# 给 macOS 上 Codex 的核查提示词：PATT-PDF v0.4.0.dev0

> 本文件可整篇复制到一个新对话中直接使用，不依赖其他上下文。
>
> 你的任务是**在这台 Mac 上核查 v0.4.0.dev0 的新功能并如实报告**。不要开发新功能，不要修改项目源码，不要提交或推送。
> - 每一项写明 PASS / FAIL / SKIP，并附证据：命令、真实退出码、关键输出。
> - 没有实际运行的项目标为 SKIP 并写明原因，**不得写成 PASS**。
> - 发现问题时给出最小复现步骤，不要自己动手修。
> - 报告里把用户名和本机绝对路径替换为 `<USER>`、`<PATH>`。
> - 不要调用 DeepL 或任何付费翻译服务。本清单全部用 `manual`、`pseudo` 后端完成。

## 0. 背景

- **项目：**PATT-PDF，把 PDF 里的英文替换成简体中文并尽量保持原位置。
- **待核查的提交：**分支 `main`，最新提交的说明以 `Document v0.4.0.dev0` 开头。先运行 `git log --oneline -14`，把看到的提交号写进报告。这些提交只在本机，尚未推送。
- **已知状态：**本版只在 Linux aarch64 容器（CPython 3.10.12，PyMuPDF 1.28.2）里测试过：全量测试 447 通过、5 跳过（有真实文档缓存时），432 通过、20 跳过（无缓存时）。**本版从未在 macOS 上运行过**，这正是本次核查的目的。
- **本版新增：**`patt-pdf run` 一条命令；`--pages` 页码选择；进度显示与并行分析；表格按单元格切分；弯曲文字保留原文；译文异常自动修复；真实文档回归集（只存清单，测试时下载）。

## 1. 规则

- 使用 `zsh` 或 `bash`。每条命令后立刻记录 `$?`。
- 所有临时文件放在 `$TMPDIR` 下新建的目录里，结束时删除。不要在项目目录里留下新文件（`.venv` 除外，结束时也删除）。
- 项目目录记为 `$REPO`。

## 2. 环境与安装

```bash
cd "$REPO" && git status --short && git log --oneline -14
sw_vers; uname -m; python3 --version
W="$(mktemp -d)"; echo "$W"
python3 -m venv "$W/venv" && source "$W/venv/bin/activate"
python -m pip install -q '.[dev]'; echo "pip exit $?"
patt-pdf --version          # 期望：patt-pdf 0.4.0.dev0
patt-pdf fonts; patt-pdf doctor; echo "doctor exit $?"
```

记录 doctor 的完整输出（它不含本机路径）。doctor 返回 2 时写明缺什么（字体、Tesseract、英文数据），并据此判断后面哪些项只能 SKIP。

## 3. 测试套件

```bash
python -m pytest -q -p no:cacheprovider -rs 2>&1 | tail -40
```

- **C1** 记录 passed / failed / skipped 的数字，逐条列出跳过原因。没有 Tesseract 时 OCR 相关测试会跳过，这是预期；真实文档测试在第 4 步之前会跳过，也是预期。
- **C2** 任何 failed 都要贴出失败测试名和断言信息的前 20 行。

## 4. 真实文档回归（需要联网，约 10 MB，不调用翻译服务）

```bash
export PATT_CORPUS_DIR="$W/corpus"
python tools/corpus_fetch.py; echo "fetch exit $?"
python tools/corpus_check.py tests/corpus "$PATT_CORPUS_DIR"; echo "check exit $?"
python -m pytest -q -p no:cacheprovider -rs tests/test_real_corpus.py; echo "exit $?"
```

- **C3** `corpus_fetch` 每个文档一行。`REJECTED` 表示发布方换了文件（税表会改版），记录是哪一份，不算本工具的失败。
- **C4** 真实文档测试的 passed / skipped 数字。全部 7 份都下载成功时期望 16 passed。
- **C5** 确认项目目录里没有出现任何 PDF：`git status --short` 应与第 2 步相同。

## 5. `patt-pdf run`（离线，manual 后端）

先生成合成样本和固定译文表：

```bash
python tests/fixtures/make_fixtures.py "$W/fx" >/dev/null; ls "$W/fx" | head -20
mkdir "$W/in" && cp "$W/fx/toc.pdf" "$W/fx/financial.pdf" "$W/fx/decorations.pdf" "$W/in/"
cd "$W"
patt-pdf run ./in --backend manual --manual-tm "$W/fx/manual_tm.json"; echo "run exit $?"
ls translated
```

