# 给 Linux 上 Codex 的完整复测提示词：PATT-PDF v0.3.8.dev0

> 本文件可整篇复制到一个新对话中直接使用，不依赖其他上下文。
>
> 你的任务是**在这台 Linux 机器上从零安装、复测并如实报告**，不是开发新功能，也不要修改项目源码。
> - 每一项都要写明 PASS / FAIL / SKIP，并附上证据（命令、真实退出码、关键输出）。
> - 没有实际运行的项目标为 SKIP 并写明原因，**不得写成 PASS**。
> - 不要把 macOS、Windows、CI 或容器中的模拟结果当作本机结果。

## 0. 背景与边界

- **项目：**PATT-PDF。它把 PDF 中的英文替换为简体中文，并尽量放在原位置；有 QA 状态和退出码。所有平台共用一套核心代码，平台差异集中在 `src/patt_pdf/osenv.py`。
- **版本：**v0.3.8.dev0，实验性开发版。开发者只在一个 Linux aarch64 **容器**里测过（CPython 3.10.12、3.11.18、3.12.16）。上一个公开提交 `c6c9ed5` 的 CI（run 42487953018）中 Linux 4 个任务全部通过（ubuntu-24.04 3.10/3.12/3.13、ubuntu-24.04-arm 3.12）；那是 `c6c9ed5` 的结果，v0.3.8 尚未在 CI 运行。**本次是第一次在真实 Linux 机器上从零安装。**
- **范围：**macOS 和 Linux 由本项目维护；Windows 由一位 Windows 协作者负责，不在本次范围内。
- 本次复测对应 `docs/STATUS.md` §0-W 中“真实 Linux 机器”这一项。
- **三类证据分开写：**GitHub CI、本机实测、模拟/跳过。
- **禁止：**调用任何翻译 API（包括 DeepL usage 查询），读取或输出真实密钥；读取或上传用户的私人文档；`sudo`、修改系统 locale 或系统设置（安装系统软件包前先征得用户同意）；推送代码、创建 release 或 PyPI 包。
- **工作范围：**只在新建的测试目录 `$T` 中工作，结束时只删除 `$T`。

## 1. Shell 与退出码规则（必须遵守）

在 bash 中执行。**每个检查都用 `run`**：先写完整日志，再记录真实退出码；不要在被测命令后接 `| tee` 或 `| tail`。
```bash
export T="$HOME/patt-linux-retest-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$T/logs"
run() {  # 用法：run <名称> <命令...>
  local name="$1"; shift
  "$@" > "$T/logs/$name.txt" 2>&1; local rc=$?
  echo "[$name] exit=$rc   (log: \$T/logs/$name.txt)"; tail -n 25 "$T/logs/$name.txt"
  echo "$name $rc" >> "$T/logs/_exitcodes.txt"; return 0
}
```

## 2. 获取候选源码（commit 和 SHA-256 由用户提供，不要猜）

**A. GitHub（仅当用户明确说“已推送，commit 是 …”时）：**
```bash
git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git "$T/PATT-pdf"
git -C "$T/PATT-pdf" checkout <用户给的完整SHA>; git -C "$T/PATT-pdf" rev-parse HEAD; git -C "$T/PATT-pdf" status --short
```
**B. 离线 bundle（未推送时）：**
```bash
B=/path/to/patt-pdf-0.3.8.dev0-<短SHA>.bundle
sha256sum "$B"                                # 必须与用户给的 SHA-256 一致
git bundle list-heads "$B"                    # HEAD 与 refs/heads/main 都必须等于用户给的 commit
git clone "$B" "$T/PATT-pdf"; git -C "$T/PATT-pdf" rev-parse HEAD
```
任何一项不一致，**立即停止并报告**。

## 3. 记录环境（用户名替换为 `<USER>`）

```bash
cat /etc/os-release | head -4; uname -srm; git --version
for p in python3.10 python3.11 python3.12 python3.13 python3; do command -v "$p" >/dev/null && echo "$p: $("$p" -c 'import sys,platform;print(sys.version.split()[0], platform.machine())')"; done
locale; locale -a | grep -i -E "utf-?8|gbk|gb18030|iso8859|cp1252" | head -20
command -v tesseract && tesseract --version 2>&1 | head -1 && tesseract --list-langs 2>&1 | head -5
fc-list 2>/dev/null | grep -i -c "Noto.*CJK"
```
- **Python：**有 3.11 和 3.12 时各完整跑一遍（`PY=python3.11 V=311`，再 `PY=python3.12 V=312`）；只有一个版本时注明。版本缺失标 SKIP；安装系统软件包前先征得同意。
- **旧 locale：**以 `locale -a` 为准（常见 `zh_CN.gbk`、`en_US.iso88591`）；没有就把相关项标为 SKIP，不要自行生成系统 locale。

## 4. 安装（每个 Python 版本各建一个全新 venv，普通安装）

