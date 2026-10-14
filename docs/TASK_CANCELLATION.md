# 全流程任务取消

## 原实现与修改范围

Store 的单线程 ThreadPoolExecutor 执行识别和独立视频导出。识别按 60 秒窗口调用 FFmpeg，再使用 faster-whisper 的惰性 Segment 迭代；不批量推理，word_timestamps 默认开启，实际工作不占 FastAPI 事件循环。原来只有视频任务保存进程句柄和取消事件；音频提取为 subprocess.run，模型构造与下一 Segment 获取均为同步调用。

本次复用已有控制对象，扩展为每个任务独立 Event、状态锁、Future 及进程句柄。没有改变模型策略、VAD、词时间戳配置、字幕评分/时间轴算法或 TXT/SRT 拼接规则；字幕函数只增加可选取消检查点。

## API 与状态

- `POST /api/tasks/{task_id}/cancel`：统一取消识别或视频导出，返回 TaskInfo，不等待操作停止。
- 原 `POST /api/exports/{export_task_id}/cancel` 保留兼容，并仍验证这是视频任务。
- `GET /api/tasks/{task_id}`：持续轮询，直到 cancelled/completed/failed。
- 新 `POST /api/media/upload?filename=...`：直接上传文件字节，不使用 multipart，前端用 AbortController 中止。旧 multipart 上传入口保留兼容。

不存在任务返回 404；重复取消及已完成/失败/取消任务返回原状态，终态不被改写。pending 取消可取消 Future 并立即进入 cancelled；运行中的任务进入 cancelling，真正退出并清理后才进入 cancelled。

识别结果发布与取消接受使用同一 RLock。结果发布先取得锁则 completed 保持；取消先接受则检查点/最终提交检查丢弃本次未完成结果。FFmpeg 视频导出保留原竞态规则：已经观察到编码器退出优先于后来的取消，验证发布阶段返回 processing/finalizing。音频提取的进程退出不代表整个识别完成，不会阻止后续阶段取消。

## 各阶段机制与响应限制

| 阶段 | 实际行为 |
|---|---|
| 文件上传 | 前端 abort HTTP 请求，流式入口从第一字节拥有临时文件；断连异常关闭文件并删除不完整目录。完整发布的媒体保留。 |
| 上传后的媒体解析 | 独立控制对象管理 FFprobe；断连监测请求停止，等待子进程退出再清理。30 秒超时仍保留。 |
| 队列等待 | 取消排队 Future；即使被线程池取到，也检查状态而不启动处理。 |
| 硬件能力检查 | 使用已有较短/缓存的检测，返回后检查标志；首次检测中的短探测没有变成复杂子任务。 |
| 模型下载/加载 | 同步 WhisperModel/Hugging Face 调用安全返回后检查；不能立即杀 Python 线程或强制卸载正在使用的模型。UI 显示 cancel_wait_model。 |
| FFmpeg 音频提取 | 复用已有 Popen 控制，q 正常退出，超时后 terminate/kill，并 wait 真实退出。 |
| 音频解码/VAD/语言检测 | model.transcribe 调用前后检查；同步原生步骤需要返回后才能响应。 |
| 惰性 Segment 推理 | 每次 next 前和获取结果后检查；当前 GPU/CPU 步骤不会被强杀，完成后不处理该 Segment，也不继续后续迭代。UI 显示 cancel_wait_inference。 |
| 字幕生成 | 进入/完成时检查，每个原 Segment 与动态规划外层循环检查。不发布部分字幕。 |
| MP4/MKV 导出 | 独立导出任务停止自己的 FFmpeg，保留识别及校对内容，清理独立临时输出，允许重新导出。 |

同步 HF 下载没有稳定的直接取消接口，本阶段不终止已经在下载的字节流，也不删除其缓存。取消后可能继续下载到返回或超时/错误，期间真实保持 cancelling；下载完成的完整缓存保留，但不再执行音频提取、推理或字幕生成。模型构造、当前推理、首次硬件探测的取消延迟取决于当前调用耗时，不承诺秒级取消。GPU 利用率也不会在点击瞬间强制降为零。

FFmpeg 日志用磁盘临时文件，不存在未读取 PIPE 导致的阻塞；仅停止当前任务的句柄，Windows terminate 与 kill 均为 TerminateProcess。若操作系统一直拒绝强制终止，保留句柄并重试，状态继续 cancelling，不误报已经停止。

