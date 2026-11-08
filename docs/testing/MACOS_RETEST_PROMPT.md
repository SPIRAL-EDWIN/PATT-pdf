# 给 macOS 上 Codex 的完整复测提示词：PATT-PDF v0.3.5.dev0

> 本文件可整篇复制到一个新对话中直接使用，不依赖其他上下文。
>
> 你的任务是**在这台 Mac 上从零安装、复测并如实报告**，不是开发新功能，也不要修改项目源码。
> - 每一项都要写明 PASS / FAIL / SKIP，并附上证据（命令、真实退出码、关键输出）。
> - 没有实际运行的项目标为 SKIP 并写明原因，**不得写成 PASS**。
> - 不要把 Linux、Windows 的结果或模拟测试当作 macOS 的结果。
> - 本次复测通过，也不代表“跨平台阶段完成”；这个结论由用户在汇总三平台证据后决定。

## 0. 背景与边界

- **项目：**PATT-PDF。它把 PDF 中的英文替换为简体中文，并尽量放在原位置；有 QA 状态和退出码。所有平台共用一套核心代码，平台差异集中在 `src/patt_pdf/osenv.py`。
- **版本：**v0.3.5.dev0，实验性开发版，不是稳定版。本版只在 Linux aarch64 上测试过，用过真实的 CPython 3.10.12，以及 python-build-standalone 的 CPython 3.11.18、3.12.16（普通安装和可编辑安装都测过，结果见 `docs/STATUS.md`）。**本版从未在 macOS 上运行过。**
- **三类证据，报告中必须分开写，不能互相替代：**
  1. **GitHub 云端 CI**：在 GitHub 提供的 macOS 云端机器上运行，不是用户的 Mac。上一版 v0.3.4（`ca38a93`，run 42396678823）在 macos-15（arm64，3.11 和 3.12）和 macos-15-intel（x64，3.11）上的 4 个任务**全部通过**；v0.3.5 **尚未在 CI 运行**。
  2. **本次在用户 Mac 上的实测**：只有你亲手运行、有日志的项目才算。CI 通过不能代替它：CI 机器的 Python 构建、区域设置、字体来源（Homebrew cask）都可能与用户的 Mac 不同。
  3. **模拟和跳过**：pytest 中的模拟测试（例如在 macOS 上模拟 Windows 路径或控制台编码）以及 SKIP 项，都不等于实测。
- **v0.3.5 相对 v0.3.4 的改动**（来自 Windows CI，macOS 上应无行为变化，但需要回归确认）：
  - 控制台输出在非 UTF-8 编码下一律转义无法编码的字符；之前只处理 `strict`，没有处理 `surrogateescape`；
  - 模拟其他系统的字体目录时，按目标系统的路径规则生成。
- **历次在 macOS 上发现的问题（需要你复测）：**
  - v0.3.1：缺少 OCR 时出现 `KeyError`；编码探针失败；Python 3.11 + ISO8859-1 + 中文路径的可编辑安装无法导入。
  - v0.3.2：两个测试失败，原因是测试本身的假设错误。
  - v0.3.3：`.pth` 解码测试在 Python 3.12.14 上失败（GBK 环境下 found，测试却预测 error），在 3.11.16 上也失败（`PYTHONUTF8=1` 时仍然 `UnicodeDecodeError`）。
    - **已确认的根因：**测试按版本号推断 `.pth` 的解码方式，这个前提是错的。
      - CPython **3.12.4 起**（从 3.13 回移）先按 UTF-8 读取 `.pth`。
      - 在 **3.11** 上，`encoding="locale"` 不受 UTF-8 Mode 影响。
    - v0.3.4 改为读取解释器**实际运行的** `site.addpackage` 代码（3.11 起的发行版构建中 `site` 是冻结模块，`inspect.getsource()` 会失败，所以读的是代码对象里的常量），再结合子进程实际报告的编码来预测结果，详见 `docs/STATUS.md` §0。**尚未在 macOS 上验证。**
- **禁止：**
  - 调用任何翻译 API（包括 DeepL 的 usage 查询和远程术语表），读取或输出真实密钥；
  - 读取、复制或上传用户的私人文档（课程资料、译文、翻译记忆、日志）；
  - 用 `sudo`、修改系统 locale 或系统设置；
  - 往系统字体目录写文件；
  - 推送代码，创建 release 或 PyPI 包。