```bash
PY=python3.12; V=312
"$PY" -m venv "$T/venv$V" && . "$T/venv$V/bin/activate"
python -m pip install --upgrade pip
run preflight-$V python -S "$T/PATT-pdf/tools/preflight.py"          # 预期 exit=1：patt_pdf 还未安装（只确认它能运行、输出不含路径）
run install-$V python -m pip install "$T/PATT-pdf[ocr,dev]"
run version-$V patt-pdf --version                                     # 预期：patt-pdf 0.3.8.dev0
run preflight2-$V python -S "$T/PATT-pdf/tools/preflight.py"         # 预期 exit=0，diagnosis: no problem found
```
- `install` 失败时**原样记 FAIL**，再用辅助脚本重试一次（新目录，脚本不删除任何东西）：
  `run install-retry-$V python "$T/PATT-pdf/tools/install_check.py" --source "$T/PATT-pdf" --work "$T/ic-$V" --extras ocr,dev`
- **字体**（Noto Sans/Serif CJK SC，OFL 1.1）：已有则直接用；否则征得同意后 `sudo apt install fonts-noto-cjk`，或不改系统、把 4 个 OTF 下载到 `$T/noto` 并 `export PATT_PDF_FONT_SOURCE="$T/noto"`。
```bash
export PATT_PDF_FONT_DIR="$T/fonts"
run fonts-$V patt-pdf fonts                                            # 预期 exit=0
run doctor-$V patt-pdf doctor                                          # 记录输出（会把家目录显示为 ~）
```
- **OCR：**有 Tesseract + eng 时 `run ocr-present-$V python "$T/PATT-pdf/tools/ci_check_ocr.py" expect-present`；没有时有 OCR 的那组标 SKIP。

## 5. 测试套件

```bash
cd "$T/PATT-pdf"
run pytest-$V python -m pytest -q -p no:cacheprovider -rs
PATT_PDF_TESSERACT="$T/no-tesseract-here" run ocr-absent-$V python tools/ci_check_ocr.py expect-absent     # 必须 exit=0
PATT_PDF_TESSERACT="$T/no-tesseract-here" run pytest-noocr-$V python -m pytest -q -p no:cacheprovider -rs
```
按设计会跳过：`test_native_windows_lock`；没有旧 locale 时 3 项 locale 测试；无 OCR 时另 5 项；`test_repository_corpus_if_present`（尚无真实 PDF 语料）；`test_real_install_into_a_fresh_venv` 仅在找不到 setuptools≥70.1 的本地 wheel 时跳过。其他任何跳过或失败逐条报告。

## 6. 专项 L1–L7

**L1 全流程，长中文加空格路径：**
```bash
IN="$T/很长的 中文 目录 with spaces/segment-01/segment-02/输入 资料"; mkdir -p "$IN"
python tests/fixtures/make_fixtures.py "$IN"; mv "$IN/truth.json" "$IN/manual_tm.json" "$T/"; TM="$T/manual_tm.json"; S="$T/state $V"
(cd "$IN" && sha256sum *.pdf) > "$T/src-$V.sha"
run l1-plan-$V patt-pdf plan "$IN" --state "$S"                                                    # 预期 1
run l1-budget-$V patt-pdf translate "$IN" --state "$S" --backend manual --manual-tm "$TM" --max-chars 5    # 预期 2，"exceeds --max-chars 5"
run l1-tr-$V patt-pdf translate "$IN" --state "$S" --backend manual --manual-tm "$TM" --max-chars 99999   # 预期 2（missing_from_backend 3）
run l1-tr2-$V patt-pdf translate "$IN" --state "$S" --backend manual --manual-tm "$TM" --max-chars 99999  # 预期 1：cache_hits > 0，只剩 TM 中故意缺的 3 句，无新译文（outcome failed）
run l1-render-$V patt-pdf render "$IN" --state "$S" --backend manual --manual-tm "$TM"                    # 预期 1
run l1-report-$V patt-pdf report "$IN" --state "$S" --out "$T/report-$V.md"
run l1-cmp-$V patt-pdf compare "$IN" --state "$S" --out "$T/cmp$V" --files "t*"
run l1-pub-$V patt-pdf publish "$IN" --state "$S" --dest "$T/pub$V"
run l1-pub2-$V patt-pdf publish "$IN" --state "$S" --dest "$T/pub$V"                                # 已有文件不覆盖
(cd "$IN" && sha256sum -c --quiet "$T/src-$V.sha") && echo "sources unchanged"
find "$T" -name '.tmp-*' | wc -l                                                                     # 预期 0
grep -c -E "$HOME|/home/" "$T/report-$V.md"                                                          # 预期 0
```
预期状态（`l1-render` 日志）：toc、financial、table、rotated、`报告 2026 – résumé` 为 PASS；decorations REVIEW；image_text UNVERIFIED；scanned、vector_glyphs、decor_scan FAIL（无 OCR 规划时）；two_column_cropbox FAIL（故意缺译文）；damaged、encrypted、truncated ERROR。

**L2 有/无 OCR 混合：**有 OCR 时用新状态目录重新 plan/translate/render（三个扫描或转曲样本预期 REVIEW），再 `PATT_PDF_TESSERACT="$T/no-tesseract-here"` 渲染 `--files "*scan*"`，预期 UNVERIFIED 且无 `KeyError`。

