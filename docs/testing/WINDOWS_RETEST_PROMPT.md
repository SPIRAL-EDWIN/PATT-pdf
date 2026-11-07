# 给 Windows 上 Codex 的完整复测提示词：PATT-PDF v0.3.3.dev0

> 本文件可整篇复制到一个新对话中直接使用，不依赖其他上下文。
>
> 你的任务是**在这台 Windows 电脑上从零安装、复测并如实报告**，不是开发新功能，也不要修改项目源码。
> - 每一项都要写明 PASS / FAIL / SKIP，并附上证据（命令、退出码、关键输出）。
> - 没有实际运行的项目标为 SKIP 并写明原因，**不得写成 PASS**。
> - 不要把 Linux、macOS 的结果或模拟测试当作 Windows 的结果。
> - 本文件中的命令都是 **PowerShell 7 写法**，不要在 cmd 或 bash 中运行。

## 0. 背景与边界

- **项目：**PATT-PDF。它把 PDF 中的英文替换为简体中文，并尽量放在原位置。所有平台共用一套核心代码，平台差异集中在 `src/patt_pdf/osenv.py`。
- **版本：**v0.3.3.dev0，实验性开发版，不是稳定版。本版只在 Linux 上测试过；**从未在 Windows 上运行过**。
- **上一轮 Windows 实测（v0.3.1，`6b969b8`）发现的问题。**这些在 v0.3.2/v0.3.3 中已有对应修改，但都**未经 Windows 实机验证**：
  - W01：编码探针失败；
  - W02：错误 JSON 和报告中出现了 Windows 绝对路径；
  - W03：缺少 OCR 或文件被锁时出现 `KeyError: 'status'`；
  - W04：字体查找顺序不对，且有重复；
  - W05：未开启 `LongPathsEnabled` 时，长路径失败。
- **禁止：**
  - 调用任何翻译 API（包括 DeepL 的 usage 查询和远程术语表），读取或输出真实密钥；
  - 读取、复制或上传用户的私人文档；
  - 修改注册表、系统区域设置或“Beta: 使用 Unicode UTF-8”选项；
  - 以管理员身份运行；
  - 往 `C:\Windows\Fonts` 写文件；
  - 推送代码，创建 release 或 PyPI 包。
- **允许：**从官方来源下载 Python、依赖、字体和 Tesseract（这属于安装测试，与翻译 API 无关）。安装软件前**先征得用户同意**，优先选择“仅为当前用户”安装。
- **工作范围：**只在新建的测试目录 `$T` 中工作，结束时只删除 `$T`。

## 1. 获取候选源码（commit 和 SHA-256 由用户提供，不要猜）

**拿不到用户给的完整 commit SHA 就停下来询问。**

```powershell
$T = Join-Path $env:USERPROFILE ("PATT 复测 " + (Get-Date -Format "yyyyMMdd-HHmmss")); New-Item -ItemType Directory $T | Out-Null
```

**A. GitHub（仅当用户明确说“已推送，commit 是 …”时使用）：**
```powershell
git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git "$T\PATT-pdf"
git -C "$T\PATT-pdf" checkout <用户给的完整SHA>
git -C "$T\PATT-pdf" rev-parse HEAD          # 必须与用户给的完全一致
git -C "$T\PATT-pdf" status --short          # 必须为空
```

**B. 离线 bundle（尚未推送时使用；由用户通过可信途径提供文件、SHA-256 和完整 commit）：**
```powershell
$B = (Resolve-Path "<bundle 路径>").Path
(Get-FileHash $B -Algorithm SHA256).Hash     # 必须与用户给的 SHA-256 一致
git bundle list-heads $B                     # HEAD 与 refs/heads/main 都必须等于用户给的 commit
git clone $B "$T\PATT-pdf"
git -C "$T\PATT-pdf" rev-parse HEAD
```
任何一项不一致，**立即停止并报告**。

## 2. 记录环境（用户名替换为 `<USER>`）

