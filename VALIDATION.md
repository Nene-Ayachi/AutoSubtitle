# 验证记录

## 当前 Windows 版本（2026-10-14 开始，跨日完成）

基线 `c96121c266f3fdd2a7567c8450268b8e851515a1` 的应用源码已在 Windows 11 build 26200 / RTX 5090 D v2（24455 MiB，驱动 617.42）完成原生构建、本机隔离运行及离线功能验证。本轮构建补充 CTranslate2 许可证，验证脚本增加 SHA256、迁移前数据保留及离线模型缓存保护检查。

- 依赖：Python 3.12.15；faster-whisper 1.2.1 / CTranslate2 4.6.2 / PyAV 16.0.1；httpx 0.28.1 + socksio 1.0.0；cuBLAS 12.8.4.1 / cuDNN 9.10.2.21；Node 24.14.1；FFmpeg 9.0.2。新增依赖后重新封装运行时，未沿用旧版本缓存；之后仅补许可证时复用本轮运行时。
- 回归：93 passed / 8 skipped；7 项为 macOS 专项，真实 CUDA 取消项另行启用后 1 passed。前端生产构建和开发/包内 `pip check` 通过。
- 实际成品：隔离 PATH/PYTHONPATH、中文空格路径解压、目录迁移后重建运行时、迁移前写入的数据和模型标记保留、HTTP/JS、端口冲突、重复启动、正常停止与 session 清理通过。实际 Start/Stop.cmd 及重启通过，未打开浏览器 UI。
- 使用已有测试模型缓存离线完成合成语音识别：9.702676 秒素材，small CPU/int8 耗时 1.582 秒、RTF 0.163；CUDA/float16 耗时 1.072 秒、RTF 0.110。耗时沿用应用指标，不包含模型加载/下载；只代表本机短合成素材。
- 字幕编辑、TXT/SRT、libx264 / h264_nvenc / hevc_nvenc MP4、MKV、视频取消与重试、原媒体/编辑结果保留通过。模型权重只在测试副本内使用，正式 ZIP 不含模型。
- ZIP：`release/MediaTool-Portable-Windows-x64.zip`，1,507,154,684 字节；SHA256 `f44351d5b254932d8e3844feaab727c225e1b8ef0e68ecd73c472aa70b20aa0b`。核对应用/前端字节、内嵌 runtime 哈希以及主要第三方许可证通过。

本次 `--download` 分别尝试 Xet 和普通 HTTP：配置/词表获取成功，权重传输未完成，随后停止测试。最终成功报告采用 `--model-cache` 且 `allow_download=false`，不能作为首次下载成功证据。干净机器、自动打开浏览器 UI 和目标笔记本性能尚未验收。

证据索引见 [DONE](docs/DONE.md)，剩余验收见 [TODO](docs/TODO.md)。最终详细报告为 `.test-work/portable-verification/report.json`；脱敏摘要为 `release/MediaTool-Portable-Windows-x64.validation.json`。

## 历史验证

日期：2026-10-08。开发机 Windows 11 / RTX 5090 D v2，24455 MiB 显存。**不代表 RTX 5060 Laptop 8GB 的性能结果。**

## 实际通过

全流程取消（2026-10-09）：常规测试 65 passed/1 GPU opt-in skipped；单独启用真实 GPU 取消测试通过。覆盖队列、模型准备、惰性 next 推理、字幕处理、结果发布竞态、流式上传断连/正常上传、真实 FFmpeg 音频提取中断、数据保留与重试。真实 RTX 5090 D v2 的 small/float16 在在途 Segment 推理期间取消，不继续下一段，不发布部分结果。正常 CPU/GPU 识别、编辑、TXT/SRT 和三种视频编码导出通过，前端构建通过。HF 实际长下载和浏览器大文件中点取消尚未实测；同步模型准备仅安全等待。详情见 [全流程取消说明](docs/TASK_CANCELLATION.md)。

Windows 便携版（2026-10-09）：生成 `release/MediaTool-Portable-Windows-x64.zip`，约 1.40 GiB，自带 Python 3.12.15、CPU/GPU 依赖、FFmpeg 和前端，无模型。对实际压缩包执行隔离验证，清除开发环境 PATH/PYTHONPATH：中文/空格路径首次初始化、已初始化目录移动后重建运行时、模型目录保留、端口冲突回退、重复启动、静态首页/JS、真实 CPU/CUDA small 识别、校对、TXT/SRT、三种 MP4 编码、MKV 封装、取消/重试、正常退出和 session 清理均通过。51 项回归测试及前端构建通过。测试 small 只下载在隔离验证目录，项目 models 和发布包不含测试权重。报告位于 `.test-work/portable-verification/report.json`，说明见 [便携版构建与验证](docs/PORTABLE_BUILD.md)。尚未在另一台干净 Windows 电脑/虚拟机验收，也未测试自动打开浏览器的 UI 点击流程。

视频导出取消：全部 51 项测试通过，含真实 FFmpeg 的 MP4/MKV 取消、进程退出、临时文件清理、原视频/校对字幕/TXT/SRT 保留、重新导出、排队取消和重复取消，以及完成/失败竞态、强制终止故障及清理故障的受控测试。前端构建通过，真实 CPU 识别/编辑及三种 MP4 编码导出集成再次通过。浏览器点击流程、NVENC 运行中取消和实际 Windows 权限故障尚未实测，详见 [视频取消说明](docs/VIDEO_EXPORT_CANCEL.md)。

