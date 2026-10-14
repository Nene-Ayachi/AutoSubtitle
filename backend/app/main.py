import logging
import shutil
import tempfile
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from app.config import DATA, WEB
from app.core import store
from app.schemas import TranscriptionRequest, EditRequest, ExportRequest, MediaInfo, TaskInfo, TranscriptionResult
from app.services import media_service, hardware_service, subtitle_service, export_service
from app.services.video_process import TaskControl, TaskCancelledError

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

@asynccontextmanager
async def lifespan(app):
    DATA.mkdir(parents=True, exist_ok=True)
    app.state.workspace = Path(tempfile.mkdtemp(prefix='session-', dir=DATA))
    yield
    for task_id in list(store.controls):
        store.cancel_task(task_id)
    await run_in_threadpool(store.pool.shutdown, wait=True)
    store.ai.unload()
    try:
        shutil.rmtree(app.state.workspace)
    except OSError:
        logging.exception('临时目录清理失败')

app = FastAPI(title='Media Tool', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5173', 'http://localhost:5173'], allow_methods=['GET', 'POST', 'PUT'], allow_headers=['Content-Type'])

@app.exception_handler(ValueError)
async def value_error(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={'detail': str(exc)})

def media_by_id(media_id):
    if media_id not in store.media:
        raise HTTPException(404, '媒体不存在')
    return store.media[media_id]

def task_by_id(task_id):
    if task_id not in store.tasks:
        raise HTTPException(404, '任务不存在')
    return store.tasks[task_id]

def result_by_id(task_id):
    task = task_by_id(task_id)
    if task['kind'] != 'transcription' or task['status'] != 'completed':
        raise HTTPException(409, '识别结果尚未完成')
    return task['result']

def public_media(media):
    return {k: v for k, v in media.items() if k != 'path'}

@app.get('/api/system/info')
def system_info():
    return hardware_service.info()

@app.post('/api/media', status_code=201, response_model=MediaInfo)
async def upload(file: UploadFile):
    name = (file.filename or 'media').replace('\\', '/').split('/')[-1]
    suffix = Path(name).suffix.lower()
    if suffix not in ('.mp4', '.mkv', '.mov', '.mp3', '.wav', '.m4a'):
        raise ValueError('支持 MP4/MKV/MOV/MP3/WAV/M4A')
    media_id = uuid4().hex
    directory = app.state.workspace / media_id
    directory.mkdir()
    path = directory / ('input' + suffix)
    try:
        with path.open('wb') as output:
            while chunk := await file.read(1024 * 1024):
                await run_in_threadpool(output.write, chunk)
        info = await run_in_threadpool(media_service.probe, path)
        media = {'id': media_id, 'name': name, 'size': path.stat().st_size, 'path': path, **info}
        store.media[media_id] = media
        return public_media(media)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        await file.close()

@app.get('/api/media/{media_id}', response_model=MediaInfo)
def get_media(media_id: str):
    return public_media(media_by_id(media_id))

@app.post('/api/media/upload', status_code=201, response_model=MediaInfo)
async def streaming_upload(request: Request, filename: str):
    # Raw streaming bypasses multipart's pre-handler spool; disconnect cleanup
    # now owns the partial file from the first incoming byte.
    name = filename.replace('\\', '/').split('/')[-1]
    suffix = Path(name).suffix.lower()
    if suffix not in ('.mp4', '.mkv', '.mov', '.mp3', '.wav', '.m4a'):
        raise ValueError('支持 MP4/MKV/MOV/MP3/WAV/M4A')
    media_id = uuid4().hex
    directory = app.state.workspace / media_id
    directory.mkdir()
    path = directory / ('input' + suffix)
    control = TaskControl(media_id, seal_on_process_exit=False)
    watcher = None
    async def watch_disconnect():
        while True:
            if await request.is_disconnected():
                control.request_cancel()
                return
            await asyncio.sleep(.1)
    try:
        with path.open('wb') as output:
            async for chunk in request.stream():
                await run_in_threadpool(output.write, chunk)
        if await request.is_disconnected():
            raise TaskCancelledError()
        watcher = asyncio.create_task(watch_disconnect())
        info = await run_in_threadpool(media_service.probe, path, control)
        control.check()
        if await request.is_disconnected():
            raise TaskCancelledError()
        media = {'id': media_id, 'name': name, 'size': path.stat().st_size, 'path': path, **info}
        with store.lock:
            store.media[media_id] = media
        return public_media(media)
    except BaseException as exc:
        control.request_cancel()
        try:
            shutil.rmtree(directory)
        except OSError:
            logging.exception('上传临时文件清理失败：%s', directory)
        if isinstance(exc, (TaskCancelledError, ClientDisconnect)):
            raise HTTPException(499, '上传已取消') from None
        raise
    finally:
        if watcher:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass

@app.get('/api/media/{media_id}/content')
def media_content(media_id: str):
    media = media_by_id(media_id)
    return FileResponse(media['path'])

@app.post('/api/tasks/transcription', status_code=202, response_model=TaskInfo)
def transcription(request: TranscriptionRequest):
    media = media_by_id(request.media_id)
    return store.submit('transcription', media['id'], lambda update, control: store.ai.transcribe(media, request, update, control=control), controlled=True)

@app.post('/api/tasks/{task_id}/cancel', response_model=TaskInfo)
def cancel_task(task_id: str):
    with store.lock:
        task_by_id(task_id)
        return store.cancel_task(task_id)

@app.get('/api/tasks/{task_id}', response_model=TaskInfo)
def task_status(task_id: str):
    with store.lock:
        task = task_by_id(task_id)
        response = {k: v for k, v in task.items() if k != 'result'}
        if task['kind'] == 'video' and task['status'] == 'completed':
            response['output_format'] = task['result'].suffix.lstrip('.')
        return response

@app.get('/api/tasks/{task_id}/result', response_model=TranscriptionResult)
def result(task_id: str):
    with store.lock:
        data = result_by_id(task_id)
        return {**data, 'text': subtitle_service.txt(data['cues'])}

@app.put('/api/tasks/{task_id}/subtitles', response_model=TranscriptionResult)
def edit(task_id: str, request: EditRequest):
    with store.lock:
        data = result_by_id(task_id)
        subtitle_service.validate(request.cues, media_by_id(task_by_id(task_id)['media_id'])['duration'])
        # Keep paragraph identity attached to the original cue, independent of timestamps.
        original = {c.id: c for c in data['cues']}
        if set(original) != {c.id for c in request.cues} or len(original) != len(request.cues):
            raise ValueError('本阶段只支持编辑现有字幕')
        for cue in request.cues:
            cue.group = original[cue.id].group
            cue.join_before = original[cue.id].join_before
        data['_edited'] = data.get('_edited', False) or any(cue != original[cue.id] for cue in request.cues)
        data['cues'] = request.cues
        return {**data, 'text': subtitle_service.txt(data['cues'])}

@app.post('/api/tasks/{task_id}/subtitles/resplit', response_model=TranscriptionResult)
def resplit(task_id: str):
    with store.lock:
        data = result_by_id(task_id)
        if data.get('_edited'):
            raise HTTPException(409, '已人工修改字幕，重新切分会覆盖修改，请保留当前结果')
        if '_segments' not in data:
            raise HTTPException(409, '该识别结果没有保留原始词时间戳')
        duration = media_by_id(task_by_id(task_id)['media_id'])['duration']
        cues = subtitle_service.split_segments(data['_segments'], data['language'], duration)
        subtitle_service.validate(cues, duration)
        data['cues'] = cues
        return {**data, 'text': subtitle_service.txt(cues)}

@app.get('/api/tasks/{task_id}/export/{format}')
def text_export(task_id: str, format: str):
    with store.lock:
        data = result_by_id(task_id)
        media = media_by_id(task_by_id(task_id)['media_id'])
        if format not in ('txt', 'srt'):
            raise HTTPException(404, '导出格式不存在')
        content = subtitle_service.txt(data['cues']) if format == 'txt' else subtitle_service.srt(data['cues'])
        from urllib.parse import quote
        name = Path(media['name']).stem + '.' + format
        return Response(content.encode('utf-8'), media_type='text/plain; charset=utf-8', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name)})

