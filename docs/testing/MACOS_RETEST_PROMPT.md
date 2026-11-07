# 给 macOS 上 Codex 的完整复测提示词：PATT-PDF v0.3.3.dev0

> 本文件可整篇复制到一个新对话中直接使用，不依赖其他上下文。
>
> 你的任务是**在这台 Mac 上从零安装、复测并如实报告**，不是开发新功能，也不要修改项目源码。
> - 每一项都要写明 PASS / FAIL / SKIP，并附上证据（命令、退出码、关键输出）。
> - 没有实际运行的项目标为 SKIP 并写明原因，**不得写成 PASS**。
> - 不要把 Linux、Windows 的结果或模拟测试当作 macOS 的结果。
> - 本次复测通过，也不代表“跨平台阶段完成”；这个结论由用户在汇总三平台证据后决定。

## 0. 背景与边界

- **项目：**PATT-PDF。它把 PDF 中的英文替换为简体中文，并尽量放在原位置；有 QA 状态和退出码。所有平台共用一套核心代码，平台差异集中在 `src/patt_pdf/osenv.py`。
- **版本：**v0.3.3.dev0，实验性开发版，不是稳定版。本版只在 Linux aarch64 上测试过；**从未在 macOS 上运行过**。
- **上一轮在 macOS 上发现的问题（需要你复测）：**
  - v0.3.1，Python 3.11，无 Tesseract：
    - 缺少 OCR 时，批量渲染以 `KeyError: 'status'` 中断；
    - 编码探针失败；
    - 在 ISO8859-1 locale 下，从中文路径做可编辑安装后无法导入。
  - v0.3.2，Python 3.12，独立检查：两个测试失败。
    - `test_stdlib_encoding_warning_does_not_abort_probe`：原因是测试辅助脚本只覆盖了 3.10 的接口；
    - `test_pth_with_non_ascii_path_is_decoded_with_locale_encoding`：原因是测试错误地假定 GBK 一定导致失败。
  - 两项均已在 v0.3.3 中修改。修改依据见 `docs/STATUS.md` §0a，**尚未在 macOS 上验证**。
- **禁止：**
  - 调用任何翻译 API（包括 DeepL 的 usage 查询和远程术语表），读取或输出真实密钥；
  - 读取、复制或上传用户的私人文档（课程资料、译文、翻译记忆、日志）；
  - 用 `sudo`、修改系统 locale 或系统设置；
  - 往系统字体目录写文件；
  - 推送代码，创建 release 或 PyPI 包。
- **允许：**从官方来源下载 Python 依赖、字体和 Tesseract（这属于安装测试，与翻译 API 无关）。安装 Homebrew 软件包前**先征得用户同意**。
- **工作范围：**只在新建的测试目录 `$T` 中工作，结束时只删除 `$T`。

## 1. 获取候选源码（commit 和 SHA-256 由用户提供，不要猜）

用户会给你以下两种来源之一。**拿不到用户给的完整 commit SHA 就停下来询问，不要用其他 commit 代替。**

**A. GitHub（仅当用户明确说“已推送，commit 是 …”时使用）：**
```bash
export T="$HOME/patt-macos-retest-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$T"
git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git "$T/PATT-pdf"
git -C "$T/PATT-pdf" checkout <用户给的完整SHA>
git -C "$T/PATT-pdf" rev-parse HEAD          # 必须与用户给的完全一致
git -C "$T/PATT-pdf" status --short          # 必须为空
```

**B. 离线 bundle（尚未推送时使用）：**用户通过 U 盘或私人网盘等可信途径，给你 bundle 文件、它的 SHA-256 和完整 commit。
```bash
export T="$HOME/patt-macos-retest-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$T"
B=/path/to/patt-pdf-0.3.3.dev0-<短SHA>.bundle
shasum -a 256 "$B"                           # 必须与用户给的 SHA-256 一致
git bundle list-heads "$B"                   # HEAD 与 refs/heads/main 都必须等于用户给的 commit
git clone "$B" "$T/PATT-pdf"
git -C "$T/PATT-pdf" rev-parse HEAD
git -C "$T/PATT-pdf" log --oneline | head -3 # 公开历史：本候选 + 6b969b8（以及之前的公开提交）
```
任何一项不一致，**立即停止并报告**。

