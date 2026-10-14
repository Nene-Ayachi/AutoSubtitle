# 从源码构建便携版

两个平台共用 `backend/`、`frontend/` 和 `scripts/common/launcher.py`。Windows x64 包必须在 Windows x64 构建，macOS arm64 包必须在原生 Apple Silicon Mac 构建；这两个脚本不是交叉编译器。目标用户无需安装 Python、Node、Conda/Homebrew 或 FFmpeg。

所有命令均从项目根目录执行。构建结果统一放在 `release/`：

```text
release/
├── MediaTool-Portable-Windows-x64.zip
├── MediaTool-Portable-Windows-x64.zip.sha256
├── MediaTool-Portable-macOS-arm64.zip
└── MediaTool-Portable-macOS-arm64.zip.sha256
```

某个平台的 ZIP 只有在对应平台实际构建成功后才会存在。构建一个平台不会删除另一个平台的产物。默认均不含模型，首次使用由用户勾选允许下载；需要全离线包时，先完整下载模型到项目 `models/`，再加 `--include-models`。不要在下载过程中打包模型，MLX 和 CTranslate2 的模型缓存不能互换。

## 源码脚本布局

```text
scripts/
├── common/
│   └── launcher.py             # 两个平台共用，打包时复制到包根目录
├── windows/
│   ├── install-ffmpeg.ps1
│   ├── start-backend.ps1
│   ├── start-frontend.ps1
│   ├── build_portable.py
│   ├── verify_portable.py
│   └── portable/               # Windows 成品启动模板：cmd、bootstrap.ps1
└── macos/
    ├── Setup-MediaTool.command # 源码安装，需要 Homebrew
    ├── Start-MediaTool.command # 源码启动，使用项目 .venv-macos
    ├── Stop-MediaTool.command
    ├── start.py
    ├── build_portable.py
    ├── verify_portable.py
    └── portable/               # macOS 成品启动模板：command、bootstrap.py
```

源码安装/启动脚本与便携包模板用途不同。不要直接运行 `portable/` 中的模板；它们需要构建后的完整目录。成品包内仍将启动/停止入口放在最外层，用户解压后可直接双击，无需进入 scripts。

## Windows x64

### 1. 准备构建环境

安装 Miniforge/Conda 和 Node.js 24（可用 nvm-windows 管理）。在 Windows PowerShell 中进入源码根目录：

```powershell
# 已有 media-tool 环境时跳过 create；不要删除其他环境。
conda create -n media-tool python=3.12 -y
conda run -n media-tool python -m pip install -r backend/requirements.txt

# 包含 CUDA 支持的发行包需要这两项运行库；不替代目标电脑的 NVIDIA 驱动。
conda run -n media-tool python -m pip install nvidia-cublas-cu12==12.8.4.1 nvidia-cudnn-cu12==9.10.2.21

# 确保 node --version 为 v24.x；如使用 nvm-windows，先执行 nvm use 24。
Push-Location frontend
npm ci
Pop-Location
.\scripts\windows\install-ffmpeg.ps1

# 打包工具只装到项目 .tools，不修改 Conda base 环境。
conda run -n media-tool python -m pip install --target .tools/portable-build/pack-tools conda-pack==0.8.1 setuptools==80.9.0
```

### 2. 构建

```powershell
conda run --no-capture-output -n media-tool python scripts/windows/build_portable.py
```

脚本构建前端、用 conda-pack 封装当前 `media-tool` 环境、复制 FFmpeg/FFprobe、启动器和许可证，输出 Windows ZIP 及 SHA256。仅修改应用代码时可追加 `--reuse-runtime`；Python 依赖或 NVIDIA 库变化后必须去掉此参数，重新打包运行时。

### 3. 验证