- **C6** 终端 stdout 上每个输入文件恰好一行（状态、页数、原因、输出文件）。贴出这几行。
- **C7** `translated/` 里的文件与这几行一致；状态不是 pass 的文件也在里面；没有额外的状态说明文件。
- **C8** 同一条命令再跑一次：不应出现 “exists, not written”，退出码与第一次相同。
- **C9** 手工改掉一个输出文件（`echo x > translated/toc.pdf`）再跑：该文件应报告 “exists, not written”，文件内容仍是 `x`，退出码 2。
- **C10** 中文摘要：`PATT_PDF_LANG=zh_CN.UTF-8 patt-pdf run ./in --backend manual --manual-tm "$W/fx/manual_tm.json" --out zh2`，输出行里的页数和原因应为中文，列对齐不乱。
- **C11** 无终端时的付费保护：`DEEPL_AUTH_KEY=00000000-0000-0000-0000-000000000000:fx patt-pdf run ./in </dev/null; echo $?`。期望退出码 2，stderr 说明需要 `--max-chars` 和 `--yes`，并写明 “Nothing was sent”。**不要加 `--yes`。**
- **C12** 缺少密钥：`env -u DEEPL_AUTH_KEY DEEPL_KEY_FILE="$W/none" HOME="$W/home" patt-pdf run ./in </dev/null; echo $?`。期望退出码 1，并提示如何保存密钥。

## 6. `--pages`

```bash
cd "$W" && rm -rf pw pout
patt-pdf run "$W/fx/decorations.pdf" --pages 2 --backend manual --manual-tm "$W/fx/manual_tm.json" --state pw --out pout; echo $?
python - <<'PY'
import pymupdf, sys, os
w = os.environ.get("W") or sys.exit("set W")
s = pymupdf.open(f"{w}/fx/decorations.pdf"); o = pymupdf.open(f"{w}/pout/decorations.pdf")
print("pages", s.page_count, o.page_count)
for i in range(s.page_count):
    same = s[i].get_pixmap(dpi=60).samples == o[i].get_pixmap(dpi=60).samples
    print("page", i + 1, "identical to source:", same)
PY
```

（运行前 `export W`。）

- **C13** 输出页数与源文件相同；未选中的页与源文件逐像素一致；选中的页不一致（已翻译）。
- **C14** 错误输入都应以退出码 1 结束并在 stderr 提到 `--pages`，且不产生输出：`--pages 0`、`--pages 9-7`、`--pages 99`、`--pages a`。
- **C15** 对含多个 PDF 的文件夹使用 `--pages 1`：期望退出码 1，提示只适用于单个文档。
- **C16** `patt-pdf plan "$W/fx/decorations.pdf" --state pw2 --pages 1 --no-ocr` 之后再 `--pages 1-2`：第二次的输出应包含 “reused 1 pages”。

## 7. 进度显示与并行

- **C17** 在终端里直接运行 `patt-pdf plan ./in --state pw3`：进度应在同一行刷新，结束后该行被清掉，只留下每个文件一行的结果。用文字描述你看到的现象。
- **C18** 重定向：`patt-pdf plan ./in --state pw4 2> "$W/err.log"; grep -c $'\r' "$W/err.log"; grep -c $'\x1b' "$W/err.log"`。两个计数都应为 0，日志里每个文件一行。
- **C19** `--quiet`：`patt-pdf plan ./in --state pw5 --quiet 2> "$W/q.log"; wc -c < "$W/q.log"` 应为 0。
- **C20**（需要 Tesseract 和第 4 步的缓存，否则 SKIP）并行结果一致并记录耗时：

```bash
F="$PATT_CORPUS_DIR/usgs_fs2016-3020.pdf"
time patt-pdf plan "$F" --state "$W/p1" --workers 1 --quiet
time patt-pdf plan "$F" --state "$W/p4" --workers 4 --quiet
python - <<'PY'
import json, os
w = os.environ["W"]
a = json.load(open(f"{w}/p1/plans/usgs_fs2016-3020.pdf.json")); b = json.load(open(f"{w}/p4/plans/usgs_fs2016-3020.pdf.json"))
print("same plan:", a["pages"] == b["pages"], "pages:", len(a["pages"]))
PY
```

期望 `same plan: True`。两次的 real 时间写进报告（Linux 容器上是 79 秒和 28 秒，仅供对照）。

## 8. 用“预览”查看输出（需要你或用户看屏幕；不能看就 SKIP 并说明）

用第 4 步的缓存生成三份占位译文输出（pseudo 后端的状态必然是 fail，这是预期；这里只看版面）：

```bash
cd "$W"
for f in arxiv_2302.13971v1.pdf:3 usgs_fs2016-3020.pdf:1 irs_fw9_rev2024-03.pdf:1; do
  patt-pdf run "$PATT_CORPUS_DIR/${f%%:*}" --pages "${f##*:}" --backend pseudo --state "pv-${f%%:*}" --out preview --quiet
done
open -a Preview preview/*.pdf
```

- **C21** 三份文件都能在“预览”中打开，中文可以选中和搜索。
- **C22** 论文第 3 页：表头是 7 个分开的单元格，数字列（`13.0B`、`5120` 等）未被改动；图例 `LLaMA 7B … 65B` 保持英文。
- **C23** 地图页第 1 页：沿断层线的弯曲英文标注保持原样，没有重叠的中文；页面上没有缺字母的英文单词。
- **C24** 表格页：左侧竖排的两行说明被替换为竖排中文，方框和线条位置不变。