## 2. 记录环境（全部写入报告，用户名替换为 `<USER>`）

```bash
cd "$T"
sw_vers; uname -m; sysctl -n machdep.cpu.brand_string
git --version
for p in python3.11 python3.12 python3.13 python3; do command -v $p >/dev/null && echo "$p: $($p -c 'import sys,platform;print(sys.version.split()[0], platform.machine())')"; done
locale; locale -a | grep -i -E "ISO8859-1|GBK|GB18030|eucCN|UTF-8" | head -20
command -v tesseract && tesseract --version 2>&1 | head -1 && tesseract --list-langs 2>&1 | head -5
ls ~/Library/Fonts /Library/Fonts 2>/dev/null | grep -i -E "noto.*(cjk|sc)" | head
```

- **Python 版本：**3.11 和 3.12 都有的话，后面 M1–M5 用两个版本**分别**跑；只有一个版本时，另一个标 SKIP。若都没有，可以征得用户同意后运行 `brew install python@3.12`，否则标 SKIP。
- **旧 locale：**macOS 通常带有 `en_US.ISO8859-1`；以上面 `locale -a` 的实际输出为准。

## 3. 安装（每个 Python 版本各建一个全新 venv）

把 `PY` 设为要测的解释器（如 `python3.12`），版本号 `V` 写入目录名：
```bash
PY=python3.12; V=312
"$PY" -m venv "$T/venv$V" && . "$T/venv$V/bin/activate"
python -m pip install --upgrade pip
pip install "$T/PATT-pdf[ocr,dev]" 2>&1 | tail -3      # 普通（非 editable）安装
patt-pdf --version                                     # 预期：patt-pdf 0.3.3.dev0
python -c "import pymupdf,numpy,fontTools,cv2;print(pymupdf.VersionBind,numpy.__version__,fontTools.version,cv2.__version__)"
pip list 2>/dev/null | grep -i -E "^(setuptools|pyyaml|pytest) "
```

**字体：**Noto Sans/Serif CJK SC，许可证为 SIL OFL 1.1。

- **已经装过时：**运行 `patt-pdf fonts`，预期 rc=0。
- **没有时：**二选一。
  - 征得同意后安装：`brew install --cask font-noto-sans-cjk font-noto-serif-cjk`。
  - 不改系统：从 https://github.com/notofonts/noto-cjk 下载 `Sans/OTF/SimplifiedChinese/NotoSansCJKsc-{Regular,Bold}.otf` 和 `Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-{Regular,Bold}.otf` 到 `$T/noto`，再运行：
    ```bash
    export PATT_PDF_FONT_SOURCE="$T/noto"
    ```
- 两种方式之后都运行：
  ```bash
  export PATT_PDF_FONT_DIR="$T/fonts"; patt-pdf fonts; echo "fonts rc=$?"
  patt-pdf doctor; echo "doctor rc=$?"                   # 记录完整输出（脱敏）
  ```

**OCR：**

- 有 Tesseract 且语言里有 `eng` 时，运行：
  ```bash
  python "$T/PATT-pdf/tools/ci_check_ocr.py" expect-present
  ```
- 用户同意时可以 `brew install tesseract`；没有 Tesseract 时，有 OCR 的那组测试标为 SKIP。

## 4. 测试套件（以实际数字为准，逐条列出跳过原因）

```bash
cd "$T/PATT-pdf"
python -m pytest -q -p no:cacheprovider -rs 2>&1 | tee "$T/pytest-py$V.txt" | tail -25
```

**有 OCR 时：**用上一节的 `ci_check_ocr.py expect-present` 确认 Tesseract 和 eng 可用。

