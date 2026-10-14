import io
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from app import core, main
from app.config import FFMPEG
from app.schemas import Cue
from app.services import export_service, media_service, video_process, hardware_service


def until(predicate, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(.01)
    raise AssertionError('Timed out waiting for export condition')


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'TranscriptionService', lambda: SimpleNamespace(unload=lambda: None))
    store = core.Store()
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setattr(hardware_service, 'info', lambda: {'encoders': ['libx264']})
    try:
        yield store
    finally:
        for task_id in list(store.video_controls):
            store.cancel_video(task_id)
        store.pool.shutdown(wait=True)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'original.mp4'
    media_service.run([
        FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=size=320x240:rate=25',
        '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '8',
        '-c:v', 'libx264', '-c:a', 'aac', str(path),
    ])
    return path


def seed(store, source):
    store.media['media'] = {'id': 'media', 'name': '原始视频.mp4', 'path': source,
                            'duration': 8, 'video': True, 'hdr': False}
    store.tasks['recognition'] = {'id': 'recognition', 'kind': 'transcription',
        'media_id': 'media', 'status': 'completed', 'stage': None, 'progress': 1,
        'error': None, 'result': {'cues': [Cue(id=1, start=0, end=6, text='已校对字幕')],
                                'metrics': {}, 'language': 'zh'}}


def state(client, task_id):
    return client.get(f'/api/tasks/{task_id}').json()


def terminal(client, task_id):
    return until(lambda: (t if (t := state(client, task_id))['status'] in
                         ('completed', 'cancelled', 'failed') else None))


@pytest.mark.parametrize('mode', ['burn', 'mux'])
def test_real_ffmpeg_cancel_cleanup_edit_retry_and_text_exports(isolated, source, monkeypatch, mode):
    store = isolated
    seed(store, source)
    original = source.read_bytes()
    real_run = export_service.run_video
    # Real encoder, paced input so cancellation cannot race a tiny fixture's finish.
    def paced(args, **kwargs):
        args = list(args)
        args.insert(args.index('-i'), '-re')
        return real_run(args, **kwargs)
    monkeypatch.setattr(export_service, 'run_video', paced)
    with TestClient(main.app) as client:
        edited = client.get('/api/tasks/recognition/result').json()['cues']
        edited[0]['text'] = '取消之后仍保留的编辑。こんにちは。Edited.'
        assert client.put('/api/tasks/recognition/subtitles', json={'cues': edited}).status_code == 200
        txt = client.get('/api/tasks/recognition/export/txt').content
        srt = client.get('/api/tasks/recognition/export/srt').content
        task_id = client.post('/api/tasks/recognition/export/video', json={'mode': mode}).json()['id']
        control = store.video_controls[task_id]
        process = until(lambda: control.process)
        extension = 'mp4' if mode == 'burn' else 'mkv'
        temporary = source.parent / 'exports' / 'temp' / f'{task_id}.{extension}'
        until(lambda: temporary.exists())
        response = client.post(f'/api/exports/{task_id}/cancel')
        assert response.status_code == 200
        assert response.json()['status'] in ('cancelling', 'cancelled')
        assert client.post(f'/api/exports/{task_id}/cancel').status_code == 200
        assert terminal(client, task_id)['status'] == 'cancelled'
        assert process.poll() is not None and process.stdin.closed
        assert control.process is None and task_id not in store.video_controls
        assert not temporary.exists()
        assert not list((source.parent / 'exports' / 'temp').iterdir())
        assert source.read_bytes() == original
        assert client.get('/api/tasks/recognition/export/txt').content == txt
        assert client.get('/api/tasks/recognition/export/srt').content == srt
        assert client.get('/api/tasks/recognition/result').json()['cues'] == edited
        assert client.get(f'/api/exports/{task_id}/content').status_code == 409
        assert client.post(f'/api/exports/{task_id}/cancel').json()['status'] == 'cancelled'
        # New export uses the current edited cues and a different independent path.
        monkeypatch.setattr(export_service, 'run_video', real_run)
        retry = client.post('/api/tasks/recognition/export/video', json={}).json()['id']
        assert retry != task_id
        assert terminal(client, retry)['status'] == 'completed'
        output = store.tasks[retry]['result']
        assert output.is_file() and output.name == f'{retry}.mp4'
        assert media_service.probe(output)['video']
        assert client.post(f'/api/exports/{retry}/cancel').json()['status'] == 'completed'
        assert output.exists()
        assert client.get(f'/api/exports/{retry}/content').status_code == 200
        assert client.get('/api/tasks/recognition/export/txt').content == txt