@app.post('/api/tasks/{task_id}/export/video', status_code=202, response_model=TaskInfo)
def video_export(task_id: str, request: ExportRequest):
    with store.lock:
        cues = [c.model_copy(deep=True) for c in result_by_id(task_id)['cues']]
        media = media_by_id(task_by_id(task_id)['media_id'])
    def action(update, control):
        update('muxing' if request.mode == 'mux' else 'exporting')
        return export_service.export_video(media, cues, request.encoder, request.mode, control=control)
    return store.submit('video', media['id'], action)

@app.post('/api/exports/{export_task_id}/cancel', response_model=TaskInfo)
def cancel_video(export_task_id: str):
    with store.lock:
        task = task_by_id(export_task_id)
        if task['kind'] != 'video':
            raise HTTPException(400, '该任务不是视频导出任务，请使用导出任务 ID')
        return store.cancel_video(export_task_id)

@app.get('/api/exports/{task_id}/content')
def download_video(task_id: str):
    task = task_by_id(task_id)
    if task['kind'] != 'video' or task['status'] != 'completed':
        raise HTTPException(409, '视频尚未导出')
    media = media_by_id(task['media_id'])
    extension = task['result'].suffix
    return FileResponse(task['result'], filename=Path(media['name']).stem + '_subtitled' + extension, media_type='video/x-matroska' if extension == '.mkv' else 'video/mp4')

# Mount last so existing API routes keep their original behavior. Development
# still uses Vite; only the portable launcher supplies MEDIA_TOOL_WEB.
if WEB is not None:
    app.mount('/', StaticFiles(directory=WEB, html=True), name='frontend')
