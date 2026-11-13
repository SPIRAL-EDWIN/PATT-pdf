# 安装 PATT-PDF

[README](../README.zh-CN.md) · [English](INSTALL.md)

PATT-PDF 只有一种安装：完整安装（Python 包、OpenCV、带英文数据的 Tesseract、Noto CJK 字体）。需要 Python 3.10 或更新版本。

## 一行命令安装（macOS 与 Linux）

```bash
curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh | bash
```

脚本会在执行每一步之前先打印出来，最后运行 `patt-pdf doctor`，让你立刻看到安装是否完整。它依次完成：

1. **系统组件**：Noto Sans/Serif CJK SC 字体、带英文数据的 Tesseract，以及（找不到时）Python ≥ 3.10。macOS 上这些通过 **Homebrew** 安装：如果尚未安装 Homebrew，脚本会明确说明并征得你同意后，才运行 Homebrew 官方安装程序（需要管理员密码，并会安装 Xcode 命令行工具）。Linux 上通过 `sudo` 调用 `apt-get`（Debian/Ubuntu）、`dnf`（Fedora/RHEL）、`pacman`（Arch）或 `zypper`（openSUSE），可能会要求输入密码。
2. **PATT-PDF 本体**，连同 OpenCV、PyMuPDF、NumPy 和 fontTools，装进独立的虚拟环境 `~/.local/share/patt-pdf/venv`，不会写入系统 Python。
3. **命令** `~/.local/bin/patt-pdf`；如果该目录不在 `PATH` 中，脚本会询问是否在 shell 启动文件里加一行（或把这一行打印出来由你自行添加）。
4. `patt-pdf fonts` 与 `patt-pdf doctor`。

### 下载来源与进度

下载任何东西之前，脚本会先说明来源并询问：

```text
==> 选择下载来源
      1) 国内镜像【默认】：清华大学 TUNA 镜像站
      2) 官方源【在中国大陆较慢】：pypi.org、Homebrew、GitHub
    回车 = 保持镜像，输入 2 = 改用官方源：
```

* **镜像（默认）。** Python 包来自 `pypi.tuna.tsinghua.edu.cn`，Homebrew 软件包来自 `mirrors.tuna.tsinghua.edu.cn/homebrew-bottles`。这些是镜像站保存的副本，不是原发布方直接提供的文件。pip 和 uv 仍会按所用索引里的哈希校验每个文件。
* **官方源。** `pypi.org`、Homebrew 自己的服务器和 GitHub。不在中国大陆时请选这个。
* 可以用 `--mirror cn` 或 `--mirror official`（或环境变量 `PATT_PDF_MIRROR`）预先回答。没有终端时（CI、`--yes`）使用镜像。镜像 8 秒内没有响应时自动改用官方源。
* 该设置只对本次运行生效，不会改动 pip 和已有 Homebrew 的配置。唯一的例外会在发生时说明：由脚本通过镜像安装的 Homebrew，会继续以镜像作为更新来源。
* 镜像上没有的两样：PATT-PDF 自己的源码（约 2 MB，来自 GitHub），以及 macOS 上的 Noto CJK 字体（约 235 MB，由 Homebrew 从 GitHub 下载；字体已安装时跳过）。即使选了镜像，这两样仍来自 GitHub。