def test_pending_cancel_idempotent_and_validation(isolated, tmp_path):
    store = isolated
    seed(store, tmp_path / 'source.mp4')
    gate = threading.Event()
    started = threading.Event()
    def blocker(update):
        started.set()
        gate.wait(5)
    store.submit('transcription', 'other', blocker)
    started.wait(2)
    try:
        with TestClient(main.app) as client:
            task_id = client.post('/api/tasks/recognition/export/video', json={}).json()['id']
            assert state(client, task_id)['status'] == 'pending'
            assert client.post(f'/api/exports/{task_id}/cancel').json()['status'] == 'cancelled'
            assert client.post(f'/api/exports/{task_id}/cancel').json()['status'] == 'cancelled'
            assert client.post('/api/exports/missing/cancel').status_code == 404
            assert client.post('/api/exports/recognition/cancel').status_code == 400
            gate.set()
            store.pool.submit(lambda: None).result(timeout=3)
            assert state(client, task_id)['status'] == 'cancelled'
            assert not (tmp_path / 'exports').exists()
            assert not store.video_controls
    finally:
        gate.set()


@pytest.mark.parametrize('failed', [False, True])
def test_observed_exit_wins_cancel_race(isolated, tmp_path, monkeypatch, failed):
    store = isolated
    seed(store, tmp_path / 'source.mp4')
    exited, release = threading.Event(), threading.Event()
    def completed_process(args, cwd, control):
        with control.lock:
            control.finished = True
        exited.set()
        release.wait(4)
        if failed:
            raise ValueError('FFmpeg 自行异常退出')
        Path(args[-1]).write_bytes(b'valid-output')
    monkeypatch.setattr(export_service, 'run_video', completed_process)
    monkeypatch.setattr(media_service, 'probe', lambda path: {'video': True})
    try:
        with TestClient(main.app) as client:
            task_id = client.post('/api/tasks/recognition/export/video', json={}).json()['id']
            assert exited.wait(2)
            response = client.post(f'/api/exports/{task_id}/cancel').json()
            assert response['status'] == 'processing' and response['stage'] == 'finalizing'
            assert not store.video_controls[task_id].cancel.is_set()
            release.set()
            expected = 'failed' if failed else 'completed'
            assert terminal(client, task_id)['status'] == expected
            assert client.post(f'/api/exports/{task_id}/cancel').json()['status'] == expected
            assert not list((tmp_path / 'exports' / 'temp').iterdir())
    finally:
        release.set()


def test_cancel_before_process_attached(isolated, tmp_path, monkeypatch):
    store = isolated
    seed(store, tmp_path / 'source.mp4')
    started, release = threading.Event(), threading.Event()
    def launch(args, cwd, control):
        started.set()
        release.wait(4)
        control.check()
        raise AssertionError('Cancelled export must not launch FFmpeg')
    monkeypatch.setattr(export_service, 'run_video', launch)
    try:
        with TestClient(main.app) as client:
            task_id = client.post('/api/tasks/recognition/export/video', json={}).json()['id']
            assert started.wait(2)
            assert store.video_controls[task_id].process is None
            assert client.post(f'/api/exports/{task_id}/cancel').json()['status'] == 'cancelling'
            assert client.post('/api/tasks/recognition/export/video', json={}).status_code == 400
            release.set()
            assert terminal(client, task_id)['status'] == 'cancelled'
            assert not list((tmp_path / 'exports' / 'temp').iterdir())
    finally:
        release.set()