字幕语义断句优化：全部 38 项测试通过，覆盖长句无标点、连续短句、中文搭配和数量词、日文助词和谓语、英文介词、中日英混合、极短尾句、停顿与标点冲突、接近长度限制、TXT 完整性及异常时间戳回退。API 验证同一次识别可重复切分且不再次调用模型，人工编辑后拒绝覆盖。前端构建通过。使用已有 small/int8 模型再次执行真实 CPU 识别、字幕编辑、TXT/SRT 和三种 MP4 编码导出，全部通过；未修改开发环境或新增依赖。六组可复现的合成词时间戳新旧对比见 [字幕断句说明](docs/SUBTITLE_SPLITTING.md)，不代表真实中文/日文语音准确率验收。

新增外挂字幕导出验证：全部 19 项测试通过。实际 FFmpeg 将带两条 AAC 音轨的 H.264 MP4 封装为 MKV；FFprobe 验证视频和两条音轨的逐包 SHA256 与源文件完全相同，确认无转码。独立 SubRip 字幕轨道包含编辑后的中日韩文本，临时字幕和失败的半成品正确清理；API 返回 MKV 格式及正确下载文件名、MIME。前端构建通过。

- 使用已有 Miniforge 创建独立 `media-tool`，Python 3.12.15；没有升级 base 或删除其他环境。
- 使用已有 nvm/Node 24；npm 安装生成 package-lock，安装时审计报告 0 vulnerabilities。
- Python 依赖 `pip check` 无冲突；固定 faster-whisper 1.2.1、CTranslate2 4.6.2、PyAV 16.0.1。
- NVIDIA Windows wheels：cuBLAS 12.8.4.1、cuDNN 9.10.2.21；只注册当前后端进程的 DLL 搜索路径。
- 项目 `.tools` 内 Gyan FFmpeg 9.0.2 essentials，下载 SHA256 校验成功；支持 libass、libx264、H.264/HEVC NVENC。
- `python -m pytest -q`：17 passed，含时间转换、中日韩 TXT、SRT、词切分、编辑同步、参数校验、重复任务、失败状态、分块、模型复用和推理失败释放；1 个上游 Starlette/AnyIO 弃用警告，不影响结果。
- `npm run build`：TypeScript 严格检查与 Vite 生产构建成功；主包约 505 kB，存在构建体积提示。
- 真实 CPU small/int8 识别英文合成语音，成功生成识别结果、编辑后的 TXT/SRT、H.264 MP4。
- 真实 CUDA small/float16 识别同一语音，完整 API 链路和 H.264 CPU / H.264 NVENC / HEVC NVENC 三种导出通过。测试源为约 9.7 秒、1920×1080/30fps 视频，文件名含中文、空格和方括号。
- 导出保持 1920×1080，FFprobe 验证时长差小于 0.5 秒且有音轨；NVENC 输出抽帧确认中文、日文、英文字幕字形和白字黑描边。
- 浏览器实际导入、默认自动语言/设备识别、字幕列表显示、编辑保存、纯文本同步、TXT 下载、NVENC MP4 导出完成，无浏览器 error/warn 日志。

机器生成测试数据保存在 Git 忽略的 `.test-work` 中：`validation-cuda.json`、`result-cuda.txt/.srt`、三种编码的 MP4、`subtitle-frame.png`、`ui-proof.jpg`。它们是合成测试媒体，非用户私有媒体。

## 已处理的兼容问题

1. PyAV 19.0.1 删除了 faster-whisper 1.2.1 使用的 `metadata_errors` 参数。真实解码失败后固定到 16.0.1，链路验证通过。
2. 当前 CTranslate2 在此 RTX 5090 D v2 上报告 CUDA 精度只有 float16/float32/bfloat16，未报告 int8/int8_float16。自动精度选择 float16，并在结果提示与日志中说明；显式不支持的精度报错。均衡模式模型保持 turbo，不静默改成 small。
3. Conda 默认选择的 FFmpeg 4.3.1 在 RTX 50 上 NVENC 旧预设初始化失败。尝试 Conda 7.1.1 时 gdk-pixbuf 安装脚本错误并回滚，最终改为项目内独立构建。
4. RTX 50 NVENC 不接受 128×128 探测帧，改用 640×360 后两种 NVENC 实际探测和导出成功。
5. React 任务轮询在终态切换时必须先获取识别结果，再更新任务终态，避免 effect 清理丢掉结果；浏览器端已验证。

## 文档支持但尚未实测

- medium、large-v3-turbo、large-v3 模型下载与识别；已实现参数和按需加载，仅 small 模型已实际下载/运行。
- 中文、日文真实语音的识别准确率（编码、字幕渲染及编辑文本已验证）。
- 复杂 VFR、延迟音轨、不规则时间戳、旋转、超长文件等输入上的音画同步；普通测试媒体仅检查时长和音轨，不能代表完整主观同步验收。
- 不同 MKV/MOV/MP3/M4A 编码组合、罕见损坏媒体，以及断网下载、真实 GPU OOM 的提示。

## 目标设备待验证

必须在 RTX 5060 Laptop 8GB 上分别测试 10 分钟 1080p、60 分钟 1080p、10 分钟 4K，记录模型、精度、峰值内存/显存、实际识别耗时/RTF、NVENC 导出与首尾同步。开发机短片结果不能用于预估这些测试的速度或显存。

## 复现真实短片集成测试

先在项目根目录用 PowerShell 生成非用户语音素材：

```powershell
New-Item -ItemType Directory -Path .test-work -Force
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice.SetOutputToWaveFile((Join-Path (Get-Location) '.test-work\speech.wav'))
$voice.Speak('Hello, welcome to Media Tool. This is a local speech transcription test. We can edit subtitles and export plain text.')
$voice.Dispose()
conda activate media-tool
cd backend
# 已缓存 small，无额外下载。首次没有缓存时显式加 --download。
python smoke.py --device cpu
python smoke.py --device cuda
```

此手动测试使用真实依赖，不属于 pytest 默认自动测试；请先安装 FFmpeg/NVIDIA 运行库。
