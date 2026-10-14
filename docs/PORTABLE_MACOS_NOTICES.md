# macOS 第三方组件

本包使用 Astral python-build-standalone 的可迁移 CPython 3.12.15（20261013，arm64），未复制开发机 venv/Homebrew 环境。Python 许可证保留在 runtime，Python 包许可证保留在 site-packages 的 dist-info 等原始目录；精确下载来源、版本和哈希见 python-packages.json 与包根目录 bundle-manifest.json。

包含 MLX/MLX Whisper（Apple）、faster-whisper、CTranslate2、PyAV、PyTorch、NumPy、FastAPI、Uvicorn 等及传递依赖。MLX 固定 0.29.3 并选择 macOS 14 兼容 wheel。前端依赖许可证及锁文件一并保留。

FFmpeg/FFprobe 使用 Martin Riedl 的 macOS arm64 静态构建 9.0.2（2026-09-20）。构建配置见 FFmpeg-build.txt，许可见 FFmpeg-license.txt（启用 GPLv3）；上游源码及构建脚本公开如下。若向第三方重新分发，应按组件许可证提供对应源码及构建材料。

- Python：https://github.com/astral-sh/python-build-standalone/releases/tag/20261013
- MLX Whisper：https://github.com/ml-explore/mlx-examples/tree/main/whisper
- FFmpeg 构建来源：https://ffmpeg.martin-riedl.de/
- FFmpeg 构建脚本：https://git.martin-riedl.de/ffmpeg/build-script
- FFmpeg 源码：https://ffmpeg.org/download.html

默认不包含模型权重。通过 --include-models 加入模型时，需保留相应来源及许可证。包未进行 Apple Developer ID 签名、公证。首次信任入口经用户明确确认后，仅解除包内隔离标记；不关闭 Gatekeeper。
