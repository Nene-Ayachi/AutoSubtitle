# 视频导出取消

## 原实现及最小修改

原导出经 media_service.run 使用 subprocess.run 同步等待 FFmpeg；Store 的单线程 ThreadPoolExecutor 统一处理识别和视频任务，已有独立视频任务 ID。输出采用随机文件名，但直接写入可下载位置，没有取消信号或可管理进程句柄。本次保留线程池、内存任务、识别、断句、编辑及 TXT/SRT 逻辑，只对视频分支增加控制对象、状态、临时发布与取消 UI。

## API

`POST /api/exports/{export_task_id}/cancel`：使用发起视频导出时返回的独立任务 ID，不能使用识别任务 ID。返回现有 TaskInfo，不等待编码器退出。

| 情况 | 返回 |
|---|---|
| 不存在的 ID | 404 |
| 识别任务 ID | 400，说明不是视频导出任务 |
| pending | 200 / cancelled，取消排队 Future，后台即使取到任务也不会启动编码 |
| processing 且 FFmpeg 尚未退出 | 200 / cancelling，后台执行停止和清理 |
| 启动进程前，尚无句柄 | 200 / cancelling，取消信号在创建进程前后均检查 |
| FFmpeg 已退出，正在验证或发布 | 200 / processing，stage=finalizing，保留成功/异常退出结果 |
| completed / failed / cancelled | 200，原终态不变 |
| cancelling | 200 / cancelling，重复请求安全 |
| 活动任务缺少控制信息 | 400，明确说明无法取消，不假装已经取消 |

`GET /api/tasks/{export_task_id}` 继续用于轮询；下载仍用 `GET /api/exports/{export_task_id}/content`，只有 completed 可以下载。取消不会修改识别任务的结果。

## 状态与竞态规则

正常路径：pending → processing → completed / failed。

取消路径：pending → cancelled；processing → cancelling → cancelled。

同一把 RLock 保护任务状态、取消接受和进程句柄。已经观察到的进程退出优先于后来的取消请求；取消先被接受则不会发布成功文件，即使 FFmpeg 收到 q 后以返回码 0 退出。取消请求只设置 Event，不执行耗时等待。控制对象在任务结束后释放。

临时文件清理重试后仍失败属于实际清理故障：status=failed、stage=cancel_cleanup_failed，error 提供残留路径；它不被伪装为普通编码错误，也不会宣称 cancelled 已完成清理。异常日志保留错误原因。已停止的进程不会因此重新启动，可重新导出，残留文件需按日志路径手工清理或在应用工作目录正常关闭时清理。

同一媒体在 cancelling 期间仍禁止发起同类视频任务；清理终态后允许立即重试。新任务 ID、新临时路径及新输出路径确保旧任务不会删除新导出的结果，重试读取当前已保存的校对字幕，不再调用 faster-whisper。

## FFmpeg 及文件生命周期

- 每个任务拥有自己的 Popen，shell=False；没有按名称结束 ffmpeg.exe 的操作。
- stdin 为 PIPE；优先发送 FFmpeg 的 q，等待 1.5 秒，再 terminate 等待 2 秒，最后 kill 等待 2 秒。Windows terminate 和 kill 均使用 TerminateProcess，不能当作不同强度的 POSIX 信号。
- 若强制终止也失败，保留该任务句柄、维持 cancelling，记录日志并重试；不会在进程仍活着时删除其文件或宣称取消成功。
- stdout 使用 DEVNULL，stderr 使用临时磁盘日志，避免未读取管道造成死锁；退出后 wait、关闭 stdin 和错误日志、清除控制对象引用。
- 直接启动静态 FFmpeg；编码器使用线程，当前方案不使用额外子进程或 shell，不需要进程树框架。未来若改用启动包装脚本，应重新验证。
- 写入 `媒体目录/exports/temp/{export_task_id}.mp4` 或 `.mkv`，字幕也使用同 ID 的 .srt。
- 返回码 0、文件非空且 FFprobe 确认有视频和有效媒体信息后，删除临时 SRT，并将视频在同一文件系统移动到 `exports/{export_task_id}.mp4` / `.mkv`。未发布文件不能下载。
- 取消/失败只清理该任务的临时视频和 SRT，进程退出后执行；删除失败最多重试三次，记录错误和路径，两个文件分别尝试清理。原媒体、识别字幕及其他导出文件不参与清理。

## 前端

视频等待/执行时显示取消按钮；点击立即禁用，接受取消后显示“正在取消导出……”，继续轮询直到 cancelled。随后显示“视频导出已取消”和“重新导出”，不清空编辑内容、不重新识别。旧轮询响应不能把 cancelling/终态退回 processing。既有进度条保持。TXT/SRT 按钮仍可使用。

浏览器关闭/刷新没有触发取消的事件处理；任务继续运行。应用后端正常关闭时会主动停止视频任务，再等待线程池退出和清理工作目录。这与关闭浏览器页面不同。

## 修改文件

- backend/app/services/video_process.py：新增独立进程控制、优雅退出、强制终止及日志资源释放。
- backend/app/services/export_service.py：Popen 导出、任务临时路径、结果验证、文件发布及清理。
- backend/app/core.py：仅视频任务保存控制对象，增加取消状态和幂等取消操作。
- backend/app/main.py：取消 API、向导出传递控制对象、服务正常关闭时停止视频任务。
- backend/app/schemas.py、frontend/src/types.ts：新增 cancelling/cancelled 类型。
- frontend/src/App.tsx：取消按钮、取消状态显示、继续轮询和重试。
- backend/tests/test_video_cancel.py：实际进程及竞态/异常测试；test_api.py、test_export.py 适配新导出调用。
- README.md、VALIDATION.md、本文件：功能说明和验证记录。

## 验证与限制

51 项 pytest 测试通过，前端 TypeScript/Vite 构建通过。新增测试覆盖真实 MP4/MKV 取消、进程退出和 stdin 关闭、临时文件删除、原文件完整性、编辑内容保留、TXT/SRT 不变、重新导出、重复取消、完成/异常退出竞态、排队取消、启动期间无句柄、terminate/kill 失败重试、删除失败及缺失控制信息。测试 fixture 和 finally 会停止其所属进程并关闭任务池。

既有真实集成 smoke.py 使用本地 small/int8 合成语音验证识别、编辑、TXT/SRT 与 H.264 CPU / H.264 NVENC / HEVC NVENC 正常导出，全部通过。

尚未实测：浏览器真实点击/关页的完整交互、NVENC 正在编码时取消、数小时/4K 大文件、实际 Windows 权限拒绝终止或永久锁定文件。终止和删除故障以受控模拟验证；真实取消使用小型视频和实际 FFmpeg。操作系统拒绝强制终止时任务可能长时间保持 cancelling，需用户在系统层面处理权限问题。后端崩溃/被强制结束后的进程恢复不在本次内存任务架构范围内。

复现：在现有 media-tool 环境、backend 目录执行 `python -m pytest -q`；frontend 执行 `npm run build`。无需新增依赖或修改 Conda/nvm。后端无热重载，重启后应用新接口；重启前导出尚未保存到文件的校对结果。