## 9. 中断与续跑

```bash
cd "$W" && rm -rf pi oi
cat > int.py <<'PY'
import signal, subprocess, sys, time
p = subprocess.Popen(sys.argv[1:]); time.sleep(8); p.send_signal(signal.SIGINT)   # 相当于按 Ctrl-C
print("exit after interrupt:", p.wait())
PY
python int.py patt-pdf run "$PATT_CORPUS_DIR/usgs_fs2016-3020.pdf" --backend pseudo --state pi --out oi --quiet
ls pi/plans/*.parts | wc -l            # 中断前已完成的页数
patt-pdf run "$PATT_CORPUS_DIR/usgs_fs2016-3020.pdf" --backend pseudo --state pi --out oi; echo "exit of second run: $?"
```

（不要用 `cmd & kill -INT $!`：非交互 shell 的后台任务会忽略 SIGINT。没有第 4 步缓存或没有 Tesseract 时这份文件处理得很快，来不及中断，标为 SKIP。）

- **C25** 第一次被中断后的退出码（期望 130）和 stderr 的提示。
- **C26** 第二次能跑完并输出一行结果；中断后没有残留的 patt-pdf 进程（`pgrep -fl patt_pdf` 为空）；中断前完成的页被复用（第一次留下的页数大于 0 时，第二次比完整运行快）。

## 10. 清理与报告

```bash
deactivate; rm -rf "$W"; cd "$REPO" && git status --short
```

`git status --short` 应与第 2 步相同。

报告格式：

```text
PATT-PDF v0.4.0.dev0 macOS 核查报告
日期：
机器：macOS <版本>，<arm64|x86_64>，Python <版本>，PyMuPDF <版本>，Tesseract <版本或 无>
提交：<git log --oneline -1 的输出>

C1  PASS/FAIL/SKIP  <数字与说明>
…
C26 PASS/FAIL/SKIP  <说明>

发现的问题（每条：现象、最小复现命令、实际输出、期望）：
未能核查的项目及原因：
```

---

## 附：第二轮补充核查（针对 3f65b2a 之后的提交）

> 第二轮已在 `9cd953e` 上完成（结果见 `docs/STATUS.md` §0-R3）。第三轮请使用 `docs/testing/MACOS_V042_CHECK_PROMPT.md`。

上一轮在 `3f65b2a` 上的结果是 25 项 PASS、1 项 FAIL（C23）。之后有两个新提交：弯曲标注的修复，以及安装器的进度显示、镜像选择和 uv 支持。这两部分只在 Linux 上验证过。请在 Mac 上补做下面几项，规则与正文相同（不改源码、不提交、不调用付费翻译服务）。

- **D1** 重跑 C1 和 C4，记录数字。Linux 上有语料缓存时是 461 passed / 5 skipped。
- **D2** 重做 C23：同样的命令生成地图页，在“预览”里对照原页。期望 `HUNTING CREEK`、`HAYWARD FAULT`、`MAACAMA FAULT` 等沿断层线的标注完整保留英文；蓝色斜体 `San Francisco Bay` 每个字母都在；直的 `GREENVILLE FAULT`、`SAN GREGORIO FAULT`、`PAICINES FAULT` 被替换为斜向中文属于预期。
- **D3** 安装器静态检查：`bash -n install.sh`；有 ShellCheck 时 `shellcheck -s bash install.sh`。
- **D4** 安装器实跑（不装系统组件，装到临时目录，结束后卸载）。在**真实终端**里运行，看到“选择下载来源”的提问后直接回车：

```bash
W2="$(mktemp -d)"
bash install.sh --source . --no-system --no-modify-path --prefix "$W2/p" --bin-dir "$W2/b"; echo "exit $?"
"$W2/b/patt-pdf" --version
bash install.sh --uninstall --prefix "$W2/p" --bin-dir "$W2/b"
```

  记录：是否出现提问及两个选项的文字；回车后是否显示“下载来源：镜像”；五个步骤的序号是否依次出现；第 3 步是否显示预计下载量和下载进度；用的是 uv 还是 pip；总耗时；退出码（系统组件齐全时期望 0）。
- **D5** 同样的命令，提问时输入 `2`：应显示官方源，其余相同。记录耗时，与 D4 对比（这是镜像是否更快的唯一实测依据）。
- **D6** `--mirror official` 和 `--mirror cn` 各跑一次：不应再出现提问。`--mirror fastest` 应以退出码 1 报错且不创建任何文件。
- **D7** `--no-uv`：第 3 步应显示 pip 逐包下载的进度，没有长时间无输出的阶段。
- **D8**（仅在你愿意改动本机 Homebrew 软件包时做，否则 SKIP）去掉 `--no-system` 完整跑一次：记录 Homebrew 是否从镜像下载（输出里的地址）、已装字体是否被跳过、Tesseract 是否正常安装。**如果本机没有 Homebrew，不要做这一项**：通过镜像新装的 Homebrew 会长期以镜像为更新来源，这个决定应由用户本人做。
