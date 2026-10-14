# Media Tool

新增 Apple Silicon macOS 源码安装支持：首次运行 `bash Setup-MediaTool.command`，之后双击 `Start-MediaTool.command`。使用原生 ARM CPU 识别，并支持探测可用的 VideoToolbox 视频编码；不依赖 Miniforge/nvm。安装、限制及 Mac 实机验证清单见 [macOS 说明](docs/MACOS.md)。目前尚未发布独立 macOS 便携包。

上传、排队、音频提取、识别、字幕生成和视频导出支持主动取消；模型下载/加载及当前 GPU 步骤采用安全等待，不假装立即终止。统一 API、阶段限制和验证见 [全流程取消说明](docs/TASK_CANCELLATION.md)。

已有 Windows x64 便携版：解压 `releases/MediaTool-Portable-Windows-x64.zip` 后双击 `Start-MediaTool.cmd`，无需安装 Miniforge、Python、Node/nvm 或 FFmpeg。默认包不含模型，首次识别联网下载。使用方式见 [便携版说明](docs/PORTABLE_QUICKSTART.md)，重新制包及验证见 [构建说明](docs/PORTABLE_BUILD.md)。

视频导出支持主动取消：导出时点击“取消导出”，等待进程退出和临时文件清理后可重新导出，字幕校对内容保持。MP4 烧录和 MKV 外挂封装共用此机制。API、状态和测试详情见 [视频导出取消说明](docs/VIDEO_EXPORT_CANCEL.md)。

Windows 本地 AI 字幕与转写工具。导入音视频 → 本地 faster-whisper → 编辑字幕 → TXT / SRT / 烧录 MP4。无账号、数据库、云端 AI 或收费 API。

## 目录与设计

- `frontend/`：React 19、TypeScript 严格模式、Vite、MUI；HTTP 轮询、播放器、字幕编辑、纯文本预览。
- `backend/app/main.py`：FastAPI API 与上传、下载；`schemas.py` 参数校验；`config.py` 集中配置。
- `backend/app/services/`：媒体探测、硬件检测、推理、字幕规则和视频导出。
- `backend/app/core.py`：内存任务状态和单工作线程，不启用多进程。
- `backend/tests/`：文本、时间轴、切分、任务和编辑导出的测试。
- `scripts/`：PowerShell 启动入口。

上传文件保存在 `%LOCALAPPDATA%/media-tool/session-*`；模型缓存默认保存在项目根目录的 `models/`（本项目为 `F:\projects\AutoSubtitle\models`），已加入 Git 忽略。路径根据 config.py 所在位置确定，不受启动时工作目录影响；可通过 `MEDIA_TOOL_MODELS` 显式覆盖。正常关闭会清理本次媒体与导出文件，模型保留；异常退出遗留 session 目录可在应用关闭后手动删除。重启不会恢复任务或编辑结果，关闭前请导出文件。

每个字幕包含 `id/start/end/text/group`，group 保留原始识别片段的段落归属。编辑文本影响所有导出；修改时间轴不改变纯文本。TXT 不按显示字幕长度换行。词时间戳有效时优先切分，无效时保留原片段边界；不按字符平均分配时间。为限制长音频内存，按 60 秒窗口提取单声道 16 kHz 音频并顺序识别，边界处可能截断单词或句子，需要校对。

## 环境安装（PowerShell）

使用已有 Miniforge 和 nvm，不升级 base 或其他项目环境。先检查：

```powershell
conda --version
conda env list
nvm list
nvm use 24
node --version
npm --version
```

若 nvm 必须完整版本号，选择 `nvm list` 中已有的 24.x 版本。不删除 Node 18。`.nvmrc` 仅作记录，nvm-windows 仍需显式切换。

```powershell
# 环境已存在时跳过 create，先检查版本，不能删除重建。
conda create -n media-tool python=3.12 -y
conda activate media-tool
python --version
python -m pip install -r backend/requirements.txt
cd frontend
npm install
cd ..
```

