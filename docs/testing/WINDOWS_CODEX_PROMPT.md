# 给 Windows 电脑上 Codex 的完整提示词：PATT-PDF Windows 验证（v0.3.2 版，已由 WINDOWS_RETEST_PROMPT.md 取代）

> **请优先使用 `docs/testing/WINDOWS_RETEST_PROMPT.md`（v0.3.3）。**本文件保留作 v0.3.2 时的完整清单参考，其中的版本号和测试数量已经过时。

> 用法：把本文件全文复制给 Windows 上的 Codex。
>
> 你的任务是**验证与报告**，不是开发新功能。只报告实际运行过的结果。没运行的项目标 SKIP 并写明原因，不得写成 PASS。

## 1. 项目、版本与取源

**项目：**PATT-PDF（Position-Aware Translation Toolkit for PDF）是一个实验性工具。它把 PDF 中的英文替换为简体中文，并尽量放在原位置。数字、金额、页码、表格和图形保留原字形，下划线和链接区域随译文移动，最后由 QA 检查结果。

**当前状态：**v0.3.2.dev0，experimental，跨平台测试候选。上一轮 Windows 实测针对 v0.3.1.dev0，发现的问题（W01–W05）已在本版处理，详见 `docs/STATUS.md` 第 0 节；本版尚未在 Windows 上运行。
- 测试套件共 124 项。只在 Linux aarch64（Python 3.10、PyMuPDF 1.28.2 与 1.25.2、Tesseract 4.1.1）上运行过，结果见 `docs/STATUS.md` 第 3 节。这些是 Linux 结果，**不代表 Windows 会得到同样的数字**。
- 上一个候选的独立审查发现：测试代码按系统默认编码读取 UTF-8 文件，在 cp936/cp1252 的 Windows 上会让 `¥9,870` 等字符乱码而误报失败。本版已修复，并新增 `tests/test_encoding.py`；在 Linux 上用 GBK 与 CP1252 区域设置模拟过，**未在真实 Windows 上运行**。
- **从未在 Windows 上运行过**，也没有进行过真实的 DeepL 调用。
- 未经测试的 Windows 专属代码路径：
  - 字体目录：`%LOCALAPPDATA%\Microsoft\Windows\Fonts`、`C:\Windows\Fonts`；
  - 密钥位置：`%APPDATA%\patt-pdf\deepl.key`；
  - Tesseract 默认路径；
  - 文件被占用时的处理；
  - 控制台代码页。

**取源（先问用户用哪一种，并记录）：**

- **A. 发布快照 bundle（尚未推送时的默认方式）。**用户通过可信途径（U 盘、私人网盘）给你三样东西：
  - 文件 `patt-pdf-<版本>-<短SHA>.bundle`；
  - 该文件的 SHA-256；
  - 完整的 commit SHA。

  先执行第 2 节的第一段命令（创建测试目录 `$T`），再执行：
  ```powershell
  $BUNDLE = (Resolve-Path .\patt-pdf-*.bundle).Path
  (Get-FileHash $BUNDLE -Algorithm SHA256).Hash                  # 必须与用户给的 SHA-256 一致
  git bundle list-heads $BUNDLE                                  # HEAD 与 refs/heads/main 都等于用户给的 commit
  git clone $BUNDLE "$T\PATT-pdf"                                # $T 见第 2 节，先建目录
  git -C "$T\PATT-pdf" rev-parse HEAD                            # 必须等于用户给的 commit
  git -C "$T\PATT-pdf" bundle verify $BUNDLE                     # 显示 "The bundle records a complete history."
  git -C "$T\PATT-pdf" log --oneline | Measure-Object -Line      # 发布快照只有 1 个提交
  ```
  任一项不一致，**立即停止并报告**，不要改测别的东西。
- **B. GitHub（仅当用户明确告诉你“已推送，commit 是 <完整SHA>”时）：**
  ```powershell
  git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git "$T\PATT-pdf"
  git -C "$T\PATT-pdf" checkout <用户给的完整SHA>
  git -C "$T\PATT-pdf" rev-parse HEAD
  ```
  如果仓库为空、SHA 不存在或与用户给的不一致，**立即停止并报告**。不要改用其他 commit，也不要自己编造 commit。