- **允许：**从官方来源下载 Python 依赖、字体和 Tesseract（这属于安装测试，与翻译 API 无关）。安装 Homebrew 软件包前**先征得用户同意**。
- **工作范围：**只在新建的测试目录 `$T` 中工作，结束时只删除 `$T`。

## 1. Shell 与退出码规则（必须遵守）

- macOS 默认 shell 是 zsh。本文所有命令都按 **bash** 写，请**在一个 bash 会话中执行**：先运行 `bash`，确认 `echo $BASH_VERSION` 有输出后再继续。
- **每个检查都用下面的 `run` 函数执行。**它把完整输出写入 `$T/logs/<名称>.txt`，再打印真实退出码和输出尾部。**不要用 `| tee`、`| tail` 直接接在被测命令后面**，那样拿到的是管道最后一条命令的退出码，会掩盖失败。

```bash
bash                                   # 进入 bash（已在 bash 中可跳过）
export T="$HOME/patt-macos-retest-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$T/logs"
run() {  # 用法：run <名称> <命令...>
  local name="$1"; shift
  "$@" > "$T/logs/$name.txt" 2>&1; local rc=$?
  echo "[$name] exit=$rc   (log: \$T/logs/$name.txt)"; tail -n 25 "$T/logs/$name.txt"
  echo "$name $rc" >> "$T/logs/_exitcodes.txt"; return 0
}
```

## 2. 获取候选源码（commit 和 SHA-256 由用户提供，不要猜）

用户会给你以下两种来源之一。**拿不到用户给的完整 commit SHA 就停下来询问，不要用其他 commit 代替。**

**A. GitHub（仅当用户明确说“已推送，commit 是 …”时使用）：**
```bash
git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git "$T/PATT-pdf"
git -C "$T/PATT-pdf" checkout <用户给的完整SHA>
git -C "$T/PATT-pdf" rev-parse HEAD          # 必须与用户给的完全一致
git -C "$T/PATT-pdf" status --short          # 必须为空
```

**B. 离线 bundle（尚未推送时使用；用户通过 U 盘、私人网盘等可信途径提供文件、SHA-256 和完整 commit）：**
```bash
B=/path/to/patt-pdf-0.3.5.dev0-<短SHA>.bundle
shasum -a 256 "$B"                           # 必须与用户给的 SHA-256 一致
git bundle list-heads "$B"                   # HEAD 与 refs/heads/main 都必须等于用户给的 commit
git clone "$B" "$T/PATT-pdf"
git -C "$T/PATT-pdf" rev-parse HEAD
git -C "$T/PATT-pdf" log --oneline | head -5 # 公开历史，以 6b969b8 起始
```
任何一项不一致，**立即停止并报告**。

## 3. 记录环境（全部写入报告，用户名替换为 `<USER>`）

```bash
sw_vers; uname -m; sysctl -n machdep.cpu.brand_string; git --version; echo "login shell: $SHELL"
for p in python3.11 python3.12 python3.13 python3; do command -v "$p" >/dev/null && echo "$p -> $(command -v $p): $("$p" -c 'import sys,platform;print(sys.version.split()[0], platform.machine())')"; done
locale; locale -a | grep -i -E "ISO8859-1|GBK|GB18030|eucCN|UTF-8" | head -20
command -v tesseract && tesseract --version 2>&1 | head -1 && tesseract --list-langs 2>&1 | head -5
```

- **Python 版本：**3.11 和 3.12 都有的话，§4–§6 用两个版本**分别**完整跑一遍（第一遍设 `PY=python3.11 V=311`，第二遍设 `PY=python3.12 V=312`）。缺少某个版本就把它标为 SKIP，并注明“未安装”；只有在用户同意后才安装（`brew install python@3.11` 等）。
- **旧 locale：**以上面 `locale -a` 的实际输出为准，常见的是 `en_US.ISO8859-1` 和 `zh_CN.GBK`/`zh_CN.eucCN`。

## 4. 安装（每个 Python 版本各建一个全新 venv）

```bash
PY=python3.12; V=312            # 第二遍改为 python3.11 / 311
"$PY" -m venv "$T/venv$V" && . "$T/venv$V/bin/activate"
python -m pip install --upgrade pip
run install-$V pip install "$T/PATT-pdf[ocr,dev]"         # 普通（非 editable）安装
run version-$V patt-pdf --version                          # 预期：patt-pdf 0.3.5.dev0
python -c "import sys,pymupdf,numpy,fontTools,cv2;print(sys.version.split()[0],pymupdf.VersionBind,numpy.__version__,fontTools.version,cv2.__version__)"
pip list 2>/dev/null | grep -i -E "^(setuptools|pyyaml|pytest) "
```