```powershell
$PSVersionTable.PSVersion; [Environment]::OSVersion.VersionString; (Get-CimInstance Win32_OperatingSystem).Caption
$env:PROCESSOR_ARCHITECTURE; git --version; py -0p
chcp; [Console]::OutputEncoding.WebName
Get-ItemPropertyValue 'HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage' -Name ACP, OEMCP   # 只读查看
Get-ItemPropertyValue 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction SilentlyContinue   # 只读查看
Get-Command tesseract -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
```

- **代码页：**若 ACP 是 `65001`，说明本机使用 UTF-8 系统代码页，**无法验证** cp936/cp1252。E1 中要写明这一点，不要为了测试去修改系统设置。
- **Python：**3.11–3.13 均可，`py -3.12` 优先；没有 Python 时，征得同意后从 python.org 安装“仅当前用户”版本。

## 3. 安装（全新 venv，普通安装）

```powershell
py -3.12 -m venv "$T\venv"; & "$T\venv\Scripts\Activate.ps1"      # 被执行策略阻止时：Set-ExecutionPolicy -Scope Process Bypass
python -m pip install --upgrade pip
pip install "$T\PATT-pdf[ocr,dev]" 2>&1 | Select-Object -Last 3
patt-pdf --version                                                   # 预期：patt-pdf 0.3.3.dev0
python -c "import pymupdf,numpy,fontTools,cv2,platform;print(pymupdf.VersionBind,numpy.__version__,fontTools.version,cv2.__version__,platform.machine())"
```
- **ARM64 Windows：**依赖没有 wheel 而安装失败时，记录 FAIL 和 pip 的报错。不要从源码编译。
- **pip 报“文件名或扩展名太长”：**把这件事记入 W05。只对当前进程设置较短的临时目录后重试，例如 `$env:TEMP="C:\pt"; $env:TMP="C:\pt"`，前提是该目录可写，且只在测试目录范围内使用。

**字体**（Noto Sans/Serif CJK SC，许可证为 SIL OFL 1.1）：

1. 从 https://github.com/notofonts/noto-cjk 下载 `Sans/OTF/SimplifiedChinese/NotoSansCJKsc-{Regular,Bold}.otf` 和 `Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-{Regular,Bold}.otf` 到 `$T\noto`。
2. 用 `git hash-object <文件>` 核对每个文件的 blob SHA：

| 文件 | blob SHA |
|---|---|
| NotoSansCJKsc-Regular | `dc15562470b4f842321894787a0d066879ccff8b` |
| NotoSansCJKsc-Bold | `ff4c0450e8a5bf0290fbb6013a72dc61a10e8e56` |
| NotoSerifCJKsc-Regular | `cba8a4783cc38574ac7cda52cae7d9b4241c07a5` |
| NotoSerifCJKsc-Bold | `f1bd9c86c5765f3358815fb84b19003fd5711747` |

3. 然后运行：
```powershell
$env:PATT_PDF_FONT_SOURCE = "$T\noto"; $env:PATT_PDF_FONT_DIR = "$T\fonts"
patt-pdf fonts; "fonts rc=$LASTEXITCODE"
patt-pdf doctor; "doctor rc=$LASTEXITCODE"           # 记录完整输出（脱敏）
```

**Tesseract**（UB Mannheim 构建，https://github.com/UB-Mannheim/tesseract/wiki ；或 `winget install UB-Mannheim.TesseractOCR`，需征得同意）：
- 只解压到 `$T\tesseract` 也可以；需要有 `eng` 语言包，可以从 https://github.com/tesseract-ocr/tessdata_fast 获取。
- 然后运行：
```powershell
$env:PATT_PDF_TESSERACT = "$T\tesseract\tesseract.exe"     # 装在默认目录或在 PATH 中时可以不设
python "$T\PATT-pdf\tools\ci_check_ocr.py" expect-present; "rc=$LASTEXITCODE"
```
无法获取 Tesseract 时，有 OCR 的那组测试标为 SKIP。

**注意：**`$env:` 变量只在当前 PowerShell 窗口有效。换窗口后要重新激活 venv，并重新设置 `$T` 和上面的变量。

