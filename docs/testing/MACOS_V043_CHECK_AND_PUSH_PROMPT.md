# 给 macOS 上 Codex 的提示词：核查 PATT-PDF v0.4.3.dev0，通过后推送到 GitHub

> 本文件可整篇复制到一个新对话中直接使用。
>
> 任务分两段：**先核查，全部通过后才推送**。不要修改项目源码，不要新建提交，不要调用付费翻译服务。
> - 每一项写明 PASS / FAIL / SKIP，附命令、真实退出码和关键输出。没有实际运行的写 SKIP 和原因。
> - 报告里把用户名和本机绝对路径替换为 `<USER>`、`<PATH>`。
> - 不要为了让命令通过而改环境（`LC_ALL=C`、换 bash 等）。只有改了环境才通过的项记为 FAIL。
> - **任何一项 FAIL，或任何一条推送门槛不满足：停止，不要推送，把情况报告给用户。**

## 0. 背景

- **仓库：**本机 `~/Documents/Projects/PATT-pdf`（记为 `$REPO`）。公开仓库是 `https://github.com/SPIRAL-EDWIN/PATT-pdf`，公开 `main` 目前停在 `703efcd`。
- **本地分支：**
  - `main`：要推送的分支，从 `703efcd` 线性延伸，全部提交署名为 `PATT-PDF dev <dev@patt-pdf.invalid>`。
  - `dev-private`：早期私有开发历史，提交里含本机路径。**永远不要推送这个分支。**
  - `codex/one-line-installer`：指向 `703efcd` 的旧分支，不需要推送。
- **本地仓库没有配置远程。** 推送时不要给它添加远程，按第 3 节用一次性地址推送（或沿用你以前推送用的独立工作树）。
- **v0.4.3.dev0 相对上一轮实测的 `a92eba7`（v0.4.2.dev0）：**只有文档、版本号和 `install.sh` 里一段注释的变化，新增 `CHANGELOG.md` 和本文件。Python 包和安装器的逻辑没有改动。所以本轮是一次较短的确认，加上推送。
- **已知未验证、且本轮不要求验证的：**安装器的 Homebrew 部分、没有 Homebrew 的 Mac、Intel Mac。这些已如实写在 `docs/STATUS.md` 里，不构成推送门槛。

## 1. 核查

```bash
cd "$REPO" && git status --short && git log --oneline -5
git rev-parse HEAD
W="$(mktemp -d)"; export W
python3.12 -m venv "$W/venv" && source "$W/venv/bin/activate"
python -m pip install -q '.[dev]'; echo "pip exit $?"
patt-pdf --version          # 期望：patt-pdf 0.4.3.dev0
patt-pdf fonts; patt-pdf doctor; echo "doctor exit $?"
```

**F1 候选确认。** `git status --short` 为空；`git log --oneline -3` 里能看到说明以 `v0.4.3.dev0:` 开头的提交；`git log --oneline 703efcd..HEAD | wc -l` 不少于 18；版本为 `0.4.3.dev0`。把 `git rev-parse HEAD` 的完整提交号写进报告，后面推送的必须是它。

**F2 相对上一轮只改了文档。** 运行：

```bash
git diff --stat a92eba7 HEAD
git diff a92eba7 HEAD -- src/ tests/ tools/ .github/ | grep -E '^[+-]' | grep -v -E '^(\+\+\+|---)'
git diff a92eba7 HEAD -- install.sh | grep -E '^[+-]' | grep -v -E '^(\+\+\+|---)' | grep -v -E '^[+-][[:space:]]*#'
```

期望：第二条命令只输出 `__version__` 的一减一加两行（`tests/`、`tools/`、`.github/` 没有变化）；第三条命令没有输出（`install.sh` 只改了注释行）。如果看到别的改动，记为 FAIL 并贴出来。

**F3 测试套件。** 先准备真实文档，再跑全量：

```bash
export PATT_CORPUS_DIR="$W/corpus"
python tools/corpus_fetch.py; echo "fetch exit $?"
python -m pytest -q -p no:cacheprovider -rs 2>&1 | tail -25
```

