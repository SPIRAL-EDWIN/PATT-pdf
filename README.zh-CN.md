<div align="center">

# PATT-PDF

**面向位置的 PDF 翻译工具包**

将英文 PDF 翻译为简体中文，并尽量把译文放回原文所在的位置。

[English](README.md) · [简体中文](README.zh-CN.md)

[效果预览](#效果预览) · [安装](#安装) · [快速开始](#快速开始) · [项目文档](#项目文档)

</div>

> **实验性项目 · v0.3.6.dev0。** 当前是命令行原型，还不是完整的桌面应用。上一版（v0.3.5）已通过 Linux、macOS、Windows 的 CI，并在一台 Mac 和一台 Windows 电脑上离线复测；本版修复了复测中发现的问题，目前只在 Linux 上测试过。尚未验证真实 PDF，也未进行真实 DeepL 请求。输出可能不完整或有误，请务必人工复核。详见[平台验证状态](docs/STATUS.md)。

## 效果预览

<p align="center">
  <img src="docs/sample/compare_synthetic.jpg" alt="合成 PDF 页面翻译前后对照：左侧英文原文，右侧简体中文译文" width="800">
</p>

*左侧为原文，右侧为译文。图片由多个合成测试页面拼接而成，使用固定译文，并非真实文件或 DeepL 效果测试；也不代表所有页面均通过质量检查。参见[示例报告](docs/sample/REPORT_SAMPLE.md)。*

## PATT 能做什么

- **尽量原位翻译：**提取文字并尝试在原区域放回译文，同时保留周围图形、数字和其他受保护内容。
- **便于复核：**提供页面规划、翻译量估算、排版、质量检查报告和原译对照图。
- **可选翻译后端：**支持 DeepL API、离线人工译文表，以及用于版面测试的伪翻译。PATT 是处理流程，不是翻译模型。
- **保护输入：**原文件、工作状态和发布结果分开；发布时不会覆盖已有文件。
- **实验性 OCR：**通过可选的本地 Tesseract 处理部分扫描页和转曲文字页面；图片内文字目前不会被翻译。

当前只支持英文 → 简体中文。复杂版面、表格、扫描件、公式及其他真实文档可能无法忠实还原。目前没有图形界面、大语言模型后端或各系统独立安装包。详见[功能与限制](docs/REFERENCE.md#what-it-does-and-how-well)。

## 安装

展开对应系统，查看从源码安装的步骤。三个系统使用同一个 Python 包，目前没有按系统区分的下载包。需要先安装 Git 和 Python 3.10 或更新版本；3.10–3.13 是计划测试的版本范围。字体需包含 Noto Sans CJK SC 和 Noto Serif CJK SC 的常规与粗体。OCR 另外需要带英文数据的 Tesseract 和 Python 的 `[ocr]` 扩展。

<details>
<summary><b>macOS</b></summary>

使用 Homebrew 安装字体，或从 [Noto CJK releases](https://github.com/notofonts/noto-cjk/releases) 获取静态 SC OTF 字体。需要 OCR 时另装 Tesseract。

```bash
brew install --cask font-noto-sans-cjk font-noto-serif-cjk
# 扫描页 / 转曲文字需要时安装：
brew install tesseract

git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git
cd PATT-pdf
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .          # 需要 OCR 时改为 '.[ocr]'
patt-pdf fonts
patt-pdf doctor
```

</details>

<details>
<summary><b>Windows</b></summary>

从 [Noto CJK releases](https://github.com/notofonts/noto-cjk/releases) 下载静态 SC OTF 字体并为当前用户安装，或放入文件夹后设置 `PATT_PDF_FONT_SOURCE`。需要 OCR 时安装带英文数据的 [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)。在 PowerShell 中运行：

```powershell
git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git
cd PATT-pdf
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .          # 需要 OCR 时改为 '.[ocr]'
patt-pdf fonts
patt-pdf doctor
```

如果没有 Python 启动器，可用 `python -m venv .venv`。未启用 Windows 长路径时建议使用 `C:\patt` 等短路径；如果 `pip install` 报临时文件不存在或“文件已存在”，可运行 `python tools\install_check.py --source . --work C:\pt`，它会把源码干净复制到一个新的短目录再安装（不会删除任何东西）。OCR 依赖不一定覆盖所有 Python / CPU 组合，包括 Windows ARM；请查看 `doctor` 和[平台说明](docs/STATUS.md)。

</details>

<details>
<summary><b>Linux（Debian / Ubuntu）</b></summary>

```bash
sudo apt install fonts-noto-cjk python3-venv
# 扫描页 / 转曲文字需要时安装：
sudo apt install tesseract-ocr tesseract-ocr-eng

git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git
cd PATT-pdf
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .          # 需要 OCR 时改为 '.[ocr]'
patt-pdf fonts
patt-pdf doctor
```

</details>

`patt-pdf fonts` 将本机已有字体复制到当前用户目录，不会自动下载字体。`doctor` 会报告字体、Tesseract 和环境警告。如果连 `patt-pdf` 都无法启动（例如 Python 3.11、非 UTF-8 区域设置、从中文目录做的可编辑安装），请用同一个 Python 运行 `python -S tools/preflight.py`：它只依赖标准库，并会给出恢复建议。自定义路径及编码注意事项见[详细安装说明](docs/REFERENCE.md#install)。

## 快速开始

将 PDF 文件或文件夹放在 `./in`。`./work` 是私有工作目录，须放在输入目录之外。以下示例使用 DeepL，会向其 API 发送待翻译文本；请先在环境中设置 `DEEPL_AUTH_KEY`。API 可能产生费用，建议先用少量非敏感内容试用。

```bash
patt-pdf plan      ./in --state ./work
patt-pdf estimate  ./in --state ./work --backend deepl
# 查看估算后，自行设置字符预算：
patt-pdf translate ./in --state ./work --backend deepl --max-chars 10000 --yes
patt-pdf render    ./in --state ./work --backend deepl
patt-pdf report    ./in --state ./work --out report.md
patt-pdf compare   ./in --state ./work --out ./comparison
patt-pdf publish   ./in --state ./work --dest ./translated --suffix " zh-Hans"
```

使用结果前请检查报告和对照图。`publish` 默认只复制状态为 `pass` 的文件；`pass` 仅表示自动检查未发现问题，并不保证翻译正确。若希望完全离线使用固定译文，参见[人工译文示例](docs/REFERENCE.md#quick-start-offline-no-api)。`estimate`、`translate`、`render` 之间应保持后端、人工译文表和术语表配置一致。

**隐私与费用：**工作目录会以明文保存原文和译文；DeepL 会收到待翻译文本。实际计费由 DeepL 决定，结果未知的请求也可能已被处理和计费，预算及配额检查不能保证最终账单金额。使用前请阅读 [DeepL、隐私与费用说明](docs/REFERENCE.md#deepl-key-cost-and-privacy)。

## 项目文档

- [详细参考文档](docs/REFERENCE.md)：安装、后端、质量检查状态、退出码、隐私与平台历史
- [当前状态与验证](docs/STATUS.md) · [架构](docs/ARCHITECTURE.md) · [迁移](docs/MIGRATION.md)

## 开发

```bash
python -m pip install -e '.[ocr,dev]'
python -m pytest -q
```

测试离线运行并使用合成样本；OCR 测试需要 Tesseract。请留意[可编辑安装的注意事项](docs/REFERENCE.md#install)，尤其是非 ASCII 路径和较旧 Python 环境。

## 许可证

[AGPL-3.0-or-later](LICENSE)。PATT-PDF 使用的 PyMuPDF/MuPDF 采用 AGPL 或商业许可。依赖、字体与致谢见[第三方声明](THIRD_PARTY_NOTICES.md)。