## 4. 测试套件（以实际数字为准）

```powershell
Set-Location "$T\PATT-pdf"
python -m pytest -q -p no:cacheprovider -rs 2>&1 | Tee-Object "$T\pytest-ocr.txt" | Select-Object -Last 25
$keep = $env:PATT_PDF_TESSERACT; $env:PATT_PDF_TESSERACT = "$T\no-tesseract-here"
python tools\ci_check_ocr.py expect-absent; "absent rc=$LASTEXITCODE"            # 必须输出 OK，rc=0
python -m pytest -q -p no:cacheprovider -rs 2>&1 | Tee-Object "$T\pytest-noocr.txt" | Select-Object -Last 25
$env:PATT_PDF_TESSERACT = $keep
```

**按设计会跳过的项目**（用来核对，不是预填结果）：
- Windows 上总会跳过 5 项：
  - POSIX 权限位：`test_key_save_is_private_and_never_printed`、`test_key_file_permissions`；
  - POSIX locale 模拟：`test_pipeline_in_legacy_posix_locales`、`test_pth_decoding_matches_cpython_rules`；
  - POSIX 替换语义：`test_posix_open_reader_does_not_block_replace`。
- 无 OCR 时另外跳过 5 项。
- **应当运行：**`test_native_windows_lock`、`test_pipeline_with_platform_default_encoding`、`test_unicode_filename_roundtrip`、`tests/test_ci_workflow.py`。它们若被跳过，要作为发现报告。

## 5. 专项复测 E1–E8

每项都记录：命令、退出码、关键输出、预期、实际，以及 PASS / FAIL / SKIP。

**E1 编码（W01）：**
```powershell
python -c "import locale,sys,io;print(getattr(locale,'getencoding',locale.getpreferredencoding)(), io.TextIOWrapper(io.BytesIO(),encoding='locale').encoding, sys.getfilesystemencoding(), sys.flags.utf8_mode)"
$env:PYTHONUTF8 = "0"; python -m pytest -q -p no:cacheprovider -rA tests\test_encoding.py 2>&1 | Tee-Object "$T\e1.txt" | Select-Object -Last 15; Remove-Item Env:PYTHONUTF8
```
- 预期：全部 PASS。
- 第一行若为 `cp65001`/`utf-8`，就写明“本机系统代码页为 UTF-8，**未验证** cp936/cp1252”。这一结论只能来自真实的非 UTF-8 机器，不能靠修改设置制造。

**E2 无 OCR 时批处理继续执行（W03）：**
```powershell
$env:PATT_PDF_TESSERACT = "$T\no-tesseract-here"
$IN = "$T\输入 目录"; python tests\fixtures\make_fixtures.py $IN; Move-Item "$IN\truth.json","$IN\manual_tm.json" $T
$S = "$T\state-noocr"; $TM = "$T\manual_tm.json"
patt-pdf plan $IN --state $S; "plan rc=$LASTEXITCODE"                                                   # 预期 1
patt-pdf translate $IN --state $S --backend pseudo --max-chars 99999; "A1 rc=$LASTEXITCODE"             # 预期 2
patt-pdf estimate $IN --state $S --backend manual --manual-tm $TM | Select-Object -Last 1              # 预期 981 字符 / 40 句段
patt-pdf render $IN --state $S --backend pseudo --files toc.pdf; "A2 rc=$LASTEXITCODE"                  # 预期 2
patt-pdf publish $IN --state $S --dest "$T\pub" --files toc.pdf; "A3 rc=$LASTEXITCODE"                 # 预期 2，且 pub 中没有 toc.pdf
patt-pdf translate $IN --state $S --backend manual --manual-tm $TM --max-chars 99999 | Select-String missing_from_backend   # 预期 3
patt-pdf translate $IN --state $S --backend manual --manual-tm $TM --max-chars 5; "B2 rc=$LASTEXITCODE"       # 预期 2
patt-pdf render $IN --state $S --backend manual --manual-tm $TM 2>&1 | Tee-Object "$T\e2-render.txt"; "C1 rc=$LASTEXITCODE"   # 预期 1
(Select-String -Path "$T\e2-render.txt" -Pattern KeyError).Count                                       # 预期 0
```