**字体：**Noto Sans/Serif CJK SC，许可证为 SIL OFL 1.1。

- **已经装过时：**直接执行下面的 `patt-pdf fonts`。
- **没有时：**二选一。
  - 征得同意后安装：`brew install --cask font-noto-sans-cjk font-noto-serif-cjk`。
  - 不改系统：从 https://github.com/notofonts/noto-cjk 下载 `Sans/OTF/SimplifiedChinese/NotoSansCJKsc-{Regular,Bold}.otf` 和 `Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-{Regular,Bold}.otf` 到 `$T/noto`，再运行：
    ```bash
    export PATT_PDF_FONT_SOURCE="$T/noto"
    ```

```bash
export PATT_PDF_FONT_DIR="$T/fonts"
run fonts-$V patt-pdf fonts                                # 预期 exit=0
run doctor-$V patt-pdf doctor                              # 记录完整输出，包括 pth_strategy / pth_locale_encoding / site_frozen 三行
```

**OCR：**
- 有 Tesseract 且语言里有 `eng` 时，运行：
  ```bash
  run ocr-present-$V python "$T/PATT-pdf/tools/ci_check_ocr.py" expect-present
  ```
- 用户同意时可以 `brew install tesseract`；没有 Tesseract 时，有 OCR 的那组标为 SKIP。

## 5. 测试套件（以实际数字为准，逐条列出跳过原因）

```bash
cd "$T/PATT-pdf"
run pytest-$V python -m pytest -q -p no:cacheprovider -rs
PATT_PDF_TESSERACT="$T/no-tesseract-here" run ocr-absent-$V python tools/ci_check_ocr.py expect-absent     # 必须 exit=0
PATT_PDF_TESSERACT="$T/no-tesseract-here" run pytest-noocr-$V python -m pytest -q -p no:cacheprovider -rs
```

**按设计会跳过的项目**（用来核对，不是预填结果）：
- 总会跳过：`test_native_windows_lock`（仅限 Windows）。
- 没有任何非 UTF-8 locale 时：`test_pipeline_in_legacy_posix_locales`、`test_pth_decoding_matches_the_interpreters_own_rule`。
- 无 OCR 时另外跳过 5 项，原因写明 tesseract/opencv/OCR。

除此之外的任何跳过或失败，都要逐条报告：测试名、断言和日志尾部。

## 6. 专项复测 M1–M8

每项都记录：命令、退出码、关键输出、预期、实际，以及 PASS / FAIL / SKIP。

**M1：`.pth` 解码与编码探针（每个 Python 版本都做；这是上一轮的失败项）**
```bash
run m1-$V python -m pytest -q -p no:cacheprovider -rA -s tests/test_osenv.py tests/test_encoding.py -k "pth or stdlib or third_party or helper_covers"
grep -A12 "pth decoding (" "$T/logs/m1-$V.txt"
grep "site.addpackage strategy" "$T/logs/m1-$V.txt"
```
- **预期：**全部 PASS。
- 把 `pth decoding (...)` 下面每一行，以及 `site.addpackage strategy` 这一行，**原样抄入报告**。
- **依据 CPython 源码和 Linux 实测的判断**（请以实际输出为准）：
  - 3.12.4 及以上应为 `utf8-first`，3.11.x 应为 `locale`；python.org 和 Homebrew 的构建中 `frozen=True` 很常见。
  - macOS 的文件系统编码总是 UTF-8，所以 3.12.4+ 在 GBK 下预计 `found`；3.11 在 GBK 下预计 `error`（`PYTHONUTF8=0/1` 都一样），在 ISO8859-1 下预计 `missing`。
  - 测试比较的是“按这台解释器自己的规则预测的结果”和“实际结果”，所以只要两者一致就是 PASS，无论 found 还是 error。
- 若测试因为“无非 UTF-8 locale”而跳过，标为 SKIP，并附上 `locale -a`。

