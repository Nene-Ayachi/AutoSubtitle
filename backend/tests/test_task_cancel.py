import asyncio
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect
from app import core, main
from app.config import FFMPEG
from app.schemas import TranscriptionRequest
from app.services import hardware_service, media_service, subtitle_service
from app.services.transcription_service import TranscriptionService
from app.services.video_process import TaskControl, TaskCancelledError


def until(check, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.01)
    raise AssertionError('task timeout')


@pytest.fixture
def store(monkeypatch, tmp_path):
    item = core.Store()
    monkeypatch.setattr(main, 'store', item)
    monkeypatch.setattr(main, 'DATA', tmp_path / 'sessions')
    monkeypatch.setattr(hardware_service, 'info', lambda: {'cuda': False, 'compute_types': {'cpu': ['int8']}})
    source = tmp_path / 'original.mp4'
    source.write_bytes(b'original media')
    item.media['media'] = {'id': 'media', 'name': 'original.mp4', 'path': source,
                           'duration': 121, 'video': True, 'hdr': False}
    def extract(path, output, start, seconds, **kwargs):
        output.write_bytes(b'partial audio')
    monkeypatch.setattr(media_service, 'extract', extract)
    yield item
    for task_id in list(item.controls):
        item.cancel_task(task_id)
    item.pool.shutdown(wait=True)


def terminal(store, task_id):
    return until(lambda: store.tasks[task_id] if store.tasks[task_id]['status'] in
                 ('completed', 'cancelled', 'failed') else None)


@pytest.mark.parametrize('phase', ['model', 'extract', 'eager', 'next', 'subtitles'])
def test_cooperative_checkpoints_prevent_downstream_and_allow_retry(store, monkeypatch, phase):
    entered, release = threading.Event(), threading.Event()
    counts = {'next': 0, 'closed': 0, 'extract': 0, 'subtitles': 0}
    def block():
        entered.set()
        release.wait(4)
    class Model:
        def __init__(self, *args, **kwargs):
            if phase == 'model': block()
        def transcribe(self, *args, **kwargs):
            if phase == 'eager': block()
            def segments():
                try:
                    for _ in range(3):
                        counts['next'] += 1
                        if phase == 'next': block()
                        yield NS(text='Hello.', start=.1, end=1, words=None)
                finally:
                    counts['closed'] += 1
            return segments(), NS(language='en')
    monkeypatch.setattr('faster_whisper.WhisperModel', Model)
    def extract(path, output, start, seconds, **kwargs):
        counts['extract'] += 1
        output.write_bytes(b'audio')
        if phase == 'extract': block()
    monkeypatch.setattr(media_service, 'extract', extract)
    real_split = subtitle_service.split_segments
    def split(*args, **kwargs):
        counts['subtitles'] += 1
        if phase == 'subtitles': block()
        return real_split(*args, **kwargs)
    monkeypatch.setattr(subtitle_service, 'split_segments', split)
    try:
        with TestClient(main.app) as client:
            job = client.post('/api/tasks/transcription', json={'media_id': 'media', 'quality': 'fast'}).json()
            assert entered.wait(2)
            response = client.post(f'/api/tasks/{job["id"]}/cancel').json()
            assert response['status'] == 'cancelling'
            assert client.post(f'/api/tasks/{job["id"]}/cancel').json()['status'] == 'cancelling'
            time.sleep(.03)
            assert store.tasks[job['id']]['status'] == 'cancelling'
            assert client.post('/api/tasks/transcription', json={'media_id': 'media'}).status_code == 400
            release.set()
            assert terminal(store, job['id'])['status'] == 'cancelled'
            assert 'result' not in store.tasks[job['id']]
            assert client.get(f'/api/tasks/{job["id"]}/result').status_code == 409
            assert store.media['media']['path'].read_bytes() == b'original media'
            assert not list(store.media['media']['path'].parent.rglob('audio-chunk.wav'))
            assert store.ai.model is None
            if phase == 'model': assert counts['extract'] == 0
            if phase in ('extract', 'eager'): assert counts['next'] == 0
            if phase == 'next': assert counts['next'] == 1 and counts['closed'] == 1
            if phase != 'subtitles': assert counts['subtitles'] == 0
            # Block's gate stays open; a new task must work with its own event/dir.
            retry = client.post('/api/tasks/transcription', json={'media_id': 'media', 'quality': 'fast'}).json()
            assert retry['id'] != job['id']
            assert terminal(store, retry['id'])['status'] == 'completed'
            assert client.post(f'/api/tasks/{retry["id"]}/cancel').json()['status'] == 'completed'
            assert client.post('/api/tasks/missing/cancel').status_code == 404
    finally:
        release.set()