预期状态：

| 文件 | 预期状态 |
|---|---|
| toc、financial、table、rotated、`报告 2026 – résumé` | `PASS` |
| decorations | `REVIEW` |
| image_text | `UNVERIFIED` |
| scanned、vector_glyphs、decor_scan | `FAIL` |
| two_column_cropbox | `FAIL` |
| damaged、encrypted、truncated | `ERROR` |

**E3 有 OCR**（Tesseract + eng 可用时；否则 SKIP）：
```powershell
$env:PATT_PDF_TESSERACT = $keep
$S2 = "$T\state-ocr"; patt-pdf plan $IN --state $S2; patt-pdf translate $IN --state $S2 --backend manual --manual-tm $TM --max-chars 99999 | Out-Null
patt-pdf render $IN --state $S2 --backend manual --manual-tm $TM; "rc=$LASTEXITCODE"
```
- 预期：三个扫描或转曲样本为 `REVIEW`，estimate 为 1136 字符 / 44 句段。
- 再测“有 OCR 时规划、无 OCR 时渲染”：
  ```powershell
  $env:PATT_PDF_TESSERACT = "$T\no-tesseract-here"; patt-pdf render $IN --state $S2 --backend manual --manual-tm $TM --files "*scan*"; $env:PATT_PDF_TESSERACT = $keep
  ```
  预期为 `UNVERIFIED`，不出现 `KeyError`。

**E4 原生文件锁（W03）。**pytest 中的 `test_native_windows_lock` 已经是一次原生锁测试，结果写入报告。另外再手动做一次：
```powershell
patt-pdf render $IN --state $S --backend manual --manual-tm $TM --files table.pdf | Out-Null
$f = "$S\out\table.pdf"; $before = (Get-FileHash $f).Hash
$h = [System.IO.File]::Open($f, 'Open', 'Read', 'Read')            # 不允许 Delete/Write 共享
patt-pdf render $IN --state $S --backend manual --manual-tm $TM --files table.pdf 2>&1 | Tee-Object "$T\e4.txt"; "rc=$LASTEXITCODE"
$h.Close()
(Get-FileHash $f).Hash -eq $before; Get-ChildItem "$S\out" -Force -Filter ".tmp-*"
```
- 预期：rc=1；输出含 `in use` 和 `close the output PDF`；没有 `KeyError`；文件哈希不变；没有 `.tmp-*` 文件残留。
- 可选：用 Edge 或 Acrobat 打开该 PDF 后重新渲染，记录实际行为；没有实际操作就标 SKIP。

**E5 路径脱敏（W02）：**
```powershell
patt-pdf report $IN --state $S --out "$T\report.md"
Select-String -Path "$T\report.md","$S\plans\*.error.json","$S\qa\*.json","$S\runs.jsonl" -Pattern ([regex]::Escape($env:USERNAME)),'C:\\\\','C:\\Users' | Select-Object -First 5   # 预期没有输出
Select-String -Path "$T\report.md" -Pattern "Failed to open file '[^']*'" | Select-Object -First 2                                     # 预期为 <input>/truncated.pdf
```

**E6 字体优先级（W04）：**
1. 在 `$T\fontprio\env` 和用户字体目录 `$env:LOCALAPPDATA\Microsoft\Windows\Fonts` 中放入**同名**的静态字体。往用户字体目录放文件前**先征得同意**，结束后删除；不同意时只用 `$T` 下的两个目录，并以 `PATT_PDF_FONT_SOURCE="dirA;dirB"` 验证先后顺序。
2. 运行：
```powershell
python -c "from patt_pdf.fonts import search_dirs, find_system_source; d=search_dirs(); print(d); print(len(d)==len({str(x).lower() for x in d})); print(find_system_source(('sans', False)))"
```
- 预期：顺序为环境变量目录 → 用户目录 → `C:\Windows\Fonts`，没有重复，也没有 `/usr/...`、`/Library/...` 这类路径；命中的是排在最前面的目录。
- **不要往 `C:\Windows\Fonts` 写文件。**