**无 OCR 对照（必做）：**
```bash
PATT_PDF_TESSERACT="$T/no-tesseract-here" python "$T/PATT-pdf/tools/ci_check_ocr.py" expect-absent      # 必须输出 OK
PATT_PDF_TESSERACT="$T/no-tesseract-here" python -m pytest -q -p no:cacheprovider -rs 2>&1 | tee "$T/pytest-py$V-noocr.txt" | tail -25
```

**按设计会跳过的项目**（用来核对，不是预填结果）：
- 总会跳过：`test_native_windows_lock`（仅限 Windows）。
- 没有 PyYAML 时：`tests/test_ci_workflow.py`（`dev` extra 已包含 PyYAML，正常情况下不应跳过）。
- 没有任何非 UTF-8 locale 时：`test_pipeline_in_legacy_posix_locales`、`test_pth_decoding_matches_cpython_rules`。
- 无 OCR 时另外跳过 5 项，原因写明 tesseract/opencv/OCR。

除此之外的任何跳过或失败，都要逐条报告：测试名、断言和输出尾部。

## 5. 专项复测 M1–M8

每项都记录：命令、退出码、关键输出、预期、实际，以及 PASS / FAIL / SKIP。

**M1：上一轮失败的两个测试（每个 Python 版本都跑）：**
```bash
PYTHONUTF8=0 python -m pytest -q -p no:cacheprovider -rA -s tests/test_encoding.py tests/test_osenv.py -k "stdlib or third_party or helper_covers or pth" 2>&1 | tee "$T/m1-py$V.txt" | tail -30
```
- 预期：全部 PASS。
- 在输出中找到 `pth decoding (locale, locale-enc, fs-enc, result, expected): [...]` 这一行，**原样抄入报告**。它记录了这台 Mac 上各 locale 实际使用的编码，用来确认根因。
- 若 `test_pth_decoding_matches_cpython_rules` 因为“无非 UTF-8 locale”而跳过，标为 SKIP 并附上 `locale -a` 的输出。

**M2：非 UTF-8 locale 下的编码测试：**
```bash
LC_ALL=en_US.ISO8859-1 PYTHONUTF8=0 python -c "import locale,sys,io;print(getattr(locale,'getencoding',locale.getpreferredencoding)(), io.TextIOWrapper(io.BytesIO(),encoding='locale').encoding, sys.getfilesystemencoding(), sys.flags.utf8_mode)"
LC_ALL=en_US.ISO8859-1 PYTHONUTF8=0 python -m pytest -q -p no:cacheprovider -rA tests/test_encoding.py 2>&1 | tail -15
```
- 记录第一行输出。
- 预期全部 PASS。若 locale 实际没有生效（第一行仍是 UTF-8），要注明“未能制造非 UTF-8 环境”，并标 SKIP，而不是 PASS。

**M3：无 OCR 时批处理继续执行**（上一轮的 `KeyError` 问题）：
```bash
export PATT_PDF_TESSERACT="$T/no-tesseract-here"
IN="$T/in 输入"; python tests/fixtures/make_fixtures.py "$IN"; mv "$IN/truth.json" "$IN/manual_tm.json" "$T/"
S="$T/state-noocr"; TM="$T/manual_tm.json"
patt-pdf plan "$IN" --state "$S"; echo "plan rc=$?"                                                    # 预期 1
patt-pdf translate "$IN" --state "$S" --backend pseudo --max-chars 99999; echo "A1 rc=$?"              # 预期 2（3 个不可读文件被跳过）
patt-pdf estimate "$IN" --state "$S" --backend manual --manual-tm "$TM" | tail -1                      # 预期 981 字符 / 40 句段
patt-pdf render "$IN" --state "$S" --backend pseudo --files toc.pdf; echo "A2 rc=$?"                   # 预期 2
patt-pdf publish "$IN" --state "$S" --dest "$T/pub" --files toc.pdf; echo "A3 rc=$?"                  # 预期 2，且 $T/pub 中没有 toc.pdf
patt-pdf translate "$IN" --state "$S" --backend manual --manual-tm "$TM" --max-chars 99999 | grep missing_from_backend   # 预期 3
patt-pdf translate "$IN" --state "$S" --backend manual --manual-tm "$TM" --max-chars 5; echo "B2 rc=$?"        # 预期 2，"estimate 290 chars exceeds --max-chars 5"
patt-pdf render "$IN" --state "$S" --backend manual --manual-tm "$TM" 2>&1 | tee "$T/m3-render.txt"; echo "C1 rc=${PIPESTATUS[0]}"   # 预期 1
grep -c KeyError "$T/m3-render.txt"                                                                    # 预期 0
unset PATT_PDF_TESSERACT
```