@pytest.mark.parametrize('graceful,retry', [(True, False), (False, False), (False, True)])
def test_process_launch_cancel_race_and_forced_stop(monkeypatch, tmp_path, graceful, retry):
    control = video_process.VideoControl('test')
    methods = []
    class FakeProcess:
        pid = 123
        stdin = io.BytesIO()
        code = None
        def poll(self): return self.code
        def wait(self, timeout=None):
            if timeout == 1.5 and graceful:
                self.code = 0
            if self.code is None:
                raise subprocess.TimeoutExpired('fake', timeout)
            return self.code
        def terminate(self):
            methods.append('terminate')
            raise OSError('simulated termination failure')
        def kill(self):
            methods.append('kill')
            if retry and methods.count('kill') == 1:
                raise OSError('simulated forced termination failure')
            self.code = -1
    process = FakeProcess()
    def launch(*args, **kwargs):
        assert kwargs['stdout'] == subprocess.DEVNULL
        assert kwargs['stderr'] != subprocess.PIPE
        control.request_cancel()  # Cancellation between Popen and handle registration.
        return process
    monkeypatch.setattr(video_process.subprocess, 'Popen', launch)
    with pytest.raises(video_process.ExportCancelled):
        video_process.run_video(['ffmpeg'], tmp_path, control)
    assert process.poll() is not None and process.stdin.closed
    assert control.process is None
    assert methods == ([] if graceful else ['terminate', 'kill', 'kill'] if retry else ['terminate', 'kill'])


def test_already_exited_handle_rejects_cancel():
    control = video_process.VideoControl('test')
    control.process = SimpleNamespace(poll=lambda: 0)
    assert not control.request_cancel()
    assert control.finished and not control.cancel.is_set()


def test_cleanup_retries_and_reports_residue(tmp_path, monkeypatch, caplog):
    path = tmp_path / 'partial.mp4'
    path.write_bytes(b'partial')
    original = Path.unlink
    calls = []
    def flaky(self, **kwargs):
        calls.append(self)
        if len(calls) < 3:
            raise PermissionError('held file')
        return original(self, **kwargs)
    monkeypatch.setattr(Path, 'unlink', flaky)
    export_service.remove_temporary(path)
    assert not path.exists() and len(calls) == 3
    assert str(path) in caplog.text
    def denied(self, **kwargs): raise PermissionError('permission denied')
    monkeypatch.setattr(Path, 'unlink', denied)
    with pytest.raises(ValueError, match='残留路径'):
        export_service.remove_temporary(path)


def test_cancel_cleanup_failure_is_explicit_and_other_temp_files_are_cleaned(isolated, tmp_path, monkeypatch):
    store = isolated
    seed(store, tmp_path / 'source.mp4')
    ready, release = threading.Event(), threading.Event()
    def launch(args, cwd, control):
        Path(args[-1]).write_bytes(b'partial')
        ready.set()
        release.wait(4)
        control.check()
    original = Path.unlink
    def denied_video(self, **kwargs):
        if self.suffix == '.mp4' and self.parent.name == 'temp':
            raise PermissionError('simulated locked file')
        return original(self, **kwargs)
    monkeypatch.setattr(export_service, 'run_video', launch)
    monkeypatch.setattr(Path, 'unlink', denied_video)
    try:
        with TestClient(main.app) as client:
            task_id = client.post('/api/tasks/recognition/export/video', json={}).json()['id']
            assert ready.wait(2)
            assert client.post(f'/api/exports/{task_id}/cancel').json()['status'] == 'cancelling'
            release.set()
            finished = terminal(client, task_id)
            assert finished['status'] == 'failed'
            assert finished['stage'] == 'cancel_cleanup_failed'
            assert '残留路径' in finished['error']
            assert not list((tmp_path / 'exports' / 'temp').glob('*.srt'))
            assert (tmp_path / 'exports' / 'temp' / f'{task_id}.mp4').exists()
            assert not store.video_controls
    finally:
        release.set()
        monkeypatch.setattr(Path, 'unlink', original)


def test_missing_control_reports_error_without_false_cancellation(isolated, tmp_path):
    store = isolated
    store.tasks['orphan'] = {'id': 'orphan', 'kind': 'video', 'media_id': 'media',
        'status': 'processing', 'stage': 'exporting', 'progress': None, 'error': None}
    with TestClient(main.app) as client:
        response = client.post('/api/exports/orphan/cancel')
        assert response.status_code == 400
        assert '控制信息' in response.json()['detail']
        assert store.tasks['orphan']['status'] == 'processing'