## 文件与结果保护

- 识别临时音频：`媒体目录/work/{task_id}/audio-chunk.wav`，关闭生成器后清理音频及该任务目录。
- 视频临时字幕/视频：原有 `exports/temp/{export_task_id}.srt/.mp4/.mkv`，进程退出后清理，成功验证才发布。
- 未完成流式上传：该次 UUID 目录独立清理；原始用户文件不被访问或删除。
- 已上传原媒体、此前完成的识别/编辑结果、正式导出和完整模型缓存保留。
- 识别取消后在工作线程中关闭迭代器、卸载当前模型引用；不在 API 线程并发强制卸载 GPU 模型。
- 删除失败记录具体路径；识别/视频清理故障以 failed 和 cancel_cleanup_failed 明确呈现，不能声称 cancelled 已成功清理。上传无任务 ID，残留路径记录在日志中。

同媒体 cancelling 时不允许开始同类新任务；真正终态后可重试。每次事件、任务 ID 和临时目录独立。前端分开保存正在执行的 task 与已完成结果的 resultTaskId，取消新的识别不会清空之前的字幕或把 TXT/SRT 导出指向取消的任务。

## 前端

上传期间显示“取消上传”；点击开始处理后立即显示“取消处理”，即使 POST 尚未返回 ID，也会记录取消意图，取得 ID 后请求后端取消。不能中止任务创建 POST 后假装服务器没有创建任务。

点击后禁用重复提交；cancelling 继续轮询。模型准备/推理阶段显示真实等待原因，cancelled 后显示“处理已取消”和“重新开始”。过期轮询只能更新同 ID，不能回退取消状态或覆盖新任务。导出仍有独立取消按钮及重新导出。关闭浏览器不主动取消已经创建的后台任务。

上传尚无任务 ID：显示客户端上传已中止和服务器将清理不完整文件，不能宣称所有后台资源已经即时释放。断连恰好发生在完整媒体发布之后时，该媒体可能保留到 session 清理；保留完整上传符合原数据保护规则。

## 修改文件

- backend/app/core.py：统一控制注册、原子结果发布、状态和幂等取消。
- backend/app/main.py：统一 API、流式上传/断连、正常关闭时请求取消全部任务。
- backend/app/services/video_process.py：控制对象复用、音频操作不封闭后续取消、FFprobe stdout/超时。
- backend/app/services/media_service.py：托管音频提取和媒体解析。
- backend/app/services/transcription_service.py：协作式模型准备/推理取消、独立工作目录及资源清理。
- backend/app/services/subtitle_service.py：仅新增可选检查点，不改变切分规则。
- frontend/src/App.tsx：上传中止、全过程取消、任务创建阶段取消意图、旧结果保护。
- backend/tests/test_task_cancel.py：新增阶段/竞态/上传/真实 FFmpeg/GPU 测试；test_api.py、test_transcription.py 适配可选控制参数。
- README.md、VALIDATION.md、PORTABLE_QUICKSTART.md 和本说明；便携 zip 与 SHA256 同步更新。

## 测试与尚未解决的边界

常规 `python -m pytest -q`：65 passed，1 个需显式启用的 GPU 测试 skipped。单独启用后真实 GPU 测试通过：使用 RTX 5090 D v2、small/float16 和合成语音，在 next 惰性推理开始后取消，只返回一个原生 Segment，不继续下一段，不发布结果，临时音频清理且原媒体保留。不能代表所有显卡或长素材的取消延迟。

受控测试覆盖模型准备、同步 transcribe 前置操作、next 在途步骤、字幕生成、模型准备期间异常、原子提交竞态、排队取消、重试和独立事件、上传传输/解析断连及缓存保护。真实 FFmpeg 音频取消、既有 MP4/MKV 取消及正常导出回归通过。正常 CPU/GPU small 识别→编辑→TXT/SRT→三种 MP4 编码集成通过，前端生产构建通过。测试自身负责终止其进程和线程池。

尚未实测浏览器大文件实际上传中点取消、真实长时间 HF 下载中途取消、其他 GPU/超长素材响应时间；上传断连和模型准备使用可控替身验证。同步 HF 下载继续等待是明确限制；如未来必须立即停止，需要评估单独可终止的下载/推理进程，本次未引入。进程崩溃后的持久恢复不在现有内存任务架构范围内。