**全程禁止：**
- 调用 DeepL 或任何翻译 API；
- 打开、复制或上传用户的私人文档（课程资料、译文、旧原型、密钥）；
- 修改或删除测试目录之外的任何文件；
- 需要管理员权限的操作（除非用户明确同意）；
- 推送代码或创建 release。

## 2. 隔离目录与基础环境

使用 PowerShell，不需要管理员权限。测试目录路径**故意**包含中文和空格：
```powershell
$T = Join-Path $env:USERPROFILE ("PATT 测试 " + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $T | Out-Null; Set-Location $T
$PSVersionTable.PSVersion; [System.Environment]::OSVersion.VersionString
$env:PROCESSOR_ARCHITECTURE; (Get-CimInstance Win32_OperatingSystem).Caption
git --version; py -0p 2>$null; python --version; [Console]::OutputEncoding.WebName; chcp
```

**Python 版本：**3.10–3.13 均可。若没有合适版本：
- 从 https://www.python.org/downloads/windows/ 安装“仅当前用户”版本（不需要管理员），或运行 `winget install Python.Python.3.12 --scope user`；
- **安装前先征得用户同意。**

**ARM64 Windows：**若 PyMuPDF 或 OpenCV 没有对应的 wheel，记录 FAIL 和 pip 的报错，不要从源码编译。

**执行策略：**若激活 venv 时被执行策略阻止，只对当前进程放行：`Set-ExecutionPolicy -Scope Process Bypass`。

```powershell
py -3.12 -m venv "$T\venv"      # 或 python -m venv "$T\venv"
& "$T\venv\Scripts\Activate.ps1"
python -m pip install --upgrade pip
Set-Location "$T\PATT-pdf"
pip install ".[ocr,dev]" 2>&1 | Select-Object -Last 3     # 普通安装；可编辑安装见 README
patt-pdf --version              # 预期：patt-pdf 0.3.2.dev0
python -c "import pymupdf, numpy, fontTools, cv2; print(pymupdf.VersionBind, numpy.__version__, fontTools.version, cv2.__version__)"
```

**网络受限：**如需代理，只通过当前会话的环境变量设置（`$env:HTTPS_PROXY`），并在报告中注明。

## 3. Tesseract OCR（可选）

**可信来源：**UB Mannheim 构建 https://github.com/UB-Mannheim/tesseract/wiki ，或 `winget install UB-Mannheim.TesseractOCR`。安装需用户同意，可选“仅当前用户”。

**检查：**
```powershell
Get-Command tesseract -ErrorAction SilentlyContinue
Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe"
tesseract --version; tesseract --list-langs     # 必须包含 eng
```

**查找顺序：**`$env:PATT_PDF_TESSERACT` → PATH 中的 `tesseract` → `%ProgramFiles%\Tesseract-OCR\tesseract.exe` → `%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe`。都不在时，设置 `$env:PATT_PDF_TESSERACT = "D:\...\tesseract.exe"`。

**有 OCR 和无 OCR 两种情况都要测**，并在报告中分开列出。没有 OCR 时：
- OCR 测试会 SKIP；
- `scanned.pdf`、`vector_glyphs.pdf`、`decor_scan.pdf` 为 `FAIL`（`page_not_processed`）；
- 程序不应崩溃。

## 4. 字体

**来源与许可：**需要 Noto Sans CJK SC 与 Noto Serif CJK SC 的 Regular 和 Bold（SIL OFL 1.1，© Adobe），来源 https://github.com/notofonts/noto-cjk/releases 。Windows 自带的微软雅黑、宋体不会被使用。

**查找顺序：**
1. `$env:PATT_PDF_FONT_SOURCE`（多个目录用 `;` 分隔）；
2. `%LOCALAPPDATA%\Microsoft\Windows\Fonts`；
3. `C:\Windows\Fonts`。

可接受 `NotoSansCJK-Regular.ttc`、`NotoSansCJKsc-Regular.otf`、`NotoSansSC-Regular.otf` 等文件名（Serif 和 Bold 同理）。可变字体（文件名带 `VF`）会被拒绝，这是预期行为。

