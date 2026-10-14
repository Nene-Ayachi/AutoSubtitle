from contextlib import nullcontext
from types import SimpleNamespace as NS
import sys

import pytest

from app.schemas import TranscriptionRequest
from app.services import hardware_service
from app.services.metal_whisper import MetalWhisperModel
from app.services.transcription_service import TranscriptionService


@pytest.fixture
def mlx(monkeypatch, tmp_path):
    calls = []
    holder = NS(model=None, model_path=None)
    def load(path, dtype):
        calls.append(('load', path, dtype))
        holder.model, holder.model_path = object(), path
    holder.get_model = load
    def transcribe(audio, **kwargs):
        calls.append(('transcribe', kwargs))
        return {'language': 'en', 'segments': [dict(start=2, end=3, text=' Hello.',
                words=[dict(start=2, end=3, word=' Hello.', probability=.9)])]}
    api = NS(ModelHolder=holder, transcribe=transcribe)
    mx = NS(gpu='gpu', float16='float16', float32='float32',
            stream=lambda device: nullcontext(), clear_cache=lambda: calls.append(('clear',)),
            metal=NS(is_available=lambda: True), array=lambda x: 1, eval=lambda x: None)
    monkeypatch.setitem(sys.modules, 'mlx', NS(core=mx))
    monkeypatch.setitem(sys.modules, 'mlx.core', mx)
    monkeypatch.setitem(sys.modules, 'mlx_whisper', NS())
    monkeypatch.setitem(sys.modules, 'mlx_whisper.transcribe', api)
    def download(repo, **kwargs):
        calls.append(('download', repo, kwargs))
        return str(tmp_path)
    monkeypatch.setattr('huggingface_hub.snapshot_download', download)
    monkeypatch.setattr('faster_whisper.audio.decode_audio', lambda *a, **kw: [0] * 64000)
    monkeypatch.setattr('faster_whisper.vad.get_speech_timestamps', lambda a: [{'start': 32000, 'end': 48000}])
    return calls, holder, mx


