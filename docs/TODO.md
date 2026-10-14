# 待办事项

更新日期：2026-10-14。构建步骤见 [PORTABLE_BUILD.md](PORTABLE_BUILD.md)，完成后将证据补入 [DONE.md](DONE.md)。

## Windows 当前版本成品构建与验证

- [x] 在 Windows x64 拉取当前工程，核对 Python 3.12/Conda、Node 24、FFmpeg、CUDA 运行库和 conda-pack；补齐最新 socksio 依赖。
- [x] 不复用旧运行时缓存，构建 `release/MediaTool-Portable-Windows-x64.zip` 和 `.zip.sha256`；核对哈希及许可证，补齐 CTranslate2 wheel 缺少的 MIT 正文。
- [x] 执行 `--skip-inference`，验证中文/空格路径、迁移后运行时初始化、模型/数据保留、HTTP/JS、端口冲突、重复启动与停止。
- [x] 使用合成语音和已有完整 small 缓存执行 `--model-cache` 离线完整验证；CPU/CUDA 识别、字幕编辑、TXT/SRT、三种 MP4 编码、MKV、取消和重试通过。实际 Start/Stop.cmd 及重启通过，真实 CUDA 推理取消测试通过。
- [ ] 完成当前 Windows 包首次联网模型下载验收。本轮 `--download` 的 Xet 与禁用 Xet 的 HTTP 两条路径均停在权重传输阶段；配置/词表可下载不能代表完整权重下载成功。需在可用网络重试并保留报告，不能以离线缓存验收替代。
- [ ] 在未安装 Python、Node、Conda、FFmpeg 的干净 Windows 机器上解压运行，验收双击启动、浏览器打开、首次模型下载、停止和重启；确认不依赖构建机路径。
- [x] 保存基线提交号、系统/GPU、依赖版本、ZIP SHA256、测试结果及 `.test-work/portable-verification/report.json`；公开摘要见 DONE 和 VALIDATION，机器可读摘要见 `release/MediaTool-Portable-Windows-x64.validation.json`。

当前版本原生构建和本机隔离/离线功能验收已通过；首次联网下载、干净机器/自动打开浏览器 UI 仍待完成。历史成品或 macOS 模拟组装不能代替这些未完成项目。

## macOS 后续验收

- [ ] 完整下载所选 MLX 模型，验证真实 Metal 语音识别、字幕编辑、导出、取消和重试；目前仅验证依赖、Metal 探测和非模型导出流程。
- [ ] 在干净 Apple Silicon Mac 和 macOS 14 目标系统验收；记录从实际下载 ZIP 开始的隔离提示、信任流程及启动情况。
- [ ] 验证无代理、HTTP/SOCKS 代理、断网和失败重试下的完整模型下载；明确系统静态代理与 PAC 的支持范围。
- [ ] 若未来取得 Apple Developer Program 会员及 Developer ID 证书，再实施签名和公证；当前不具备条件，不宣称免提示或已公证。

## 其他已有验证缺口

- [ ] 在 RTX 5060 Laptop 8GB 上完成 10 分钟 1080p、60 分钟 1080p、10 分钟 4K 的耗时、峰值内存/显存、导出及首尾同步测试。
- [ ] 验证中文/日文真实语音准确率、复杂 VFR/旋转/延迟音轨和长文件同步，以及模型下载中断、GPU OOM 等错误提示；详见 `VALIDATION.md`。