**安装（需用户同意）：**在 releases 页面分别找到 Sans 和 Serif 的最新发布，下载只含简体中文（SC）的**静态 OTF** 压缩包（资源文件名以页面为准，不要选带 `VF` 的）。解压到 `$T\noto`，然后：
```powershell
$env:PATT_PDF_FONT_SOURCE = "$T\noto"
$env:PATT_PDF_FONT_DIR = "$T\fonts"
patt-pdf fonts; "rc=$LASTEXITCODE"
```
**预期：**4 行 “extracted from …”，rc=0。找不到字体时 rc=1，错误信息会列出搜索过的目录，请复制到报告中。

**重要：**`$env:` 变量只在当前 PowerShell 窗口有效。换窗口后要：
- 重新激活 venv；
- 重新设置 `$env:PATT_PDF_FONT_DIR`，以及 `$T`、`$S`、`$TM`、`$IN`。

否则 `render` 会报 `FontsMissing`（rc=1）。这是环境问题，报告前先排除。

## 5. 离线测试套件

```powershell
Set-Location "$T\PATT-pdf"
$env:PATT_PDF_FONT_DIR = "$T\fonts"
python -m pytest -q -p no:cacheprovider -rs 2>&1 | Tee-Object "$T\pytest.txt" | Select-Object -Last 15
```

**以实际输出为准。**下面只说明哪些测试**按设计**会在 Windows 上跳过，用来判断跳过是否合理；它不是预先写好的结果，请照实填写 passed/failed/skipped 数量。

共 161 项。按测试代码中的跳过条件，在 Windows 上：
- **总会 SKIP 的 5 项**（检查的是 POSIX 专有行为，Windows 由别的项目覆盖）：
  - `test_key_save_is_private_and_never_printed`、`test_key_file_permissions`：POSIX 权限位，由第 7 节 F 项手动检查 ACL 替代；
  - `test_pipeline_in_legacy_posix_locales`、`test_pth_with_non_ascii_path_is_decoded_with_locale_encoding`：POSIX 区域设置模拟；Windows 改由 `test_pipeline_with_platform_default_encoding` 在真实的系统代码页下运行；
  - `test_posix_open_reader_does_not_block_replace`：POSIX 的替换语义；Windows 改由 `test_native_windows_lock` 实测。
- **没有 Tesseract 时再多 5 项 SKIP**，原因写明 tesseract/opencv 或 OCR。
- 因此，字体、Tesseract 都齐备且没有失败时，应是 156 passed、5 skipped；没有 Tesseract 时是 151 passed、10 skipped。这是根据代码推算的数字，不是 Windows 实测结果。**若出现其他跳过原因或任何失败，都要逐条报告。**
- `test_unicode_filename_roundtrip` 和 `test_legacy_console_encoding_does_not_abort` 只在 POSIX 非 UTF-8 文件系统编码下跳过，在 Windows 上**应当运行**；若跳过请报告。

**编码专项（本版重点）：**
```powershell
python -c "import locale,sys; print(locale.getpreferredencoding(False), sys.flags.utf8_mode, sys.getfilesystemencoding())"
$env:PYTHONUTF8 = "0"; python -m pytest -q -p no:cacheprovider -rA tests\test_encoding.py 2>&1 | Tee-Object "$T\pytest-encoding.txt" | Select-Object -Last 8
Remove-Item Env:PYTHONUTF8
```
记录第一行输出（例如 `cp936 0 utf-8`）。若默认编码本身就是 UTF-8（Windows 的“Beta：使用 Unicode UTF-8 提供全球语言支持”已开启），说明本机**测不到**这个问题，请在报告中注明，不要写成已验证。

**控制台编码：**`test_legacy_console_encoding_does_not_abort` 模拟了 cp1252 控制台。实际运行中，若管道输出含中文文件名时出现 `UnicodeEncodeError`，算 FAIL；若文件名显示为 `\u62a5` 之类的转义，可以接受。两种情况都要记录 `chcp` 的结果。