**M2：直接观测解释器的真实行为（不经过 pytest，每个 Python 版本都做）**
```bash
python - "$T" <<'EOF'
import os, sys, subprocess, pathlib
T = pathlib.Path(sys.argv[1]) / "pthprobe"; site = T / "site"; pkg = T / "源码 目录" / "pthprobe_pkg"
pkg.mkdir(parents=True, exist_ok=True); site.mkdir(parents=True, exist_ok=True); (pkg / "__init__.py").write_text("")
line = str(T / "源码 目录").encode("utf-8"); (site / "probe.pth").write_bytes(line + b"\n")
print("pth bytes (hex, first 40):", line[:40].hex())
child = ("import io,sys,site,locale,importlib.util as u\n"
         "def k(co):\n for c in co.co_consts:\n  yield from (k(c) if hasattr(c,'co_consts') else [c])\n"
         "s=[c for c in k(site.addpackage.__code__) if isinstance(c,str)]\n"
         "fz=site.addpackage.__code__.co_filename\n"
         "g=getattr(locale,'getencoding',lambda:'n/a')()\n"
         "e=io.TextIOWrapper(io.BytesIO(),encoding='locale').encoding\n"
         "try:\n site.addsitedir(sys.argv[1]); r='found' if u.find_spec('pthprobe_pkg') else 'missing'\n"
         "except Exception as x:\n r='error:'+type(x).__name__\n"
         "print(sys.version.split()[0], 'utf8-first' if 'utf-8-sig' in s else 'locale', 'getencoding='+g, 'locale-text='+e,\n"
         "      'fs='+sys.getfilesystemencoding(), 'utf8_mode=%d' % sys.flags.utf8_mode, 'site='+site.__file__.rsplit('/',2)[-2]+'/site.py', 'code='+fz, r)\n")
for loc in ["C.UTF-8", "en_US.UTF-8", "en_US.ISO8859-1", "zh_CN.GBK", "zh_CN.eucCN"]:
    for m in ("0", "1"):
        r = subprocess.run([sys.executable, "-S", "-c", child, str(site)], capture_output=True, text=True,
                           env=dict(os.environ, LC_ALL=loc, PYTHONUTF8=m))
        print(f"{loc:16s} PYTHONUTF8={m}:", (r.stdout.strip() or r.stderr.strip()[-200:]))
EOF
```
- 把输出原样抄入报告。这是判断 macOS 上真实行为的一手证据。
- 不存在的 locale 会被 macOS 静默忽略，此时 `getencoding` 仍会是 UTF-8。如实记录即可，不要把它当成异常。

**M3：可编辑安装与普通安装对比**（上一轮的导入问题；每个 Python 版本都做）
```bash
mkdir -p "$T/源码 目录"; cp -R "$T/PATT-pdf/." "$T/源码 目录/"
"$PY" -m venv "$T/venv-edit$V" && run m3-editable-install-$V "$T/venv-edit$V/bin/pip" install -e "$T/源码 目录"
for LOC in en_US.ISO8859-1 zh_CN.GBK; do for M in 0 1; do
  LC_ALL=$LOC PYTHONUTF8=$M run m3-edit-$V-$LOC-$M "$T/venv-edit$V/bin/python" -c "import patt_pdf; print('import OK')"
  LC_ALL=$LOC PYTHONUTF8=$M run m3-regular-$V-$LOC-$M "$T/venv$V/bin/python" -c "import patt_pdf; print('import OK')"
done; done
LC_ALL=en_US.ISO8859-1 PYTHONUTF8=0 run m3-doctor-$V "$T/venv-edit$V/bin/python" -m patt_pdf.cli doctor
"$T/venv-edit$V/bin/pip" list 2>/dev/null | grep -i setuptools
cat "$T/venv-edit$V/lib/python"*/site-packages/__editable__*.pth 2>/dev/null | head -c 200 | xxd | head -3
```
- 把结果整理成表：Python 版本 × locale × `PYTHONUTF8` × 安装方式 → `import OK` 或报错。
- **依据 CPython 源码的判断**（以实测为准，不符时原样报告，不要改测试来迁就）：
  - 3.12.4+：可编辑安装预计在各种情况下都能导入，doctor 不发出 .pth 警告。
  - 3.11：在 GBK 或 ISO8859-1 真正生效的 locale 下，可编辑安装预计失败，**`PYTHONUTF8=1` 也无效**；doctor 应发出警告；普通安装应成功。

