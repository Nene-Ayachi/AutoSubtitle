# Apple Silicon macOS

支持原生 arm64 Python 的 M 系列 Mac。保持 faster-whisper/CTranslate2 后端：语音识别使用 ARM CPU，自动选择运行库支持的精度（int8 不支持时回退 float32），不提供 Metal/MPS 或 Neural Engine 推理。VideoToolbox 仅用于视频编码，不用于语音识别。

## 首次安装

将工程放在有写权限的本地目录，安装 [Homebrew](https://brew.sh)，在该目录执行：

```bash
bash Setup-MediaTool.command
```

脚本安装 Homebrew `python@3.12`、`node@24`、`ffmpeg-full`，创建项目内 `.venv-macos`，安装固定版本后端依赖，构建前端并检查运行库。无需 Miniforge、Conda 或 nvm。首次安装需要网络；不自动下载识别模型。使用 ffmpeg-full 是为了包含 libass 字幕烧录依赖，它是 keg-only 包，应用直接解析其路径，不需要强制 brew link。

首次安装脚本如果失败，应保留完整错误日志，不要复制 Windows 的 Python 环境或 node_modules。源目录可跨平台复制，虚拟环境不能直接搬家；移动工程后使用原生 Python 重建 `.venv-macos`，再重新安装。项目 models 目录可以保留。

## 启动与退出

安装成功后双击 `Start-MediaTool.command`；也可以执行 `bash Start-MediaTool.command`。启动器只监听 127.0.0.1，自动选择 8765 起的可用端口，打开浏览器；不需要另启 Vite，也不需要 Node 常驻。双击 `Stop-MediaTool.command` 或在启动窗口按 Ctrl+C 退出。关闭浏览器不会取消任务。macOS 若要求确认来源，按系统正常流程允许可信的本地工程，不关闭 Gatekeeper。

默认启动器把 data、models、logs 保存在工程目录。直接用 uvicorn 启动后端时，媒体临时目录默认在 `~/Library/Application Support/MediaTool`，模型仍在工程 models。应用不会持久化识别任务，退出前导出所需结果。

识别建议先测试 small + 自动精度。不要把大模型的 CPU 速度等同于 Windows CUDA。中文默认字体 PingFang SC，可用 MEDIA_TOOL_FONT 覆盖；日文需要实际确认系统字体回退。

MP4 可选 CPU H.264；只有本机 FFmpeg 的实际单帧硬件编码探测通过后，才提供 H.264 Apple VideoToolbox。使用 8 Mbps 视频码率；不允许编码器静默改用软件实现。MKV 外挂封装、TXT/SRT 和任务取消共用现有流程。FFmpeg 先 q 正常退出，再 SIGTERM，超时 SIGKILL，等待退出后清理当前任务文件。模型准备/当前推理仍为协作式取消。

## 验证与发布边界

开发机是 Windows，已添加模拟 macOS 的路径、CPU 精度回退、硬件探测以及 VideoToolbox 参数/清理测试。2026-10-14 后端回归 70 项通过、1 项显式启用的 CUDA 测试跳过；前端 TypeScript/Vite 生产构建通过。没有在真实 Mac 执行安装、ARM 推理、VideoToolbox 编码、字体与 Finder 启动验证。

在 Apple Silicon 上执行：

```bash
.venv-macos/bin/python scripts/start_macos.py --check
(cd backend && ../.venv-macos/bin/python -m pytest -q)
```

还需实际验证：中文/日文识别→编辑→TXT/SRT→CPU/VideoToolbox MP4→MKV；处理中取消与重试；带空格中文目录；退出无遗留 FFmpeg。GPU 专项测试是 NVIDIA CUDA 测试，不适用于 Apple GPU。

本次提供源码安装和双击启动支持；现有 Windows 便携包不能在 Mac 使用，尚未生成无依赖 macOS .app/DMG。此类包需要在真实 Apple Silicon 上构建、验证 ARM 动态库及签名公证后发布，不能将 Windows 包改名充当 Mac 版本。

依据：[CTranslate2 平台支持](https://opennmt.net/CTranslate2/installation)、[硬件后端](https://opennmt.net/CTranslate2/hardware_support.html)、[Homebrew ffmpeg-full](https://formulae.brew.sh/formula/ffmpeg-full)。