五个步骤各自显示序号、下载内容和大致下载量，下载工具显示自己的进度。Python 包约 75–110 MB，因平台而异。如果本机已有 [`uv`](https://docs.astral.sh/uv/)，脚本会用它（并行下载），否则用 pip；脚本不会安装 uv。`--no-uv` 强制使用 pip。

在中国大陆的一台 Apple Silicon Mac 上实测过一次（只含 Python 包，空缓存，先后进行）：pip 走镜像 27 秒、走官方源 52 秒；uv 走镜像 33 秒。只有一台机器、一个晚上的数据，仅供参考，不是基准测试。

想先看再跑？先下载，再运行同一个文件：

```bash
curl -fsSL https://raw.githubusercontent.com/SPIRAL-EDWIN/PATT-pdf/main/install.sh -o install.sh
less install.sh
bash install.sh            # 选项：--help、--ref v0.x.y、--mirror cn|official、--no-uv、--no-system、--yes、--uninstall
```

重新运行脚本即为升级；`bash install.sh --uninstall`（或 `curl … | bash -s -- --uninstall`）会删除虚拟环境和命令链接，不动系统软件包、字体和你的数据。`--no-system` 跳过第 1 步，适合自己安装字体、Tesseract 和 Python 的情况；`--ref` 安装指定标签或提交而不是 `main`。CI 在预备好系统依赖的环境中检查安装流程。Fedora、Arch、openSUSE 的系统软件包安装尚未验证（见[平台状态](STATUS.md)）。该脚本不适用于 Windows。

## 手动安装

与一行命令相同的结果，分步完成。三个系统使用同一个 Python 包，没有按系统区分的下载包。需要先安装 Git 和 Python。字体需包含 Noto Sans CJK SC 和 Noto Serif CJK SC 的常规与粗体；按下方步骤安装带英文数据的 Tesseract。

<details>
<summary><b>macOS</b></summary>

使用 Homebrew 安装字体，或从 [Noto CJK releases](https://github.com/notofonts/noto-cjk/releases) 获取静态 SC OTF 字体。同时安装 Tesseract 以支持 OCR。

```bash
brew install --cask font-noto-sans-cjk font-noto-serif-cjk
# 安装 OCR 引擎和英文识别数据：
brew install tesseract

git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git
cd PATT-pdf
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
patt-pdf fonts
patt-pdf doctor
```

</details>

<details>
<summary><b>Windows</b></summary>

> Windows 由一位 Windows 协作者开发和测试；本版本**未在 Windows 上验证**。以下步骤仅供参考。

从 [Noto CJK releases](https://github.com/notofonts/noto-cjk/releases) 下载静态 SC OTF 字体并为当前用户安装，或放入文件夹后设置 `PATT_PDF_FONT_SOURCE`。标准安装还需安装带英文数据的 [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)。在 PowerShell 中运行：

```powershell
git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git
cd PATT-pdf
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
patt-pdf fonts
patt-pdf doctor
```

如果没有 Python 启动器，可用 `python -m venv .venv`。未启用 Windows 长路径时建议使用 `C:\patt` 等短路径；如果 `pip install` 报临时文件不存在或“文件已存在”，可运行 `python tools\install_check.py --source . --work C:\pt`，它会把源码干净复制到一个新的短目录再安装（不会删除任何东西）。OpenCV wheel 不一定覆盖所有 Python / CPU 组合，包括 Windows ARM；这种情况下标准 `pip install .` 可能失败，无法运行 `doctor`。详见[平台说明](STATUS.md)。

为降低凭据泄露风险，`install_check.py` 会隐藏 pip 输出并报告退出码。这不能控制 pip 自身的文件日志、配置、环境变量或进程参数：请避免在命令参数、`PIP_LOG`、`--log` 或共享配置中放入凭据，并在分享日志前检查。

</details>

<details>
<summary><b>Linux（Debian / Ubuntu）</b></summary>

```bash
sudo apt install fonts-noto-cjk python3-venv
# 安装 OCR 引擎和英文识别数据：
sudo apt install tesseract-ocr tesseract-ocr-eng

git clone https://github.com/SPIRAL-EDWIN/PATT-pdf.git
cd PATT-pdf
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
patt-pdf fonts
patt-pdf doctor
```

</details>

`patt-pdf fonts` 将本机已有字体复制到当前用户目录，不会自动下载字体。`doctor` 会报告字体、Tesseract 和环境警告。如果连 `patt-pdf` 都无法启动（例如 Python 3.11、非 UTF-8 区域设置、从中文目录做的可编辑安装），请用同一个 Python 运行 `python -S tools/preflight.py`：它只依赖标准库，默认输出不含本机路径，并会给出恢复建议。自定义路径及编码注意事项见[详细安装说明](REFERENCE.md#install)。