**M4：无 OCR 时批处理继续执行**（上一轮的 `KeyError` 问题）
```bash
export PATT_PDF_TESSERACT="$T/no-tesseract-here"
IN="$T/in 输入"; python tests/fixtures/make_fixtures.py "$IN"; mv "$IN/truth.json" "$IN/manual_tm.json" "$T/"
S="$T/state-noocr-$V"; TM="$T/manual_tm.json"
run m4-plan-$V patt-pdf plan "$IN" --state "$S"                                            # 预期 exit=1
run m4-a1-$V patt-pdf translate "$IN" --state "$S" --backend pseudo --max-chars 99999      # 预期 exit=2
run m4-est-$V patt-pdf estimate "$IN" --state "$S" --backend manual --manual-tm "$TM"      # 末行预期 981 字符 / 40 句段
run m4-a2-$V patt-pdf render "$IN" --state "$S" --backend pseudo --files toc.pdf           # 预期 exit=2
run m4-a3-$V patt-pdf publish "$IN" --state "$S" --dest "$T/pub$V" --files toc.pdf        # 预期 exit=2，pub 中无 toc.pdf
run m4-b1-$V patt-pdf translate "$IN" --state "$S" --backend manual --manual-tm "$TM" --max-chars 99999   # 日志中 missing_from_backend 为 3
run m4-b2-$V patt-pdf translate "$IN" --state "$S" --backend manual --manual-tm "$TM" --max-chars 5       # 预期 exit=2，"exceeds --max-chars 5"
run m4-c1-$V patt-pdf render "$IN" --state "$S" --backend manual --manual-tm "$TM"        # 预期 exit=1
grep -c KeyError "$T/logs/m4-c1-$V.txt"                                                    # 预期 0
unset PATT_PDF_TESSERACT
```

预期状态（看 `m4-c1` 日志）：

| 文件 | 预期状态 |
|---|---|
| toc、financial、table、rotated、`报告 2026 – résumé` | `PASS` |
| decorations | `REVIEW` |
| image_text | `UNVERIFIED` |
| scanned、vector_glyphs、decor_scan | `FAIL` |
| two_column_cropbox | `FAIL`（测试数据中故意缺少译文） |
| damaged、encrypted、truncated | `ERROR` |

**M5：有 OCR（Tesseract + eng 可用时；否则 SKIP）**
```bash
S2="$T/state-ocr-$V"
run m5-plan-$V patt-pdf plan "$IN" --state "$S2"
run m5-tr-$V patt-pdf translate "$IN" --state "$S2" --backend manual --manual-tm "$TM" --max-chars 99999
run m5-render-$V patt-pdf render "$IN" --state "$S2" --backend manual --manual-tm "$TM"
PATT_PDF_TESSERACT="$T/no-tesseract-here" run m5-mixed-$V patt-pdf render "$IN" --state "$S2" --backend manual --manual-tm "$TM" --files "*scan*"
```
- **预期：**
  - `m5-render`：三个扫描或转曲样本为 `REVIEW`。
  - `m5-mixed`（有 OCR 时规划、无 OCR 时渲染）：`UNVERIFIED`，不出现 `KeyError`。

**M6：替换已打开的输出文件。**POSIX 系统上，文件被打开时通常仍能被替换，这和 Windows 不同。
```bash
open -a Preview "$S/out/table.pdf"; sleep 3
run m6-$V patt-pdf render "$IN" --state "$S" --backend manual --manual-tm "$TM" --files table.pdf
ls -a "$S/out" | grep -c '^\.tmp-'                                            # 预期 0
```
- 记录实际行为：替换成功，还是给出 “in use” 提示。
- 只有在 Preview 真实打开文件后才能标 PASS 或 FAIL；无法打开时标 SKIP。
- pytest 中的模拟测试**不能代替**本项。

**M7：路径脱敏（含上轮 `/custom/private/report.pdf` 的情形）**
```bash
run m7-report-$V patt-pdf report "$IN" --state "$S" --out "$T/report-$V.md"
grep -n -E "/Users/|$HOME|/private/var|/Volumes/" "$T/report-$V.md" "$S"/plans/*.error.json "$S"/qa/*.json "$S"/runs.jsonl | head   # 预期没有输出
grep -o "Failed to open file '[^']*'" "$T/report-$V.md" | head -2                                                                  # 预期 '<input>/truncated.pdf'
run m7-unit-$V python -m pytest -q -p no:cacheprovider tests/test_osenv.py -k "redact or custom_mount"
```

