# Apple Silicon macOS

支持原生 arm64 Python 的 M 系列 Mac。语音识别新增 MLX Whisper 后端，使用 Apple Metal GPU。自动设备优先选择探测通过的 Metal；MLX 缺失或 Metal 不可用时选择 faster-whisper/CTranslate2 ARM CPU，自动选择支持的精度（int8 不支持时回退 float32）。也可手动选择 CPU。不支持 Intel Mac 的 Metal 推理或 Neural Engine。VideoToolbox 仅用于视频编码，不用于语音识别。

## 首次安装

将工程放在有写权限的本地目录，安装 [Homebrew](https://brew.sh)，在该目录执行：

```bash
bash scripts/macos/Setup-MediaTool.command
```

脚本安装 Homebrew `python@3.12`、`node@24`、`ffmpeg-full`，创建项目内 `.venv-macos`，安装固定版本后端依赖，构建前端并检查运行库。无需 Miniforge、Conda 或 nvm。首次安装需要网络；不自动下载识别模型。使用 ffmpeg-full 是为了包含 libass 字幕烧录依赖，它是 keg-only 包，应用直接解析其路径，不需要强制 brew link。

首次安装脚本如果失败，应保留完整错误日志，不要复制 Windows 的 Python 环境或 node_modules。源目录可跨平台复制，虚拟环境不能直接搬家；移动工程后使用原生 Python 重建 `.venv-macos`，再重新安装。项目 models 目录可以保留。

## 启动与退出

源码安装成功后双击 `scripts/macos/Start-MediaTool.command`；也可以在项目根目录执行 `bash scripts/macos/Start-MediaTool.command`。启动器只监听 127.0.0.1，自动选择 8765 起的可用端口，打开浏览器；不需要另启 Vite，也不需要 Node 常驻。双击 `scripts/macos/Stop-MediaTool.command` 或在启动窗口按 Ctrl+C 退出。关闭浏览器不会取消任务。macOS 若要求确认来源，按系统正常流程允许可信的本地工程，不关闭 Gatekeeper。

默认启动器把 data、models、logs 保存在工程目录。直接用 uvicorn 启动后端时，媒体临时目录默认在 `~/Library/Application Support/MediaTool`，模型仍在工程 models。应用不会持久化识别任务，退出前导出所需结果。

识别建议先测试 small + 自动设备/精度，完成后指标应显示 `metal / float16`。已有安装重新运行 `bash scripts/macos/Setup-MediaTool.command` 即可安装新增的 `mlx-whisper==0.4.3` 依赖并构建界面。此依赖仅在 macOS arm64 安装。

Metal 支持 float16、float32；不支持 int8/int8_float16，手动选择不支持的精度会报错。MLX 当前不支持 Beam Search，界面固定显示 Beam Size 1，API 的其他值会在结果中提示使用贪心解码。VAD 使用 Silero 检测语音区间，通过 MLX 的 clip_timestamps 保留原始时间轴；支持词级时间戳。每次最多处理 60 秒音频，当前 MLX 调用/模型加载返回后响应取消。

四种模型分别映射到 `mlx-community/whisper-small-mlx`、`whisper-medium-mlx`、`whisper-large-v3-turbo`、`whisper-large-v3-mlx`。MLX 权重与 CTranslate2 权重不能互用，缓存存储在 `models/mlx`；首次切换后端可能需要重新勾选允许下载。未授权下载时仅查找本地缓存。模型加载或推理失败会报告错误，用户可选择 CPU 重试；不会静默更换模型或后端。不要把大模型的 CPU 速度等同于 GPU。中文默认字体 PingFang SC，可用 MEDIA_TOOL_FONT 覆盖；日文需要实际确认系统字体回退。

MP4 可选 CPU H.264；只有本机 FFmpeg 的实际单帧硬件编码探测通过后，才提供 H.264 Apple VideoToolbox。使用 8 Mbps 视频码率；不允许编码器静默改用软件实现。MKV 外挂封装、TXT/SRT 和任务取消共用现有流程。FFmpeg 先 q 正常退出，再 SIGTERM，超时 SIGKILL，等待退出后清理当前任务文件。模型准备/当前推理仍为协作式取消。

## 验证与发布边界

自动化测试覆盖 macOS 路径、CPU 精度回退、Metal 探测/失败回退、MLX 模型缓存/下载许可、精度切换、VAD 时间戳、词级数据及 VideoToolbox 参数/清理。模拟后端测试不能替代真实模型识别质量和性能验证。

2026-10-14 本次验证：Apple Silicon 实机 Metal 运算探测通过（`metal=true`），前端生产构建通过；使用便携包内 FFmpeg 后，后端回归 81 项通过、1 项 CUDA 专项跳过。实际 ZIP 的迁移、Metal 探测、字幕烧录、MKV、网页启动及退出验证通过。尚未下载模型进行真实语音识别、速度/内存和完整 VideoToolbox 导出验证。

在 Apple Silicon 上执行：

```bash
.venv-macos/bin/python scripts/macos/start.py --check
(cd backend && ../.venv-macos/bin/python -m pytest -q)
```

还需实际验证：中文/日文识别→编辑→TXT/SRT→CPU/VideoToolbox MP4→MKV；处理中取消与重试；带空格中文目录；退出无遗留 FFmpeg。GPU 专项测试是 NVIDIA CUDA 测试，不适用于 Apple GPU。

另提供 Apple Silicon ZIP 便携包：完整解压后双击包内 Start-MediaTool.command，不需要运行 Setup 或安装 Homebrew/Python/Node。适用于 macOS 14+，内含独立运行时、Metal 依赖、FFmpeg/FFprobe；默认不含模型。见 [便携版使用说明](PORTABLE_MACOS_QUICKSTART.md) 和 [构建说明](PORTABLE_BUILD.md#macos-apple-silicon-zip)。ZIP 未做 Apple Developer ID 签名/公证，不能视为已公证的 .app/DMG。Windows 包不能在 Mac 使用。

依据：[CTranslate2 平台支持](https://opennmt.net/CTranslate2/installation)、[硬件后端](https://opennmt.net/CTranslate2/hardware_support.html)、[Homebrew ffmpeg-full](https://formulae.brew.sh/formula/ffmpeg-full)。

MLX 接口依据：[MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)。