**每个失败都是发现：**保留完整的 `pytest.txt`，并逐条记录失败的测试名和断言信息。

## 6. 路径、编码与重复执行

本节与第 7 节共用 `$IN`、`$S`、`$TM` 三个变量：
```powershell
$IN = "$T\输入 目录"
python tests\fixtures\make_fixtures.py $IN
Move-Item "$IN\truth.json","$IN\manual_tm.json" $T
$S = "$T\state"; $TM = "$T\manual_tm.json"
patt-pdf plan $IN --state $S; "plan rc=$LASTEXITCODE"           # 预期 1：damaged/encrypted 为 error（truncated 见第 7 节表格），其余已规划
patt-pdf plan $IN --state $S | Select-String cached            # 第二次运行：可读文件均为 cached（Linux 上为 11 或 12 个，取决于 truncated）
```

**另外检查：**
- **非 ASCII 文件名：**`报告 2026 – résumé.pdf` 应能正常规划、渲染和发布。
- **状态目录隔离：**`patt-pdf plan $IN --state "$IN\state"` 应报错（状态目录不能放在输入目录内），rc=1。
- **跨盘符：**若有 D: 等其他盘，把 `--state` 放在另一盘上重跑 plan；没有则 SKIP。
- **长路径：**在总长度超过 260 字符的目录中放一个 fixture 并运行 plan。若失败，记录错误信息，以及 `LongPathsEnabled` 是否开启。**不要修改注册表。**
- **报告不泄露路径：**`$S\plans\*.error.json` 和第 7 节生成的报告中只应出现 `<input>/…`，不应出现 `C:\Users\…`。

## 7. 离线端到端检查（零 API）

下面的预期值来自 2026-11-07 在 Linux 上用等价 bash 命令的预演（路径含中文和空格，有 Tesseract），**不是 Windows 上的结果**。任何偏差都是需要报告的发现。

逐条执行，记录每条命令的 rc 和输出：
```powershell
patt-pdf translate $IN --state $S --backend pseudo --max-chars 99999; "A1 rc=$LASTEXITCODE"                 # 预期 2：可读文件已完成，但跳过了 3 个不可读文件
patt-pdf estimate  $IN --state $S --backend manual --manual-tm $TM | Select-Object -Last 1                 # 预期 1136 字符/44 句段（无 OCR 时 981/40）：伪译文未被复用
patt-pdf render    $IN --state $S --backend pseudo --files toc.pdf; "A2 rc=$LASTEXITCODE"                  # 预期 2，FAIL
patt-pdf publish   $IN --state $S --dest "$T\pub" --files toc.pdf; "A3 rc=$LASTEXITCODE"                  # 预期 2，跳过；pub 中没有 toc.pdf
patt-pdf translate $IN --state $S --backend manual --manual-tm $TM --max-chars 99999; "B1 rc=$LASTEXITCODE"  # 预期 2（TM 缺 3 个句段，"missing_from_backend": 3）
patt-pdf translate $IN --state $S --backend manual --manual-tm $TM --max-chars 5; "B2 rc=$LASTEXITCODE"      # 预期 2："estimate 290 chars exceeds --max-chars 5"
patt-pdf render    $IN --state $S --backend manual --manual-tm $TM; "C1 rc=$LASTEXITCODE"                  # 预期 1（存在 error 文件）
patt-pdf report    $IN --state $S --out "$T\report.md"
patt-pdf compare   $IN --state $S --out "$T\cmp" --files "t*"
patt-pdf compare   $IN --state $S --out "$T\cmp" --files "decorations.pdf"
```

**预期状态**（见 `$T\report.md`）：

| 文件 | 预期状态 |
|---|---|
| `toc`、`financial`、`table`、`rotated`、`报告 2026 – résumé` | `pass` |
| `decorations` | `needs review`：第 1 页 pass；第 2 页 review（`decoration_not_adjusted`、`link_area_not_mapped`、`markup_annotation_on_translated_text`） |
| `image_text` | `UNVERIFIED` |
| `scanned`、`vector_glyphs`、`decor_scan` | 有 OCR 时 `needs review`，无 OCR 时 `FAIL` |
| `two_column_cropbox` | `FAIL`（故意留的 TM 缺口） |
| `damaged`、`encrypted` | `ERROR`，消息里只有 `<input>/…` |
| `truncated` | 与 PyMuPDF 版本有关：无法打开时为 `ERROR`；被 MuPDF 自动修复时为 `UNVERIFIED`（`source_repaired`）。**绝不应为 pass** |