def test_pending_transcription_cancel_is_immediate_and_independent(store):
    gate, entered = threading.Event(), threading.Event()
    def action(update):
        entered.set()
        gate.wait(4)
        return 'done'
    first = store.submit('transcription', 'other', action)
    assert entered.wait(2)
    calls = []
    second = store.submit('transcription', 'media', lambda update: calls.append(1))
    try:
        assert store.cancel_task(second['id'])['status'] == 'cancelled'
        assert store.tasks[first['id']]['status'] == 'processing'
        gate.set()
        assert terminal(store, first['id'])['status'] == 'completed'
        store.pool.submit(lambda: None).result(2)
        assert not calls and store.tasks[second['id']]['status'] == 'cancelled'
    finally:
        gate.set()


def test_cancel_after_action_return_before_publication_discards_result(store):
    entered, release = threading.Event(), threading.Event()
    def action(update, control):
        entered.set()
        release.wait(4)
        return {'partial': 'must not be published'}
    job = store.submit('transcription', 'media', action, controlled=True)
    try:
        assert entered.wait(2)
        store.cancel_task(job['id'])
        release.set()
        assert terminal(store, job['id'])['status'] == 'cancelled'
        assert 'result' not in store.tasks[job['id']]
    finally:
        release.set()


def test_model_error_after_cancel_preserves_complete_cache(store, monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    cached = tmp_path / 'complete-model.bin'
    cached.write_bytes(b'complete cached model')
    def model(*args, **kwargs):
        entered.set()
        release.wait(4)
        raise RuntimeError('synchronous download failed while cancelling')
    monkeypatch.setattr('faster_whisper.WhisperModel', model)
    request = TranscriptionRequest(media_id='media', quality='fast', allow_download=True)
    job = store.submit('transcription', 'media', lambda update, control:
                       store.ai.transcribe(store.media['media'], request, update, control), controlled=True)
    try:
        assert entered.wait(2)
        assert store.cancel_task(job['id'])['stage'] == 'cancel_wait_model'
        release.set()
        assert terminal(store, job['id'])['status'] == 'cancelled'
        assert cached.read_bytes() == b'complete cached model'
    finally:
        release.set()


def test_real_ffmpeg_audio_extraction_terminates_own_process(tmp_path, monkeypatch):
    source = tmp_path / 'source.wav'
    media_service.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '6', str(source)])
    original = source.read_bytes()
    control = TaskControl('audio', seal_on_process_exit=False)
    output = tmp_path / 'chunk.wav'
    from app.services import video_process
    actual_run = video_process.run_video
    def paced(args, **kwargs):
        args = list(args)
        args.insert(args.index('-i'), '-re')
        return actual_run(args, **kwargs)
    monkeypatch.setattr(video_process, 'run_video', paced)
    errors = []
    def work():
        try: media_service.extract(source, output, 0, 6, control)
        except Exception as exc: errors.append(exc)
        finally: output.unlink(missing_ok=True)
    thread = threading.Thread(target=work)
    thread.start()
    try:
        process = until(lambda: control.process)
        control.request_cancel()
        thread.join(5)
        assert not thread.is_alive() and process.poll() is not None
        assert len(errors) == 1 and isinstance(errors[0], TaskCancelledError)
        assert control.process is None and not output.exists()
        assert source.read_bytes() == original
    finally:
        control.request_cancel()
        thread.join(10)