预期状态：

| 文件 | 预期状态 |
|---|---|
| toc、financial、table、rotated、`报告 2026 – résumé` | `PASS` |
| decorations | `REVIEW` |
| image_text | `UNVERIFIED` |
| scanned、vector_glyphs、decor_scan | `FAIL`（`page_not_processed`） |
| two_column_cropbox | `FAIL`（测试数据中故意缺少译文） |
| damaged、encrypted、truncated | `ERROR` |

**M4：有 OCR（Tesseract + eng 可用时；否则 SKIP）：**
```bash
S2="$T/state-ocr"
patt-pdf plan "$IN" --state "$S2"; patt-pdf translate "$IN" --state "$S2" --backend manual --manual-tm "$TM" --max-chars 99999 >/dev/null
patt-pdf render "$IN" --state "$S2" --backend manual --manual-tm "$TM"; echo "rc=$?"
```
- 预期：scanned、vector_glyphs、decor_scan 为 `REVIEW`，estimate 为 1136 字符 / 44 句段，其余与 M3 相同。
- 再测“有 OCR 时规划、无 OCR 时渲染”：
  ```bash
  PATT_PDF_TESSERACT="$T/no-tesseract-here" patt-pdf render "$IN" --state "$S2" --backend manual --manual-tm "$TM" --files "*scan*"
  ```
  预期这两个文件为 `UNVERIFIED`，不出现 `KeyError`。

**M5：可编辑安装与普通安装对比**（上一轮的导入问题，需要有非 UTF-8 locale）：
```bash
mkdir -p "$T/源码 目录"; cp -R "$T/PATT-pdf/." "$T/源码 目录/"
"$PY" -m venv "$T/venv-edit$V" && "$T/venv-edit$V/bin/pip" install -q -e "$T/源码 目录[ocr]"
for M in 0 1; do echo "PYTHONUTF8=$M:"; LC_ALL=en_US.ISO8859-1 PYTHONUTF8=$M "$T/venv-edit$V/bin/python" -c "import patt_pdf;print('import OK')" 2>&1 | tail -1; done
LC_ALL=en_US.ISO8859-1 PYTHONUTF8=0 "$T/venv$V/bin/python" -c "import patt_pdf;print('regular install: import OK')"
LC_ALL=en_US.ISO8859-1 PYTHONUTF8=0 "$T/venv-edit$V/bin/python" -m patt_pdf.cli doctor 2>&1 | grep -i -A2 "warning" | head -6
"$T/venv-edit$V/bin/pip" list 2>/dev/null | grep -i setuptools
```
记录每一行输出，以及 Python 和 setuptools 的版本。依据 CPython 源码的判断如下，**请用实际结果验证**：
- **Python 3.11/3.12：**可编辑安装在 `PYTHONUTF8=0` 下很可能失败，在 `PYTHONUTF8=1` 下应成功；普通安装应成功；doctor 应给出警告。
- **Python 3.13+：**`.pth` 文件先按 UTF-8 解码，因此预期成功，doctor 也不警告。

实际结果与上述判断不符时，原样报告，不要改测试来迁就。