**D. 过期规划：**用另一份 PDF 替换 `toc.pdf` 后再渲染。预期 rc=1，并提示 “source file content changed”：
```powershell
python -c "import pymupdf,os,sys; d=pymupdf.open(); d.new_page().insert_text((72,72),'Other'); d.save(sys.argv[1]); os.replace(sys.argv[1], sys.argv[2])" "$T\x.pdf" "$IN\toc.pdf"
patt-pdf render $IN --state $S --backend manual --manual-tm $TM --files toc.pdf; "D rc=$LASTEXITCODE"
```

**E. 文件占用（Windows 重点）：**
1. 先渲染一次 `table.pdf`（rc 0）；
2. 在 Edge 或 Acrobat 中打开 `$S\out\table.pdf`，保持打开；
3. 再渲染一次：
   ```powershell
   patt-pdf render $IN --state $S --backend manual --manual-tm $TM --files table.pdf; "E1 rc=$LASTEXITCODE"
   Get-ChildItem $S\out -Filter ".tmp-*"
   ```

预期：二者之一。
- 成功覆盖（部分查看器允许）；
- 或报出清楚的 “file is in use … close it” 错误，rc=1。

无论哪种，原 `out\table.pdf` 都必须仍能打开且未损坏，`$S\out` 中不能残留 `.tmp-*` 文件。

然后检查发布到已有同名文件的位置时不会覆盖：
```powershell
New-Item -ItemType Directory "$T\pub2" | Out-Null; Set-Content "$T\pub2\table.pdf" "old"
patt-pdf publish $IN --state $S --dest "$T\pub2" --files table.pdf; "E2 rc=$LASTEXITCODE"   # 预期 rc=2，显示 skipped … exists (not overwritten)
Get-Content "$T\pub2\table.pdf"                                                              # 仍为 old
```
本项只操作测试目录中的文件。

**F. 密钥文件（只用假密钥）：**
```powershell
"11111111-2222-3333-4444-555555555555:fx" | patt-pdf key save --path "$T\k\deepl.key"; "F rc=$LASTEXITCODE"
icacls "$T\k\deepl.key"
"11111111-2222-3333-4444-555555555555:fx" | patt-pdf key save --path "$T\k\deepl.key"; "F2 rc=$LASTEXITCODE"   # 预期 1：不覆盖已有文件
```
预期：
- 第一次 rc=0，输出中不出现这个假密钥；
- 第二次 rc=1（不覆盖已有文件）。

记录 `icacls` 的结果。Windows 上这个文件继承父目录的 NTFS 权限，请明确报告除当前用户、SYSTEM 和 Administrators 之外是否还有其他人能读取。

**G. 中断与续跑（需要 OCR；没有 Tesseract 就 SKIP）：**
```powershell
New-Item -ItemType Directory "$T\big" | Out-Null
python -c "import pymupdf,sys; d=pymupdf.open(); s=pymupdf.open(sys.argv[1]); [d.insert_pdf(s) for _ in range(20)]; d.save(sys.argv[2])" "$IN\scanned.pdf" "$T\big\scan20.pdf"
patt-pdf plan "$T\big" --state "$T\sbig" --time-budget 3; "G1 rc=$LASTEXITCODE"   # 预期 partial，“stopped by --time-budget after N of 20 pages”，rc=2
patt-pdf plan "$T\big" --state "$T\sbig"; "G2 rc=$LASTEXITCODE"                     # 预期 planned 20 pages，“reused N pages”，rc=0
```
两次的 N 应该相同且大于 0。Linux 上 N=3。