若 PowerShell 中 activate 不可用，可在本次会话加载 hook（不修改 profile 或系统 PATH）：

```powershell
(& conda 'shell.powershell' 'hook') | Out-String | Invoke-Expression
conda activate media-tool
```

也可使用 `conda run -n media-tool ...`。所有 Python 命令必须在此环境执行。

### FFmpeg

需要同时有 FFmpeg、FFprobe，以及 libass 字幕滤镜、libx264。推荐使用项目内独立构建，避免旧 Conda 的 FFmpeg 版本和 DLL 脚本兼容问题：

```powershell
.\scripts\install-ffmpeg.ps1
.\.tools\ffmpeg\bin\ffmpeg.exe -version
.\.tools\ffmpeg\bin\ffprobe.exe -version
.\.tools\ffmpeg\bin\ffmpeg.exe -filters | Select-String subtitles
.\.tools\ffmpeg\bin\ffmpeg.exe -encoders | Select-String 'libx264|nvenc'
```

脚本下载 [FFmpeg 官网链接的 Gyan Windows essentials 构建](https://ffmpeg.org/download.html#build-windows)，校验其发布的 SHA256，保存在 `.tools/ffmpeg/bin`（Git 忽略）。后端自动使用该路径，无需修改系统 PATH。已有独立 FFmpeg 可通过 `MEDIA_TOOL_FFMPEG` / `MEDIA_TOOL_FFPROBE` 指定绝对路径。如果偏好 Conda，可尝试 `conda install -n media-tool -c conda-forge 'ffmpeg>=7.1,<8' -y`；本机旧 Conda 的 gdk-pixbuf post-link 出错导致该路径回滚，不建议使用未指定版本而自动选中的 4.3.1（RTX 50 NVENC 初始化失败）。

### RTX 50 / CUDA

固定 faster-whisper 1.2.1 + CTranslate2 4.6.2，避免未经验证自动升级。该组合要求 CUDA 12 的 cuBLAS 和 cuDNN 9；RTX 50 系列应使用支持 Blackwell 的较新 CUDA 12 运行库（12.8 或更新），不要套用旧 CUDA 11 的降级方案。GPU 驱动和 `nvidia-smi` 的 CUDA 数字不等同于已安装运行库。

参考 [faster-whisper 官方 GPU 要求](https://github.com/SYSTRAN/faster-whisper#gpu) 和 [CTranslate2 发布记录](https://github.com/OpenNMT/CTranslate2/releases)。本项目在 Windows 中采用官方 NVIDIA wheels 安装到独立环境（不覆盖系统 CUDA），应用只为自身进程注册 DLL 搜索目录：

```powershell
conda activate media-tool
python -m pip install nvidia-cublas-cu12==12.8.4.1 nvidia-cudnn-cu12==9.10.2.21
cd backend
python -c "import app; import ctranslate2 as ct; print(ct.__version__); print(ct.get_cuda_device_count()); print(ct.get_supported_compute_types('cuda'))"
```

最终必须实际识别验证 cuBLAS/cuDNN 和模型兼容性。检测精度成功并不保证模型运行成功；加载失败会报告错误，不静默切换模型。无 CUDA 可选 CPU + int8。NVENC 通过实际编码单帧探测，不只检查编码器列表。

默认均衡 large-v3-turbo/int8_float16，CPU 自动使用 int8；快速 small/int8；高质量 large-v3/float16。若自动精度的预设不受运行时支持，会选择实际支持的精度，并在日志及识别完成信息中提示，模型保持不变。手动选择不支持的精度则报错。一个模型、一项任务、不使用批量推理。首次使用所选模型需勾选允许下载，下载后可以离线处理；启动不下载模型。PyAV 固定 16.0.1，以避免新版本音频解码 API 与 faster-whisper 1.2.1 不兼容。

## 启动

打开两个 PowerShell 窗口，在项目根目录执行：

```powershell
# 窗口 1
conda activate media-tool
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

```powershell
# 窗口 2
nvm use 24
cd frontend
npm run dev
```

访问 http://127.0.0.1:5173；API 文档 http://127.0.0.1:8000/docs。也可使用 `scripts/start-backend.ps1` 和 `scripts/start-frontend.ps1`。不使用 uvicorn reload 或多 worker，以免重复加载模型。

## 操作与测试

1. 导入 MP4/MKV/MOV/MP3/WAV/M4A。扩展名筛选后以 FFprobe 验证音轨和时长。
2. 选择质量、语言、设备；高级设置可调整模型、精度、Beam Size、VAD、词时间戳。
3. 首次勾选所选模型下载，开始识别；查看实际阶段和已处理的音频范围。
4. 在字幕页修改文本与开始/结束秒数，点击时间跳转，播放时查看字幕叠加与高亮。
5. 保存修改（导出时也自动保存）；非法时间、重叠、空文本会报错。
6. 纯文本页查看和复制全文；TXT、SRT 导出不会重新识别。
7. 在“字幕方式”中选择：烧录字幕（MP4），使用 CPU H.264 或可用 NVENC；或外挂字幕封装（MKV，无转码），将字幕作为可开关的软字幕轨道封装进文件。完成后下载视频。失败仍可导出 TXT/SRT。

外挂字幕封装直接复制原视频和全部音轨，保留章节及容器元数据，不使用视频编码器、不做 HDR 色调转换。已有字幕轨道不会复制，新增字幕来自当前编辑数据。MKV 中字幕是否显示由播放器控制，可使用支持 MKV/SRT 的播放器。若某种原始编码无法封装进 MKV，会明确报错，不自动转码；普通 SRT 文件仍可单独导出。

```powershell
conda activate media-tool
cd backend
python -m pytest -q
cd ../frontend
npm run build
```

手动集成测试使用真实 1080p MP4：CUDA 识别 → 编辑 → TXT/SRT → 烧录 MP4 → 核对中日韩字形、首尾音画同步、旋转方向、分辨率、帧率。必须另外在 RTX 5060 Laptop 8GB 上验证 10 分钟 1080p、60 分钟 1080p、10 分钟 4K；5090 的结果不能代表目标笔记本。

## 配置与限制

环境变量：`MEDIA_TOOL_DATA`、`MEDIA_TOOL_MODELS`、`MEDIA_TOOL_FFMPEG`、`MEDIA_TOOL_FFPROBE`、`MEDIA_TOOL_FONT`；字幕切分和窗口参数位于 config.py。默认烧录字体 Microsoft YaHei，Windows 应存在该字体；日文可设置为支持日语的安装字体，如 Yu Gothic。请检查最终导出字形。

媒体上传需要额外磁盘空间。保留原分辨率和由 FFmpeg 自动处理的旋转，音轨重新编码 AAC；不保证原编码字节或所有附加音轨保留。不支持 HDR 烧录，会明确拒绝。浏览器是否能播放 MKV/MOV 取决于编码；识别/文本导出不依赖浏览器解码，预览不支持时可先转为 H.264 MP4。视频下载通过浏览器处理同名文件，不覆盖服务器原始媒体。长任务暂不提供取消，退出时等待工作线程完成。

暂无历史保存、批处理、说话人分离、翻译、总结、桌面打包。本地绑定和有限 CORS 不提供远程访问或账户鉴权；不应映射到公网。

## 实测记录

见 [VALIDATION.md](VALIDATION.md)，严格区分自动化测试、真实编码/识别验证与目标硬件尚待测试项。

字幕断句现在使用语言规则与候选评分的动态规划，参数位于 `config.py` 的 `SUBTITLE_POLICIES`，不增加 NLP/LLM 依赖。原始片段和词时间戳保留在任务内存中，可以调用 `POST /api/tasks/{task_id}/subtitles/resplit` 无需重新识别地切分；人工编辑后拒绝覆盖。算法说明、回退策略、语言参数和六组实际新旧输出见 [字幕断句对比](docs/SUBTITLE_SPLITTING.md)。模型/VAD/词时间戳参数没有改变。
