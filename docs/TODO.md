# 待办事项

更新日期：2026-10-14。构建步骤见 [PORTABLE_BUILD.md](PORTABLE_BUILD.md)，完成后将证据补入 [DONE.md](DONE.md)。

## 优先：Windows 当前版本成品构建与验证

- [ ] 在 Windows x64 拉取当前工程，按构建指南准备 Python 3.12/Conda、Node 24、FFmpeg、CUDA 运行库和 conda-pack。
- [ ] 执行 `conda run --no-capture-output -n media-tool python scripts/windows/build_portable.py`，确认生成 `release/MediaTool-Portable-Windows-x64.zip` 和 `.zip.sha256`，核对哈希及许可证。依赖更新后不能沿用旧运行时缓存。
- [ ] 执行 `conda run --no-capture-output -n media-tool python scripts/windows/verify_portable.py --skip-inference`，验证中文/空格路径、移动目录后的运行时初始化、数据保留、HTTP/JS、端口冲突、重复启动与停止。
- [ ] 按 `VALIDATION.md` 准备合成语音素材，执行 `conda run --no-capture-output -n media-tool python scripts/windows/verify_portable.py --download`；验证 CPU 及可用 CUDA 识别、字幕编辑、TXT/SRT、MP4/MKV、取消和重试。缺少 NVIDIA GPU 时须保留 CUDA 未验收状态。
- [ ] 在未安装 Python、Node、Conda、FFmpeg 的干净 Windows 机器上解压运行，验收双击启动、浏览器打开、首次模型下载、停止和重启；确认不依赖构建机路径。
- [ ] 保存提交号、系统/GPU、依赖版本、ZIP SHA256、测试结果及 `.test-work/portable-verification/report.json`。将可公开的结果摘要写入文档，不提交用户媒体或模型权重。

验收标准：当前版本原生构建成功、上述适用检查通过且证据完整。历史 Windows 成品或 macOS 上的模拟包组装测试不能代替此项。

## macOS 后续验收

- [ ] 完整下载所选 MLX 模型，验证真实 Metal 语音识别、字幕编辑、导出、取消和重试；目前仅验证依赖、Metal 探测和非模型导出流程。
- [ ] 在干净 Apple Silicon Mac 和 macOS 14 目标系统验收；记录从实际下载 ZIP 开始的隔离提示、信任流程及启动情况。
- [ ] 验证无代理、HTTP/SOCKS 代理、断网和失败重试下的完整模型下载；明确系统静态代理与 PAC 的支持范围。
- [ ] 若未来取得 Apple Developer Program 会员及 Developer ID 证书，再实施签名和公证；当前不具备条件，不宣称免提示或已公证。

## 其他已有验证缺口

- [ ] 在 RTX 5060 Laptop 8GB 上完成 10 分钟 1080p、60 分钟 1080p、10 分钟 4K 的耗时、峰值内存/显存、导出及首尾同步测试。
- [ ] 验证中文/日文真实语音准确率、复杂 VFR/旋转/延迟音轨和长文件同步，以及模型下载中断、GPU OOM 等错误提示；详见 `VALIDATION.md`。