**H. 视觉检查：**
- 打开 `$T\cmp\toc_p1.png` 和 `$T\cmp\table_p1.png`：左右两侧的数字 1、2、3、5，以及金额、负数括号、百分比和日期应完全一致，英文应变成中文。
- 打开 `$T\cmp\decorations_p1.png`：右侧每条下划线和删除线应在中文末尾结束；`info@example.org` 下的线应跟着地址移动；小表格和长灰线不变。

截图保存到 `$T\screens\`。

**I. 链接：**
```powershell
python -c "import pymupdf,sys; o=pymupdf.open(sys.argv[1]); print([sorted(l['uri'] for l in p.get_links()) for p in o])" "$S\out\decorations.pdf"
```
预期输出：`[['https://example.org/field-guide', 'mailto:info@example.org'], ['https://example.org/map']]`。

在 PDF 阅读器中点击第 1 页两个链接，可点击区域应落在中文文字上。

## 8. DeepL（默认关闭）

本轮**不调用 DeepL**。若用户以后单独授权少量字符的测试：
- **密钥：**只能用 `Get-Clipboard | patt-pdf key save` 或用户自己设置的环境变量提供，不得出现在命令行参数、截图、报告、日志或仓库中。
- **事先说明：**写明样本、预估字符数和 `--max-chars`。`--max-chars` 也限制重试，重试会计入 `sent_chars`。
- **术语表：**`--glossary` 会在你的 DeepL 账户中创建术语表（远程写入），只有在预算检查通过后才会创建。
- **报告：**记录 `patt-pdf usage` 在调用前后的数值，与 `runs.jsonl` 中的 `sent_chars`、`possibly_billed_chars`、`billed_delta` 对比后报告。

## 9. 清理（只删测试目录）

```powershell
deactivate 2>$null
Set-Location $env:USERPROFILE
Write-Host "将删除：$T"; Get-ChildItem $T | Select-Object Name
Remove-Item -LiteralPath $T -Recurse -Force      # 只删除本次测试目录
```

**不要：**
- 卸载 Python、Tesseract 或字体；
- 删除其他目录；
- 清理全局 pip 缓存。

如果文件仍被查看器锁定导致删除失败，关闭查看器后重试，并在报告中说明。

## 10. 反馈模板（请严格按此填写）

```
Windows: <版本/版本号>  Arch: <x64|ARM64>  PowerShell: <x>  chcp: <代码页>
Python: <x>  Git: <x>  Tesseract: <x 或 未安装>  eng 语言包: <有/无>
PyMuPDF <x>  numpy <x>  fontTools <x>  opencv <x>
测试来源: A bundle（SHA-256 <…>）/ B GitHub   commit: <完整SHA>   提交数: <n>

2 安装 ................ PASS/FAIL/SKIP
3 OCR 检测 ............ PASS/FAIL/SKIP（路径：…）
4 字体 ................ PASS/FAIL（来源目录：…）
5 pytest .............. <n passed / n failed / n skipped>（失败测试名列表）
6 中文/空格路径 ....... PASS/FAIL
6 状态目录隔离 ........ PASS/FAIL
6 跨盘符 .............. PASS/FAIL/SKIP
6 长路径 .............. PASS/FAIL/SKIP（LongPathsEnabled：是/否/未知）
6 报告不含本机路径 .... PASS/FAIL
7 A 伪译文隔离 ........ PASS/FAIL
7 B 预算与部分完成 .... PASS/FAIL
7 C 状态与退出码 ...... PASS/FAIL（与预期表的偏差）
7 D 过期规划 .......... PASS/FAIL
7 E 文件占用 .......... PASS/FAIL（实际行为描述）
7 F 密钥文件 .......... PASS/FAIL（icacls 摘要）
7 G 中断续跑 .......... PASS/FAIL/SKIP
7 H 视觉对比 .......... PASS/FAIL（截图路径）
7 I 链接 .............. PASS/FAIL

每个 FAIL：复现命令 / 预期 / 实际 / 日志路径（已脱敏）
遗留风险：…
```

**脱敏要求：**日志中只允许出现测试目录内的合成文件。输出中出现的用户名替换为 `<USER>`。任何真实密钥都不得出现在报告中。