**L3 过期计划：**
```bash
cp "$IN/table.pdf" "$T/table.bak"; python -c "import pymupdf,sys;d=pymupdf.open(sys.argv[1]);d[0].insert_text((50,50),'x');d.saveIncr()" "$IN/table.pdf"
run l3-$V patt-pdf render "$IN" --state "$S" --backend manual --manual-tm "$TM" --files table.pdf   # 预期 1，"source file content changed"
cp "$T/table.bak" "$IN/table.pdf"
```

**L4 真实中断与续跑：**
```bash
run l4-pytest-$V python -m pytest -q -p no:cacheprovider -rA -s tests/test_process_interrupt.py tests/test_workflow_paths.py
grep -E "SIG(INT|KILL)" "$T/logs/l4-pytest-$V.txt"                  # [SIGINT] 和 [SIGKILL] 都必须 PASSED，不得 SKIP
```
然后在终端里亲手做一次：对新的状态目录执行 render，输出两三行后按 Ctrl+C，记录退出码；`ls -a <状态>/out | grep -c '^\.tmp-'` 预期 0；再执行一次 render 续跑并记录退出码与状态。

**L5 输出被打开时替换：**`xdg-open "$S/out/table.pdf"`（有桌面时）或 `python -c "import time,sys;f=open(sys.argv[1],'rb');time.sleep(30)" "$S/out/table.pdf" &`，随后重新 render `--files table.pdf`，预期 exit=0、无 `.tmp-` 残留。记录实际行为；这是 POSIX 行为，不代表 Windows。

**L6 安装诊断与隐私：**
```bash
run l6-pre-$V python -S "$T/PATT-pdf/tools/preflight.py" --json
grep -c -E "$HOME|$USER" "$T/logs/l6-pre-$V.txt"                     # 预期 0
run l6-ic-$V python "$T/PATT-pdf/tools/install_check.py" --source "$T/PATT-pdf" --work "$T/ic dry 目录" --dry-run
```
旧 locale 存在时，另做可编辑安装对比（中文目录、`LC_ALL=<旧locale>` 与 `PYTHONUTF8=0/1`），并用 `python -S tools/preflight.py` 记录其结论是否与 `import patt_pdf` 的实际结果一致。不要使用 `--private-details` 或 `xxd` 把路径放进报告。

**L7 视觉：**查看 `$T/cmp$V` 的对照图：数字、金额、负号、日期两侧相同；下划线随中文缩短；表格线保留。链接：
`python -c "import pymupdf,sys;o=pymupdf.open(sys.argv[1]);print([sorted(l['uri'] for l in p.get_links()) for p in o])" "$S/out/decorations.pdf"`，预期 `[['https://example.org/field-guide', 'mailto:info@example.org'], ['https://example.org/map']]`。

最后 `cat "$T/logs/_exitcodes.txt"`。

## 7. 证据、脱敏与清理

- 把 `$T/logs/`、报告、对照图复制到**用户指定的私有位置**；不要放进仓库、不要上传。
- 用户名替换为 `<USER>`，家目录替换为 `<HOME>`；不要附带 `.pth` 的十六进制或任何可还原私人路径的编码。分享前逐行检查；脱敏只是尽力而为。
- 用户确认后：`deactivate 2>/dev/null; echo "将删除：$T"; rm -rf "$T"`。不要卸载系统软件包或字体。

## 8. 反馈模板（发给用户，由用户转交 Claude；不要自动发送）

```
候选 commit：<完整 SHA>    来源：A GitHub / B bundle（SHA-256 <…>）
证据类别：本机实测（真实 Linux 机器 / 虚拟机 / 容器：<哪一种>）
发行版 <…>  内核 <…>  架构 <x86_64|aarch64>  Python：<各版本>  pip <…>  setuptools <…>
PyMuPDF <…> numpy <…> fontTools <…> opencv <…> pytest <…>
字体来源：<apt / OTF 目录>   Tesseract：<版本 + eng / 无>   旧 locale：<…/无>
preflight（安装前/后）：exit=<…>/<…>；doctor（脱敏）：<…>
pytest 有OCR / 无OCR（各版本）：n passed / n failed / n skipped（逐条列出跳过原因）
L1 全流程 ........ PASS/FAIL  各步 exit：<…>  源文件不变：是/否  .tmp 残留：<…>  报告含路径：<…>
L2 OCR 混合 ...... PASS/FAIL/SKIP
L3 过期计划 ...... PASS/FAIL
L4 中断/续跑 ..... pytest PASS/FAIL；SIG 行：<…>；手动 Ctrl+C exit=<…>；续跑 exit=<…>
L5 打开时替换 .... PASS/FAIL/SKIP（实际行为：…）
L6 诊断/隐私 ..... PASS/FAIL（preflight 含路径次数：<…>）；旧 locale 对比：<表/SKIP>
L7 视觉/链接 ..... PASS/FAIL（图片位置：私有）
_exitcodes.txt：<粘贴>
每个 FAIL：最小复现 / 预期 / 实际 / 日志位置（私有）
未验证项：真实 PDF、真实翻译 API、<其他>
```