**M6：替换已打开的输出文件。**POSIX 系统上，文件被打开时通常仍能被替换，这和 Windows 不同。
```bash
open -a Preview "$S2/out/table.pdf" 2>/dev/null || open -a Preview "$S/out/table.pdf"; sleep 3
patt-pdf render "$IN" --state "$S" --backend manual --manual-tm "$TM" --files table.pdf; echo "rc=$?"
ls -a "$S/out" | grep -c '^\.tmp-'                                                   # 预期 0
```
- 记录实际行为：替换成功，还是给出“file is in use”提示。
- 真实打开 Preview 后才能标 PASS 或 FAIL；无法打开 Preview 时标 SKIP。
- pytest 中的 `test_posix_open_reader_does_not_block_replace` 和 `test_locked_output_is_reported_and_batch_continues` 属于模拟测试，**不能代替**本项。

**M7：报告中的路径脱敏：**
```bash
patt-pdf report "$IN" --state "$S" --out "$T/report.md"
grep -n -E "/Users/|$HOME|/private/var|/Volumes/" "$T/report.md" "$S"/plans/*.error.json "$S"/qa/*.json | head   # 预期没有输出
grep -o "Failed to open file '[^']*'" "$T/report.md" | head -2                                                      # 预期为 '<input>/truncated.pdf' 这类形式
```

**M8：中文路径、视觉效果与链接：**
```bash
patt-pdf compare "$IN" --state "$S" --out "$T/cmp" --files "t*"; patt-pdf compare "$IN" --state "$S" --out "$T/cmp" --files decorations.pdf
python -c "import pymupdf,sys; o=pymupdf.open(sys.argv[1]); print([sorted(l['uri'] for l in p.get_links()) for p in o])" "$S/out/decorations.pdf"
```
- 链接预期为 `[['https://example.org/field-guide', 'mailto:info@example.org'], ['https://example.org/map']]`。
- 用 Preview 查看 `$T/cmp` 中的图片：数字、金额和日期两侧应相同，下划线应随中文缩短，表格线保留。
- 截图保存在 `$T/screens`。

## 6. 保存证据与清理

- **证据：**把 `$T/*.txt`、`$T/report.md` 和 `$T/screens/` 复制到**用户指定的私有位置**（不要放进仓库，也不要上传）。
- **脱敏：**日志中的用户名替换为 `<USER>`，home 路径替换为 `<HOME>`。
- **清理：**用户确认后执行下面的命令。不要卸载 Homebrew 软件包或字体，不要清理全局缓存。
  ```bash
  echo "将删除：$T"; rm -rf "$T"
  ```

## 7. 反馈模板（发给用户，由用户转交 Claude）

```
候选 commit：<完整 SHA>    来源：A GitHub / B bundle（SHA-256 <…>）
macOS <版本>（<arm64|x86_64>，<芯片>）  Git <…>
Python：3.11 <x.y.z> / 3.12 <x.y.z>（没有的写“无”）   setuptools <…>  pip <…>
PyMuPDF <…> numpy <…> fontTools <…> opencv <…> pytest <…> PyYAML <…>
字体来源：<cask / notofonts OTF / 已有>   Tesseract：<版本 + eng / 无>
旧 locale：<locale -a 中的非 UTF-8 项>
doctor 输出（脱敏）：<…>

pytest py3.11 有OCR：n passed / n failed / n skipped（跳过原因：…）
pytest py3.11 无OCR：…
pytest py3.12 有OCR：…
pytest py3.12 无OCR：…
M1 两个上轮失败测试 ... PASS/FAIL/SKIP   pth decoding 行：<原样>
M2 非UTF-8 编码测试 .... PASS/FAIL/SKIP   第一行：<…>
M3 无OCR批处理 ........ PASS/FAIL         C1 rc=<…>  KeyError 次数=<…>  状态表偏差：<…>
M4 有OCR ............. PASS/FAIL/SKIP
M5 可编辑/普通安装 .... 结果表（版本 × PYTHONUTF8 × 安装方式）
M6 Preview 打开时替换 . PASS/FAIL/SKIP（实际行为：…）
M7 路径脱敏 ........... PASS/FAIL
M8 视觉/链接 .......... PASS/FAIL（截图位置：<私有路径，已脱敏>）

每个 FAIL：最小复现命令 / 预期 / 实际 / 日志位置（私有）
未验证项：真实 PDF、真实翻译 API、跨卷、信号中断、<其他>
```
