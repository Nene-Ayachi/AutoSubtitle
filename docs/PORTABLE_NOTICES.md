# 第三方组件

本包包含已验证的 Windows x64 Python 3.12 运行时及其依赖，由 conda-pack 生成可迁移归档。目标机器不需要安装 Conda；首次启动使用包内独立脚本修复路径。原始运行时归档保持不变，以便移动目录后重新初始化。

Python 及运行库授权文件保留在 runtime.zip 中（初始化后位于 runtime 目录）；Python 包的授权/元数据保留在 Lib/site-packages 的对应 dist-info 目录，Conda 包的记录保留在 conda-meta 与相关 Library 目录。依赖的授权适用于各自组件。

包含 FastAPI、Uvicorn、faster-whisper、CTranslate2、PyAV、NumPy、NVIDIA cuBLAS/cuDNN 及其传递依赖。NVIDIA GPU 库的授权文件随相应包保留。未包含 GPU 驱动。

FFmpeg 与 FFprobe 使用项目已验证的 Gyan Windows essentials 构建，原 LICENSE、README 在本目录。上游及构建信息：

- https://www.python.org/
- https://conda.github.io/conda-pack/
- https://github.com/SYSTRAN/faster-whisper
- https://github.com/OpenNMT/CTranslate2
- https://ffmpeg.org/
- https://www.gyan.dev/ffmpeg/builds/

前端由 React、MUI、Emotion、Vite 构建。构建时许可证注释随产物保留，依赖 LICENSE 文件及 package-lock 清单位于本目录。本包默认没有包含识别模型权重；加入权重时应同时保留对应模型来源和授权信息。
