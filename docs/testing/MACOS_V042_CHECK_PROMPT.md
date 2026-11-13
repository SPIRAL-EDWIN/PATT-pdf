# 给 macOS 上 Codex 的核查提示词：PATT-PDF v0.4.2.dev0（第三轮）

> 本轮已在 `a92eba7` 上完成，E1–E9 全部通过（结果见 `docs/STATUS.md` §0-R4）。下一轮请使用 `docs/testing/MACOS_V043_CHECK_AND_PUSH_PROMPT.md`。

> 本文件可整篇复制到一个新对话中直接使用。
>
> 任务是**在这台 Mac 上核查安装器的修复并如实报告**。不要修改项目源码，不要提交或推送，不要调用付费翻译服务。
> - 每一项写明 PASS / FAIL / SKIP，附命令、真实退出码和关键输出。没有实际运行的写 SKIP 和原因。
> - 报告里把用户名和本机绝对路径替换为 `<USER>`、`<PATH>`。
> - **不要为了让命令通过而设置 `LC_ALL=C` 或改用别的 bash。** 本轮要验证的正是默认环境。如果某项只有改了环境才通过，写 FAIL，并把改环境后的结果作为补充信息。

## 0. 背景

- **待核查的提交：**分支 `main` 的最新提交。`git log --oneline -3` 里应能看到说明以 `Installer: complete under bash 3.2` 开头的提交，`patt-pdf --version` 应为 `0.4.2.dev0`。把实际看到的提交号写进报告。
- **上一轮（`9cd953e`）的问题：**安装器在 macOS 自带 Bash 3.2、`LC_ALL=C.UTF-8` 下，第 1 步之后报 `SOURCE…: unbound variable` 并中断，却返回退出码 0；测试套件因此有 9 项失败。
- **本轮的修改：**脚本里紧跟中文的变量一律写成 `${名字}`；退出陷阱保留真实退出码，凡不是正常走到结尾的退出都不会返回 0；测试改为对本机每个可用的 bash 都跑一遍（macOS 上包含 `/bin/bash` 3.2）。
- **已知状态：**这些修改只在 Linux 上验证过。在 Linux 上用源码编译的 Bash 3.2.57 能在 Latin-1 区域设置下复现两个问题，修复后消失；但 macOS 上 `C.UTF-8` 这个确切条件在 Linux 上复现不出来，所以需要本轮确认。

## 1. 准备

```bash
cd "$REPO" && git status --short && git log --oneline -3
sw_vers; uname -m; /bin/bash --version | head -1; echo "LC_ALL=${LC_ALL-<unset>} LANG=${LANG-<unset>}"; locale
W="$(mktemp -d)"; export W
python3.12 -m venv "$W/venv" && source "$W/venv/bin/activate"
python -m pip install -q '.[dev]'; echo "pip exit $?"
patt-pdf --version
```

`locale` 的完整输出写进报告（它决定了 bash 如何解析字符）。

## 2. 核查项

**E1 上一轮的最小复现，原样重跑。** 期望：依次出现第 1 到第 5 步，退出码 0（`patt-pdf doctor` 报告不完整时为 2），命令可运行。

```bash
W2="$(mktemp -d)"
LC_ALL=C.UTF-8 PATT_PDF_LANG=zh_CN.UTF-8 /bin/bash install.sh \
  --source . --no-system --no-modify-path --mirror official \
  --prefix "$W2/p" --bin-dir "$W2/b"; echo "exit $?"
"$W2/b/patt-pdf" --version; echo "version exit $?"
/bin/bash install.sh --uninstall --prefix "$W2/p" --bin-dir "$W2/b"; echo "uninstall exit $?"
```

**E2 默认环境，不设任何区域变量。** 在本机默认的 shell 环境里直接运行（不加 `LC_ALL=`、不加 `PATT_PDF_LANG=`），其余参数同 E1。记录五步是否齐全、提示语是中文还是英文、退出码。

**E3 其他区域设置。** 分别用 `LC_ALL=zh_CN.UTF-8`、`LC_ALL=en_US.UTF-8`、`LC_ALL=en_US.ISO8859-1`、`LC_ALL=C` 各跑一次 E1 的命令（保留 `PATT_PDF_LANG=zh_CN.UTF-8`）。四次都应完成五步。

