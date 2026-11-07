# PATT-PDF v0.3.2.dev0 复测提示词（macOS 与 Windows 通用，可直接复制给对应电脑上的 Codex）

> 你的任务是**复测与报告**，不是开发新功能。只报告实际运行过的结果；没运行的项目标 SKIP 并写明原因。上一轮针对的是 v0.3.1.dev0（`6b969b8`），本轮针对 v0.3.2.dev0，**不要把上一轮的结果抄过来**。

## 0. 边界

**禁止：**
- 调用任何翻译 API，包括 DeepL 的 usage 查询和远程术语表；
- 读取或输出真实密钥，接触用户的私人文档；
- 修改注册表或系统 locale，以管理员身份安装软件；
- 推送代码，创建 release 或 PyPI 包。

**允许：**
- 从官方来源下载依赖、字体和 Tesseract 到隔离目录（这属于安装测试，与翻译 API 无关）。

**工作范围：**只在新建的测试目录 `$T` 中工作，结束后只删除 `$T`。

## 1. 取源（commit 由用户提供，不要自己猜）

用户会给出以下其中一种：

- **A. GitHub：**
  ```
  git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git "$T/PATT-pdf"
  git -C "$T/PATT-pdf" checkout <用户给的完整 SHA>
  git -C "$T/PATT-pdf" rev-parse HEAD
  ```
  输出必须等于用户给的 SHA。
- **B. bundle：**用户给出文件名、SHA-256 和完整 commit。先核对文件的 SHA-256，再运行 `git bundle list-heads <bundle>`，确认 HEAD 等于用户给的 commit，然后 `git clone <bundle> "$T/PATT-pdf"`。

不一致、仓库为空或 commit 不存在时，**立即停止并报告**。

## 2. 安装（两种方式都测）

**macOS / Linux：**
```bash
export T="$HOME/patt-retest-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$T"
python3 -m venv "$T/venv" && . "$T/venv/bin/activate" && python -m pip install --upgrade pip
pip install "$T/PATT-pdf[ocr,dev]"                       # 普通安装（推荐方式）
patt-pdf --version                                        # 预期 0.3.2.dev0
patt-pdf doctor; echo "doctor rc=$?"
```

**Windows（PowerShell）：**
```powershell
$T = Join-Path $env:USERPROFILE ("PATT 复测 " + (Get-Date -Format "yyyyMMdd-HHmmss")); New-Item -ItemType Directory $T | Out-Null
py -3.12 -m venv "$T\venv"; & "$T\venv\Scripts\Activate.ps1"; python -m pip install --upgrade pip
pip install "$T\PATT-pdf[ocr,dev]"
patt-pdf --version; patt-pdf doctor; "doctor rc=$LASTEXITCODE"
```

**字体和 Tesseract：**沿用上一轮的隔离方式，并设置 `PATT_PDF_FONT_SOURCE`、`PATT_PDF_FONT_DIR`、`PATT_PDF_TESSERACT`，然后运行 `patt-pdf fonts`。请记录 `doctor` 的全部输出（用户名替换为 `<USER>`）。

## 3. 测试套件（以实际数字为准）

```
python -m pytest -q -p no:cacheprovider -rs 2>&1 | tee "$T/pytest.txt" | tail -25
```

**按设计会跳过的项目**（用来核对跳过原因是否合理，不是预先写好的结果）：

- **Windows：**
  - POSIX 权限位测试 2 项；
  - POSIX locale 模拟 2 项（`test_pipeline_in_legacy_posix_locales`、`test_pth_with_non_ascii_path…`）；
  - `test_posix_open_reader_does_not_block_replace` 1 项。
  - `test_native_windows_lock` 在 Windows 上**应当运行**。
- **macOS：**
  - `test_native_windows_lock` 1 项；
  - 没有非 UTF-8 locale 时，locale 模拟 2 项。
- **没有 Tesseract 时：**另外跳过 5 项，原因写明 tesseract/opencv/OCR。

出现任何其他跳过原因或任何失败，都逐条写入报告。

## 4. 针对上一轮发现的复测

把每项的命令、退出码和关键输出写入报告。

**R1（W03 / macOS P1）无 OCR 时批处理继续：**
- 在没有 Tesseract 的环境中（macOS 上没装；Windows 上让 PATH、`PATT_PDF_TESSERACT` 和默认目录都找不到它），按 `docs/testing/WINDOWS_CODEX_PROMPT.md` 或 `MACOS_CHECKLIST.md` 第 6–7 节生成样本，再运行 plan、translate（manual）和 render。
- 预期：
  - 输出中不出现 `KeyError`；
  - `scanned`、`vector_glyphs`、`decor_scan` 为 `FAIL`（`page_not_processed`）；
  - 其余文件照常渲染，并有与上一轮有 OCR 时相同的状态；
  - render 退出码为 1（因为存在 damaged/encrypted/truncated 这几个出错文件）。