期望 0 failed。上一轮是 482 passed / 1 skipped（跳过的是 Windows 原生锁）。记录数字和每条跳过原因。`corpus_fetch` 报 `REJECTED` 表示发布方换了文件，记录是哪一份，不算失败，但相应测试会跳过。

**F4 安装器，默认环境。** 用系统 bash，不设任何区域变量：

```bash
W2="$(mktemp -d)"
/bin/bash install.sh --source . --no-system --no-modify-path --mirror cn \
  --prefix "$W2/p" --bin-dir "$W2/b"; echo "install exit $?"
"$W2/b/patt-pdf" --version; echo "version exit $?"
/bin/bash install.sh --uninstall --prefix "$W2/p" --bin-dir "$W2/b"; echo "uninstall exit $?"
```

期望：五个步骤依次出现，三个退出码都是 0，版本为 `0.4.3.dev0`。

**F5 上两轮的回归点。** 各跑一次，确认没有倒退：

```bash
# 第二轮的故障命令（应完成五步，exit 0）
W3="$(mktemp -d)"
LC_ALL=C.UTF-8 PATT_PDF_LANG=zh_CN.UTF-8 /bin/bash install.sh --source . --no-system --no-modify-path \
  --mirror official --prefix "$W3/p" --bin-dir "$W3/b"; echo "exit $?"
/bin/bash install.sh --uninstall --prefix "$W3/p" --bin-dir "$W3/b"

# 第一轮的地图页（在“预览”里对照原页；不能看屏幕就写 SKIP）
patt-pdf run "$PATT_CORPUS_DIR/usgs_fs2016-3020.pdf" --pages 1 --backend pseudo --state "$W/map" --out "$W/map-out" --quiet; echo "exit $?"
open -a Preview "$W/map-out/usgs_fs2016-3020.pdf"
```

地图页期望：`HUNTING CREEK`、`HAYWARD FAULT`、`MAACAMA FAULT` 和蓝色斜体 `San Francisco Bay` 完整保留英文。命令退出码 2 是 pseudo 后端的预期结果。

**F6 一条命令的完整流程（离线）。**

```bash
python tests/fixtures/make_fixtures.py "$W/fx" >/dev/null
mkdir "$W/in" && cp "$W/fx/toc.pdf" "$W/fx/financial.pdf" "$W/in/"
cd "$W" && patt-pdf run ./in --backend manual --manual-tm "$W/fx/manual_tm.json"; echo "run exit $?"; ls translated; cd "$REPO"
```

期望：stdout 两行，都是 `pass`，退出码 0，`translated/` 里两个 PDF。

**F7 公开内容检查。** 确认要推送的提交里没有不该公开的东西：

```bash
git diff --stat 703efcd HEAD | tail -1
git log 703efcd..HEAD --format='%an <%ae> | %cn <%ce>' | sort -u
git ls-files | grep -i -E '\.(pdf|key|env|jsonl|otf|ttf|ttc)$'
git grep -n -I -E "$(whoami)|$HOME" -- . ; echo "grep exit $? (1 = nothing found)"
git log 703efcd..HEAD --format='%B' | grep -n -E "$(whoami)|$HOME"; echo "grep exit $? (1 = nothing found)"
git grep -n -I -E '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(:fx)?' -- . \
  | grep -v -E '00000000-0000-0000-0000-000000000000|11111111-2222-3333-4444-555555555555'
```

期望：
- 作者和提交者只有 `PATT-PDF dev <dev@patt-pdf.invalid>` 一种。
- 没有被跟踪的 PDF、密钥、翻译记忆（`.jsonl`）或字体文件。
- 两条 `grep` 都没有找到本机用户名或主目录路径（退出码 1）。
- 最后一条没有输出。仓库里只有两个占位密钥（全零的，和 `11111111-2222-3333-4444-555555555555`），都已被过滤；出现任何别的形似 DeepL 密钥的字符串都算 FAIL。

任何一条不满足，记为 FAIL 并停止。

**清理（核查部分）：**

```bash
deactivate; rm -rf "$W" "$W2" "$W3"; cd "$REPO" && git status --short
```

## 2. 推送门槛（全部满足才进入第 3 节）