**M7b：重定向输出的控制台编码与平台模拟测试（v0.3.5 回归）**
```bash
for e in latin-1:surrogateescape cp1252:surrogateescape; do
  PYTHONIOENCODING=$e run m7b-${e%%:*}-$V patt-pdf plan "$IN" --state "$T/enc-$V-${e%%:*}" --no-ocr --files "报*"    # 预期 exit=0
done
grep -l UnicodeEncodeError "$T"/logs/m7b-*-$V.txt                                   # 预期：没有输出
run m7b-tests-$V python -m pytest -q -p no:cacheprovider -rA tests/test_reliability.py tests/test_encoding.py tests/test_osenv.py -k "console or windows_like or simulated_os or orders_user"
```
- 预期：全部 exit=0，`m7b-tests` 全部 PASS。这是在 Mac 上**模拟**非 UTF-8 输出，报告中要这样写。

**M8：中文路径、视觉效果与链接**
```bash
run m8-cmp-$V patt-pdf compare "$IN" --state "$S" --out "$T/cmp$V" --files "t*"
run m8-cmp2-$V patt-pdf compare "$IN" --state "$S" --out "$T/cmp$V" --files decorations.pdf
python -c "import pymupdf,sys; o=pymupdf.open(sys.argv[1]); print([sorted(l['uri'] for l in p.get_links()) for p in o])" "$S/out/decorations.pdf"
```
- 链接预期为 `[['https://example.org/field-guide', 'mailto:info@example.org'], ['https://example.org/map']]`。
- 用 Preview 查看 `$T/cmp$V`：数字、金额和日期两侧应相同，下划线应随中文缩短，表格线保留。

最后执行 `cat "$T/logs/_exitcodes.txt"`，把所有退出码一并附在报告中。

## 7. 保存证据与清理

- **证据：**把 `$T/logs/`、`$T/report-*.md` 和截图复制到**用户指定的私有位置**（不要放进仓库，也不要上传）。
- **脱敏：**用户名替换为 `<USER>`，home 路径替换为 `<HOME>`。
- **清理：**用户确认后执行下面的命令。不要卸载 Homebrew 软件包或字体，不要清理全局缓存。
  ```bash
  deactivate 2>/dev/null; echo "将删除：$T"; rm -rf "$T"
  ```

## 8. 反馈模板（发给用户，由用户转交 Claude）

```
候选 commit：<完整 SHA>    来源：A GitHub / B bundle（SHA-256 <…>）
证据类别：本报告只含本机实测；CI 结果（如引用）单独注明 run 链接
macOS <版本>（<arm64|x86_64>，<芯片>）  Git <…>  执行 shell：bash <版本>（登录 shell <…>）
Python 3.11：<x.y.z / 无>   Python 3.12：<x.y.z / 无>   setuptools <…>  pip <…>
PyMuPDF <…> numpy <…> fontTools <…> opencv <…> pytest <…> PyYAML <…>
字体来源：<cask / notofonts OTF / 已有>   Tesseract：<版本 + eng / 无>
旧 locale：<locale -a 中的非 UTF-8 项>
doctor（各版本，脱敏）：<…，含 pth_strategy / pth_locale_encoding>

pytest 3.11 有OCR / 无OCR：n passed / n failed / n skipped（逐条列出跳过原因）
pytest 3.12 有OCR / 无OCR：…
M1 .pth 测试 ........... PASS/FAIL/SKIP   strategy 行 + pth decoding 各行（原样）
M2 解释器实测 .......... 原样输出（各版本）
M3 可编辑/普通安装 ..... 表：版本 × locale × PYTHONUTF8 × 方式 → 结果
M4 无OCR批处理 ......... PASS/FAIL  c1 exit=<…>  KeyError=<…>  状态表偏差：<…>
M5 有OCR .............. PASS/FAIL/SKIP
M6 Preview 打开时替换 .. PASS/FAIL/SKIP（实际行为：…）
M7 路径脱敏 ............ PASS/FAIL
M7b 输出编码（模拟） .... PASS/FAIL
M8 视觉/链接 ........... PASS/FAIL（截图位置：私有）
_exitcodes.txt：<粘贴>

每个 FAIL：最小复现命令 / 预期 / 实际 / 日志位置（私有）
未验证项：真实 PDF、真实翻译 API、跨卷、信号中断、<其他>
```