- 再测一种情况：**先在有 OCR 的环境中 plan，再在无 OCR 的环境中 render**（Windows：plan 时设置 `PATT_PDF_TESSERACT`，render 前移除它，并确认 doctor 显示找不到）。
  - 预期：三个扫描/转曲样本为 `UNVERIFIED`（`residual_check_skipped`：规划时已识别并翻译，渲染后缺 OCR 无法复查残留英文）；绝不能是 pass；
  - 其他文件继续处理，不出现 `KeyError`。

**R2（W03 文件锁）：**
- Windows：pytest 中的 `test_native_windows_lock` 应 PASS。另按上一轮的 `CreateFileW` 方法手动加锁，再 render `table.pdf`。
  - 预期：rc=1；提示中含 `in use` 和 `close the output PDF`；锁定前后的 SHA-256 相同；没有 `.tmp-*` 残留。
- macOS：在 Preview 中打开 `out/table.pdf` 后重新 render。macOS 通常允许替换，请记录实际行为，没有实际操作就标 SKIP。

**R3（W01）编码探针：**
```
PYTHONUTF8=0 python -m pytest -q -p no:cacheprovider -rA tests/test_encoding.py
```
Windows 上用 `$env:PYTHONUTF8="0"`。
- 预期：全部 PASS；输出中列出 `EncodingWarnings from other code (not failing): [...locale.py...]` 或 `none`。
- 记录 Python 版本，以及以下一行的输出：
  ```
  python -c "import locale,sys; print(getattr(locale,'getencoding',locale.getpreferredencoding)(), sys.flags.utf8_mode)"
  ```

**R4（macOS 中文路径下的可编辑安装）：**仅 macOS。在名字含中文的目录中另建一个 venv，运行 `pip install -e`，再执行：
```
LC_ALL=en_US.ISO8859-1 PYTHONUTF8=0 python -c "import patt_pdf"
```
- 预期仍会失败。这是 Python 按 locale 编码读取 `.pth` 的已知行为。
- 接着确认以下三种情况：
  - 同一命令加上 `PYTHONUTF8=1` 后可以导入；
  - 普通安装（`pip install .`）在同一 locale 下可以导入；
  - `patt-pdf doctor` 输出了警告。
- 记录 setuptools 的版本。

**R5（W02）报告不含本机路径：**
- 生成样本、plan、render、report 后，在 `$S` 和报告中搜索用户名、`Users`、`C:` 和 `/Users/`。
- 预期：只出现 `<input>/…`、`<state>/…` 或 `<path>/文件名`。

**R6（W04）字体顺序：**仅 Windows。
- 在用户字体目录 `%LOCALAPPDATA%\Microsoft\Windows\Fonts` 和一个通过 `PATT_PDF_FONT_SOURCE` 指定的目录中，放入同名的静态字体，然后运行：
  ```
  python -c "from patt_pdf.fonts import search_dirs, find_system_source; print(search_dirs()); print(find_system_source(('sans', False)))"
  ```
- 预期：顺序为环境变量目录 → 用户目录 → 系统目录，没有重复，也没有 `/usr/...` 之类的 POSIX 路径；命中的是环境变量目录中的文件。
- 不要往系统字体目录写入任何文件。

**R7（W05）长路径：**仅 Windows。
- 用上一轮的脚本，以普通路径（307 字符）运行 plan。
- 预期：rc=1，错误信息中说明 `LongPathsEnabled` 和建议；`doctor` 显示 `windows_long_paths_enabled False`。
- 不修改注册表。

## 5. 清理

只删除 `$T`。不要卸载 Python、Tesseract 或字体，也不要清理全局缓存。

## 6. 反馈模板

```
系统/版本/架构:            Python:            setuptools:
commit:（完整 SHA）        取源: A/B          PyMuPDF / numpy / fontTools / opencv:
doctor 输出（脱敏）:
pytest: n passed / n failed / n skipped（逐条列出跳过原因与失败）
R1 无 OCR 批处理 ......... PASS/FAIL/SKIP
R1b 有 OCR 规划→无 OCR 渲染  PASS/FAIL/SKIP
R2 文件锁 ............... PASS/FAIL/SKIP（原生锁 / Preview）
R3 编码探针 ............. PASS/FAIL（Python 版本、默认编码）
R4 可编辑安装 ............ 预期失败已复现/未复现；PYTHONUTF8=1、普通安装、doctor 警告 各 PASS/FAIL；SKIP（非 macOS）
R5 路径脱敏 ............. PASS/FAIL
R6 字体顺序 ............. PASS/FAIL/SKIP
R7 长路径诊断 ............ PASS/FAIL/SKIP
未验证：真实非 UTF-8 系统代码页 / 阅读器交互 / 真实 API（本轮均不测）
```