@pytest.mark.parametrize('available', [True, False])
def test_metal_probe(mlx, monkeypatch, available):
    _, _, mx = mlx
    mx.metal.is_available = lambda: available
    monkeypatch.setattr(hardware_service.sys, 'platform', 'darwin')
    monkeypatch.setattr(hardware_service.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(hardware_service, 'run', lambda *a, **kw: '')
    monkeypatch.setitem(sys.modules, 'ctranslate2', NS(
        get_supported_compute_types=lambda d: {'float32'}, get_cuda_device_count=lambda: 0))
    hardware_service.info.cache_clear()
    try:
        hw = hardware_service.info()
        assert hw['metal'] == available
        assert hw['recommended_device'] == ('metal' if available else 'cpu')
        assert hw['recommended_compute'] == ('float16' if available else 'float32')
    finally:
        hardware_service.info.cache_clear()


@pytest.mark.parametrize('offline', [True, False])
def test_adapter_download_vad_words_and_release(mlx, tmp_path, offline):
    calls, holder, _ = mlx
    model = MetalWhisperModel('small', compute_type='float16', download_root=tmp_path, local_files_only=offline)
    assert calls[0][2]['local_files_only'] == offline
    assert calls[0][2]['cache_dir'] == str(tmp_path / 'mlx')
    segments, info = model.transcribe('test.wav', language=None, beam_size=5, vad_filter=True, word_timestamps=True)
    segment = next(segments)
    assert (segment.start, segment.words[0].start, info.language) == (2, 2, 'en')
    options = calls[-1][1]
    assert options['clip_timestamps'] == [2, 3]
    assert options['fp16'] and options['word_timestamps']
    assert 'beam_size' not in options
    assert options['temperature'] == 0.0
    model.close()
    assert holder.model is None and holder.model_path is None


def test_silence_skips_inference(mlx, tmp_path, monkeypatch):
    calls, _, _ = mlx
    model = MetalWhisperModel('small', compute_type='float32', download_root=tmp_path, local_files_only=True)
    monkeypatch.setattr('faster_whisper.vad.get_speech_timestamps', lambda a: [])
    segments, info = model.transcribe('test.wav', language=None, beam_size=1, vad_filter=True, word_timestamps=True)
    assert list(segments) == [] and info.language is None
    assert not any(c[0] == 'transcribe' for c in calls)


def test_service_routing_reuse_precision_and_offsets(mlx, tmp_path, monkeypatch):
    calls, holder, _ = mlx
    monkeypatch.setattr(hardware_service, 'info', lambda: {
        'cuda': False, 'metal': True,
        'compute_types': {'cpu': ['float32'], 'metal': ['float16', 'float32']}})
    monkeypatch.setattr('app.services.media_service.extract', lambda path, out, *a, **kw: out.touch())
    service = TranscriptionService()
    media = {'path': tmp_path / 'input.wav', 'duration': 65}
    request = TranscriptionRequest(media_id='x', model='small')
    result = service.transcribe(media, request, lambda *a: None)
    assert result['metrics']['device'] == 'metal'
    assert result['metrics']['compute_type'] == 'float16'
    assert result['_segments'][1].words[0].start == 62
    assert 'Beam' in result['message']
    service.transcribe(media, request, lambda *a: None)
    assert len([c for c in calls if c[0] == 'load']) == 1
    service.transcribe(media, request.model_copy(update={'compute_type': 'float32'}), lambda *a: None)
    assert [c for c in calls if c[0] == 'load'][-1][2] == 'float32'
    with pytest.raises(ValueError, match='不支持'):
        service.transcribe(media, request.model_copy(update={'compute_type': 'int8'}), lambda *a: None)
    service.unload()
    assert holder.model is None
    assert not list((tmp_path / 'work').glob('*/audio-chunk.wav'))


def test_unavailable_metal_has_actionable_error(monkeypatch):
    monkeypatch.setattr(hardware_service, 'info', lambda: {'cuda': False, 'metal': False})
    with pytest.raises(ValueError, match='Metal 不可用'):
        TranscriptionService().transcribe({}, TranscriptionRequest(media_id='x', device='metal'), lambda *a: None)


def test_model_load_failure_clears_global_cache(mlx, tmp_path):
    _, holder, _ = mlx
    def fail(*args):
        holder.model = object()
        raise RuntimeError('load failure')
    holder.get_model = fail
    with pytest.raises(RuntimeError, match='load failure'):
        MetalWhisperModel('small', compute_type='float16', download_root=tmp_path, local_files_only=True)
    assert holder.model is None


def test_offline_cache_miss_never_retries_download(mlx, tmp_path, monkeypatch):
    attempts = []
    def missing(repo, **options):
        attempts.append(options)
        raise FileNotFoundError('no cached model')
    monkeypatch.setattr('huggingface_hub.snapshot_download', missing)
    with pytest.raises(FileNotFoundError):
        MetalWhisperModel('small', compute_type='float16', download_root=tmp_path, local_files_only=True)
    assert len(attempts) == 1 and attempts[0]['local_files_only']


def test_vad_intervals_preserve_offsets_and_detected_language(mlx, tmp_path, monkeypatch):
    calls, _, _ = mlx
    monkeypatch.setattr('faster_whisper.vad.get_speech_timestamps', lambda a: [
        {'start': 0, 'end': 16000}, {'start': 32000, 'end': 48000}])
    model = MetalWhisperModel('small', compute_type='float16', download_root=tmp_path, local_files_only=True)
    model.transcribe('test.wav', language=None, beam_size=1, vad_filter=True, word_timestamps=True)
    options = [c[1] for c in calls if c[0] == 'transcribe']
    assert [o['clip_timestamps'] for o in options] == [[0, 1], [2, 3]]
    assert options[0]['language'] is None and options[1]['language'] == 'en'


def test_cancel_after_metal_inference_releases_model_and_files(mlx, tmp_path, monkeypatch):
    from app.services.video_process import TaskControl
    calls, holder, _ = mlx
    control = TaskControl('metal-cancel', seal_on_process_exit=False)
    monkeypatch.setattr(hardware_service, 'info', lambda: {
        'cuda': False, 'metal': True, 'compute_types': {'metal': ['float16']}})
    monkeypatch.setattr('app.services.media_service.extract', lambda path, out, *a, **kw: out.touch())
    api = sys.modules['mlx_whisper.transcribe']
    original = api.transcribe
    def cancel(*args, **kwargs):
        control.request_cancel()
        return original(*args, **kwargs)
    api.transcribe = cancel
    service = TranscriptionService()
    from app.services.video_process import ExportCancelled
    with pytest.raises(ExportCancelled):
        service.transcribe({'path': tmp_path / 'input.wav', 'duration': 60},
                           TranscriptionRequest(media_id='x'), lambda *a: None, control)
    assert service.model is None and holder.model is None
    assert not (tmp_path / 'work' / control.task_id).exists()