**E4 异常中断不得返回 0。** 用一份故意带错的脚本副本验证，不改动仓库里的文件：

```bash
sed 's|^  fetch_source$|  echo "$PATT_NO_SUCH_VARIABLE"; fetch_source|' install.sh > "$W/broken.sh"
grep -c 'PATT_NO_SUCH_VARIABLE' "$W/broken.sh"        # 应为 1
W3="$(mktemp -d)"
/bin/bash "$W/broken.sh" --source . --no-system --no-modify-path --mirror official \
  --prefix "$W3/p" --bin-dir "$W3/b"; echo "exit $?"
ls "$W3/b" 2>&1; ls "$W3/p" 2>&1
```

期望：stderr 有 `unbound variable` 和 `the installer stopped before it finished`；退出码**不是 0**；没有命令链接和虚拟环境留下。

**E5 测试套件。** `python -m pytest -q -p no:cacheprovider -rs 2>&1 | tail -30`。期望 0 failed。记录 passed / skipped 数字和每条跳过原因。只跑安装器部分的数字也记一下：`python -m pytest -q -p no:cacheprovider -rs tests/test_install_script.py`。

**E6 真实文档回归。** `export PATT_CORPUS_DIR="$W/corpus"; python tools/corpus_fetch.py; python -m pytest -q -p no:cacheprovider tests/test_real_corpus.py`。期望 16 passed。

**E7 镜像提问与进度（真实终端）。** 在真实终端里运行下面的命令两次：第一次在提问处直接回车，第二次输入 `2`。**两次不要同时进行**，每次用独立的空缓存，这样耗时才有可比性。

```bash
for round in mirror official; do
  W4="$(mktemp -d)"
  time PIP_CACHE_DIR="$W4/cache" /bin/bash install.sh --source . --no-system --no-modify-path --no-uv \
    --prefix "$W4/p" --bin-dir "$W4/b"; echo "$round exit $?"
  /bin/bash install.sh --uninstall --prefix "$W4/p" --bin-dir "$W4/b"; rm -rf "$W4"
done
```

记录：提问和两个选项是否出现；选择后显示的下载来源；第 3 步的预计下载量和 pip 的逐包进度；两次的 real 时间。

**E8 `--mirror` 参数。** `--mirror cn`、`--mirror official` 各一次（不应提问），`--mirror fastest` 一次（退出码 1，不创建任何文件）。

**E9 uv（本机有 `uv` 才做，否则 SKIP；不要为此安装 uv）。** 去掉 E7 命令里的 `--no-uv` 跑一次，第 3 步应显示“安装工具：uv”。记录耗时。

**E10 Homebrew 部分（可选，默认 SKIP）。** 只有在用户明确同意改动本机 Homebrew 软件包时才做。去掉 `--no-system`，仍然装到临时目录：

```bash
W5="$(mktemp -d)"
/bin/bash install.sh --source . --no-modify-path --prefix "$W5/p" --bin-dir "$W5/b"; echo "exit $?"
/bin/bash install.sh --uninstall --prefix "$W5/p" --bin-dir "$W5/b"
```

这会执行 `brew install tesseract`（已安装时可能顺带升级它和依赖库），并在本机没有 Noto CJK 字体文件时下载约 235 MB 字体。记录：输出里 Homebrew 的下载地址是否为镜像；字体是否被跳过；Tesseract 的版本前后是否变化。**本机没有 Homebrew 时不要做这一项。**

## 3. 清理与报告

```bash
deactivate; rm -rf "$W" "$W2" "$W3"; cd "$REPO" && git status --short
```

`git status --short` 应与开始时相同。报告格式：

```text
PATT-PDF v0.4.2.dev0 macOS 核查报告（第三轮）
日期：
机器：macOS <版本>，<架构>，/bin/bash <版本>，默认 LC_ALL/LANG，Python <版本>
提交：<git log --oneline -1>

E1  PASS/FAIL/SKIP  <说明>
…
E10 PASS/FAIL/SKIP  <说明>

发现的问题（现象、最小复现命令、实际输出、期望）：
未能核查的项目及原因：
```