1. F1–F7 全部 PASS（F5 的“预览”目视一项允许 SKIP，其余不允许）。
2. 核查前后 `git status --short` 都为空，`git rev-parse HEAD` 没有变化。
3. `git merge-base --is-ancestor 703efcd HEAD; echo $?` 输出 0（本地 `main` 是公开线的直接延伸）。
4. 公开 `main` 仍是 `703efcd`：

   ```bash
   git ls-remote https://github.com/SPIRAL-EDWIN/PATT-pdf.git refs/heads/main
   ```

   如果这里不是 `703efcd…`（有人在此期间推送过），**不要推送，不要 rebase 或合并**，报告给用户。
5. 用户在本轮对话里明确同意推送。如果没有，先把核查报告交给用户并询问。

## 3. 推送

只推送 `main` 这一个分支，快进，不带标签，不强制：

```bash
cd "$REPO"
HEAD_SHA="$(git rev-parse HEAD)"
git push https://github.com/SPIRAL-EDWIN/PATT-pdf.git "$HEAD_SHA:refs/heads/main"; echo "push exit $?"
```

- **不要**使用 `--force`、`--force-with-lease`、`--all`、`--mirror`、`--tags`。
- **不要**推送 `dev-private` 或 `codex/one-line-installer`。
- 不要给本地仓库添加远程（`git remote add`）。如果你以前是通过独立工作树推送的，沿用那个方式也可以，前提是推送上去的提交号等于 `$HEAD_SHA`。
- 如果推送被拒绝（non-fast-forward、权限、网络），停止并把原始报错交给用户，不要换别的方式重试。
- 不要创建 GitHub Release，不要打标签，不要发布到 PyPI。

## 4. 推送后核对

```bash
git ls-remote https://github.com/SPIRAL-EDWIN/PATT-pdf.git
```

- **G1** `refs/heads/main` 等于 `$HEAD_SHA`；远端没有出现 `dev-private`。
- **G2** 打开 `https://github.com/SPIRAL-EDWIN/PATT-pdf`：README 顶部的展示图正常显示；“安装”一节的一行命令还在；徽章正常。
- **G3** 公开的安装脚本就是这个版本：

  ```bash
  curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh | shasum -a 256
  shasum -a 256 install.sh
  ```

  两个哈希应相同（raw 地址有缓存，不一致时等几分钟再试一次）。
- **G4** 从公开仓库真正装一次（这是 README 里那条命令的等价形式，装到临时目录，不装系统组件）：

  ```bash
  W4="$(mktemp -d)"
  curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh \
    | /bin/bash -s -- --no-system --no-modify-path --mirror cn --prefix "$W4/p" --bin-dir "$W4/b"; echo "exit ${PIPESTATUS[1]}"
  "$W4/b/patt-pdf" --version
  curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh \
    | /bin/bash -s -- --uninstall --prefix "$W4/p" --bin-dir "$W4/b"; rm -rf "$W4"
  ```

  期望：第 2 步显示从 GitHub 下载源码，五步完成，版本 `0.4.3.dev0`。这一项验证的是“脚本从管道读入”加“源码从 GitHub 下载”这条真实用户路径，此前只在 Linux 上跑过。
- **G5** GitHub Actions：打开仓库的 Actions 页，找到这次推送触发的 `tests` 运行。记录运行编号和每个作业的结果（Linux 4 个、macOS 3 个）。这是 `703efcd` 之后第一次 CI 运行，新增了两个步骤（真实文档回归、macOS 系统 bash 安装）。**有作业失败不要自行修复**，把失败作业的名称、步骤和日志里的关键报错记下来交给用户。运行可能要十几分钟；等不到结束就记录当时的状态。

## 5. 报告

```text
PATT-PDF v0.4.3.dev0 macOS 核查与推送报告
日期：
机器：macOS <版本>，<架构>，/bin/bash <版本>，Python <版本>
候选提交：<完整提交号>

F1 … F7  PASS/FAIL/SKIP  <说明>
推送门槛 1–5：<逐条 是/否>
推送：<已推送 / 未推送及原因>，push 退出码
G1 … G5  PASS/FAIL/SKIP  <说明>

发现的问题（现象、最小复现命令、实际输出、期望）：
未能核查的项目及原因：
```