```powershell
# 不下载模型：验证解压、迁移、包内运行时、HTTP/JS、端口冲突和退出。
conda run --no-capture-output -n media-tool python scripts/windows/verify_portable.py --skip-inference

# 完整识别与导出验证，需要先按 VALIDATION.md 准备 .test-work 合成视频。
# --download 允许将 small 下载到测试包，不写入发行 ZIP。
conda run --no-capture-output -n media-tool python scripts/windows/verify_portable.py --download
```

Windows 验证报告位于 `.test-work/portable-verification/report.json`。完整模式包括 CPU/可用 CUDA 识别、编辑、TXT/SRT、可用编码器 MP4、MKV、取消和重试。

Windows 成品首次启动会从包内 runtime.zip 初始化私有运行时；移动整个包后重新初始化运行时并保留 models/data。保留 runtime.zip，不要单独搬动启动脚本。使用 `Start-MediaTool.cmd` 和 `Stop-MediaTool.cmd`。

## macOS Apple Silicon ZIP

### 1. 准备构建环境

需要原生 Apple Silicon Mac、macOS 14+、Homebrew，以及 Apple Command Line Tools。首次缺少命令行工具时执行 `xcode-select --install`，按系统界面完成安装。

```bash
bash scripts/macos/Setup-MediaTool.command
```

安装脚本准备 Python 3.12、Node 24、ffmpeg-full、项目 `.venv-macos` 和前端依赖。后续重新开终端时，构建前确保 Node 24 在 PATH 中：

```bash
export PATH="$(brew --prefix node@24)/bin:$PATH"
node --version
```

### 2. 构建

```bash
.venv-macos/bin/python scripts/macos/build_portable.py
```

脚本下载并校验可迁移的 python-build-standalone；从依赖清单安装 macOS 14 兼容 wheels（MLX 固定 0.29.3），下载并校验静态 FFmpeg/FFprobe，构建前端、收集许可证，输出 macOS ZIP 及 SHA256。不会复制不可迁移的开发 venv 或 Homebrew 动态库。构建缓存位于 `.tools/portable-macos-build/`。

应用代码/入口更新后可加 `--reuse-runtime`。缓存指纹包含后端 requirements、固定的 Python/MLX 版本及目标系统，指纹变化时自动重建依赖。包内原生文件会检查最低 macOS 版本及绝对动态库依赖，拒绝依赖开发机/Homebrew 路径的构建。

### 3. 验证

```bash
.venv-macos/bin/python scripts/macos/verify_portable.py
```

验证真实 ZIP 在中文空格目录解压、整包移动、隔离开发环境、首次信任的取消/确认、私有 Python/MLX/FFmpeg、Metal 探测、字幕烧录、MKV 封装、网页/JS、端口冲突、重复启动和停止。测试需要本机访问 Metal 和回环网络；受限沙箱可能阻止它们。

报告写入 `.test-work/macos-portable-*/report.json`。默认不下载模型，不把这些检查视为真实语音识别验证。macOS 14 最低版本依据 wheel 和 Mach-O 元数据，仍需在目标系统实机验收。

macOS 成品首次使用 `首次信任并启动.command`，核实来源和路径后输入 `TRUST`，仅解除包内隔离标记；以后使用 `Start-MediaTool.command`，退出使用 `Stop-MediaTool.command`。这不是 Apple 公证，入口本身仍可能需要在“隐私与安全性”中允许打开，不保证严格只出现一个系统弹窗。

## 发布前检查

- 核对对应 ZIP 和 SHA256；Windows 用 `Get-FileHash`，macOS 用 `shasum -a 256`。
- 每个平台执行自己的验证脚本；更新运行时后重新验证。
- 在另一台没有开发环境的目标平台机器测试启动、真实识别和导出。
- 运行时许可证、依赖版本/来源随包保留；加入模型时保留对应授权信息。
- 测试数据和验证用模型只放 `.test-work/`，不混入默认发行 ZIP。

`release/`、`.tools/` 和 `.test-work/` 都是生成目录，不提交 Git。修改源码后需要重新打包，移动脚本不会自动更新已经分发的 ZIP。