def test_subtitle_dp_has_cancel_checkpoint():
    from app.services.subtitle_service import SegmentData, WordData
    text = '这是一个用于验证字幕生成循环可以及时停止的长句子' * 4
    segment = SegmentData(text, 0, 20, tuple(WordData(ch, i*.1, (i+1)*.1) for i,ch in enumerate(text)))
    calls = []
    def check():
        calls.append(1)
        if len(calls) == 6: raise TaskCancelledError()
    with pytest.raises(TaskCancelledError):
        subtitle_service.split_segments([segment], 'zh', check_cancel=check)
    assert len(calls) == 6


def test_stream_upload_api_preserves_original_and_supports_restart(store, monkeypatch):
    monkeypatch.setattr(media_service, 'probe', lambda path, control=None: {'duration': 1, 'video': True, 'hdr': False})
    with TestClient(main.app) as client:
        response = client.post('/api/media/upload?filename=uploaded.mp4', content=b'complete upload',
                               headers={'Content-Type': 'application/octet-stream'})
        assert response.status_code == 201
        media = response.json()
        assert store.media[media['id']]['path'].read_bytes() == b'complete upload'
        assert store.media['media']['path'].read_bytes() == b'original media'


@pytest.mark.parametrize('disconnect', ['body', 'probe', 'none'])
def test_stream_upload_disconnect_and_success(tmp_path, monkeypatch, disconnect):
    workspace = tmp_path / 'uploads'
    workspace.mkdir()
    monkeypatch.setattr(main.app.state, 'workspace', workspace, raising=False)
    class Request:
        stopped = False
        async def stream(self):
            yield b'partial media'
            if disconnect == 'body': raise ClientDisconnect()
        async def is_disconnected(self): return self.stopped
    request = Request()
    def probe(path, control):
        if disconnect == 'probe':
            request.stopped = True
            until(lambda: control.cancel.is_set())
            control.check()
        return {'duration': 1, 'video': True, 'hdr': False}
    monkeypatch.setattr(media_service, 'probe', probe)
    if disconnect == 'none':
        result = asyncio.run(main.streaming_upload(request, '中文 视频.mp4'))
        assert result['name'] == '中文 视频.mp4'
        assert main.store.media[result['id']]['path'].read_bytes() == b'partial media'
        assert len(list(workspace.iterdir())) == 1
    else:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(main.streaming_upload(request, '中文 视频.mp4'))
        assert caught.value.status_code == 499
        assert not list(workspace.iterdir())


@pytest.mark.skipif(os.getenv('MEDIA_TOOL_REAL_GPU') != '1', reason='Explicit native GPU test opt-in required')
def test_real_gpu_next_segment_cancel(tmp_path, monkeypatch):
    import faster_whisper
    from app.config import MODELS
    hw = hardware_service.info()
    assert hw['cuda'], 'Native CUDA validation requires working GPU'
    real_model = faster_whisper.WhisperModel('small', device='cuda', compute_type='float16', download_root=str(MODELS), local_files_only=True)
    entered = threading.Event()
    native_yields = []
    class Model:
        def __init__(self, *args, **kwargs): pass
        def transcribe(self, *args, **kwargs):
            segments, info = real_model.transcribe(*args, **kwargs)
            def observed():
                entered.set()
                for segment in segments:
                    native_yields.append(segment.text)
                    yield segment
            return observed(), info
    monkeypatch.setattr(faster_whisper, 'WhisperModel', Model)
    source = Path(__file__).resolve().parents[2] / '.test-work' / '中文 视频 [test].mp4'
    local_source = tmp_path / 'source.mp4'
    local_source.write_bytes(source.read_bytes())
    store = core.Store()
    media = {'path': local_source, 'duration': 9.702676, 'audio_duration': 9.702676}
    options = TranscriptionRequest(media_id='media', quality='fast', device='cuda', language='en')
    job = store.submit('transcription', 'media', lambda update, control:
                       store.ai.transcribe(media, options, update, control), controlled=True)
    try:
        assert entered.wait(15)
        store.cancel_task(job['id'])
        assert terminal(store, job['id'])['status'] == 'cancelled'
        assert len(native_yields) == 1
        assert 'result' not in store.tasks[job['id']]
        assert local_source.exists() and not list(tmp_path.rglob('audio-chunk.wav'))
        assert store.ai.model is None
    finally:
        store.cancel_task(job['id'])
        store.pool.shutdown(wait=True)
