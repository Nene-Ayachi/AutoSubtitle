# 便携版构建与验证

目标用户不需要安装 Miniforge/Conda、Python、Node/nvm、FFmpeg。包内运行时来自已验证的 media-tool 环境，用 conda-pack 生成；不是直接复制一个不可迁移的 Conda 文件夹。构建机仍需现有开发环境。

## 构建机

项目根目录执行，打包工具仅安装到 Git 忽略的 .tools，不修改现有环境：

```powershell
conda run -n media-tool python -m pip install --target .tools/portable-build/pack-tools conda-pack==0.8.1 setuptools==80.9.0
conda run --no-capture-output -n media-tool python scripts/build_portable.py
```

输出 `releases/MediaTool-Portable-Windows-x64.zip` 及 `.zip.sha256`。构建过程生成生产前端、封装 Python/依赖、复制 FFmpeg、授权文件和启动器。识别、字幕断句、文本导出、视频任务算法保持现状，仅增加显式 MEDIA_TOOL_WEB 配置下的静态网页挂载。

若只是修改应用代码/前端/启动器，且构建环境依赖未变，可使用 `--reuse-runtime`。依赖变动后必须重新构建运行时，不能复用旧归档。

默认不包含模型。若已有下载完整的项目 models 缓存，可加 `--include-models` 制作离线包；不要在模型下载中打包缓存。离线识别时需要选择包内已有的模型。

## 运行时迁移

启动器在自己的进程中设置私有 PATH/Python 环境，使用包内 python.exe 和 Library/bin，不执行目标机器上的 Conda、Node 或 pip。第一次启动校验 runtime.zip 的 SHA256，并用 Windows .NET 解压，然后运行包内 conda-unpack-script.py 修复前缀。

conda-pack 修复后的运行时不能再次直接迁移。为此保留原始 runtime.zip；启动器记录初始化路径，整包移动后自动删除并从原始归档重建 runtime，保留 models/data。路径清理只允许包内 runtime，拒绝目录链接。请正常退出后再移动。

Windows 本地 mutex 防止同目录重复启动；监听 socket 在 127.0.0.1 上预先占用，端口占用时尝试后续端口。Ctrl+C 或 Stop-MediaTool.cmd 请求正常关闭，已有视频任务走原有停止/清理流程。关闭浏览器不会关闭后台。

## 隔离验证

```powershell
# 在 .test-work 中解压、移动并运行实际发布包，清除开发环境 PATH/PYTHONPATH。
# --download 只将 small 下载到测试包的 models，不改变项目 models 或发布 zip。
conda run --no-capture-output -n media-tool python scripts/verify_portable.py --download
```

验证包含包内 native 库加载、中文/空格路径、初始化后迁移、缓存保留、端口冲突、重复启动、网页及 JS、真实 CPU/CUDA 识别、字幕编辑、TXT/SRT、可用 MP4 编码器、MKV 封装、取消/重试与退出后 session 清理。使用已有 .test-work 合成视频，验证数据和模型不进入发布包。

无识别素材时可加 `--skip-inference` 检查运行时/启动，不下载模型；完整识别检查需要先按 VALIDATION.md 生成测试素材。运行日志和报告在 `.test-work/portable-verification`。

当前验证在开发机上清除开发环境变量后进行。干净的另一台 Windows 电脑/虚拟机、不同驱动、无 GPU 和长路径机器仍需验收，不能将本机隔离测试当作这些机器已测试。

组件来源与授权见便携包 licenses/；[conda-pack 的迁移说明](https://conda.github.io/conda-pack/)介绍了原始归档修复路径的机制和限制。