**E7 长路径（W05）。**不要修改注册表：
```powershell
$deep = "$T\" + (("d" * 40 + "\") * 7); $p = Join-Path $deep "f.pdf"; $p.Length
New-Item -ItemType Directory -Path ("\\?\" + $deep) -Force | Out-Null
Copy-Item "$IN\toc.pdf" ("\\?\" + $p)
patt-pdf plan $deep --state "$T\lp-state"; "plain rc=$LASTEXITCODE"                  # LongPathsEnabled=0 时预期 rc=1，提示中应含 LongPathsEnabled
patt-pdf plan ("\\?\" + $deep) --state "$T\lp-state2"; "extended rc=$LASTEXITCODE"   # 记录实际结果，不预设
patt-pdf doctor | Select-String -Pattern "long|LongPaths"
```

**E8 OCR 发现顺序与显式路径：**
```powershell
$env:PATT_PDF_TESSERACT = "$T\missing\tesseract.exe"; python tools\ci_check_ocr.py expect-absent    # 预期 OK：显式路径不存在时，不会改用其他安装
$env:PATT_PDF_TESSERACT = $keep; python tools\ci_check_ocr.py expect-present                         # 预期 OK
```

## 6. 保存证据与清理

- **证据：**把 `$T\*.txt`、`$T\report.md` 和截图复制到**用户指定的私有位置**（不要放进仓库，也不要上传）。
- **脱敏：**用户名替换为 `<USER>`，机器名替换为 `<HOST>`。
- **清理：**用户确认后执行下面的命令。如果在用户字体目录放过测试字体，也一并删除。不要卸载 Python、Tesseract 或字体。
  ```powershell
  deactivate; Set-Location $env:USERPROFILE; Remove-Item -LiteralPath $T -Recurse -Force
  ```
  长路径目录可能需要先执行 `Remove-Item -LiteralPath ("\\?\" + $T) -Recurse -Force`。

## 7. 反馈模板（发给用户，由用户转交 Claude）

```
候选 commit：<完整 SHA>    来源：A GitHub / B bundle（SHA-256 <…>）
Windows <版本/版本号>  Arch <x64|ARM64>  PowerShell <…>  ACP/OEMCP <…>  chcp <…>  LongPathsEnabled <0|1|未设>
Python <x.y.z>  pip <…>  setuptools <…>  PyMuPDF <…> numpy <…> fontTools <…> opencv <…> pytest <…> PyYAML <…>
字体来源与 blob 校验：<…>   Tesseract：<版本 + eng / 无；来源与位置（脱敏）>
doctor 输出（脱敏）：<…>

pytest 有OCR：n passed / n failed / n skipped（逐条列出跳过原因）
pytest 无OCR：…
E1 编码 ................ PASS/FAIL；默认编码=<…>；cp936/cp1252：未验证/已验证（何种机器）
E2 无OCR批处理 ......... PASS/FAIL  C1 rc=<…>  KeyError 次数=<…>  状态表偏差：<…>
E3 有OCR ............... PASS/FAIL/SKIP
E4 原生文件锁 .......... PASS/FAIL（rc、提示、哈希、.tmp 残留）；查看器实测：PASS/FAIL/SKIP
E5 路径脱敏 ............ PASS/FAIL
E6 字体优先级 .......... PASS/FAIL（search_dirs 输出与命中的文件）
E7 长路径 .............. 普通路径 rc=<…>（提示：…）；扩展前缀 rc=<…>
E8 OCR 显式路径 ........ PASS/FAIL

每个 FAIL：最小复现命令 / 预期 / 实际 / 日志位置（私有）
未验证项：cp936/cp1252 系统、阅读器交互、真实 PDF、真实翻译 API、<其他>
```
