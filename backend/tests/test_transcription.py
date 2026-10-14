from types import SimpleNamespace as NS
import pytest
from app.schemas import TranscriptionRequest
from app.services.transcription_service import TranscriptionService

@pytest.fixture
def engine(monkeypatch, tmp_path):
    loaded=[]
    extracted=[]
    class FakeModel:
        def __init__(self, model, **options):
            loaded.append((model,options))
        def transcribe(self, path, **options):
            return iter([NS(start=.2,end=1.2,text=' Hello.',words=None)]), NS(language='en')
    monkeypatch.setattr('faster_whisper.WhisperModel',FakeModel)
    monkeypatch.setattr('app.services.hardware_service.info',lambda:{'cuda':True,'compute_types':{'cuda':['float16'],'cpu':['int8']}})
    def extract(path, out, start, seconds, **kwargs):
        extracted.append(start)
        out.write_bytes(b'test')
    monkeypatch.setattr('app.services.media_service.extract',extract)
    media={'path':tmp_path/'input.wav','duration':121,'audio_duration':121}
    return TranscriptionService(),media,loaded,extracted

def test_bounded_chunks_and_model_reuse(engine):
    service,media,loaded,extracted=engine
    request=TranscriptionRequest(media_id='x',quality='fast',device='cpu')
    result=service.transcribe(media,request,lambda *args:None)
    assert extracted==[0,60,120]
    assert len(result['cues'])==3
    assert result['cues'][-1].end==121
    assert result['cues'][1].start==60.2
    assert not (media['path'].parent/'audio-chunk.wav').exists()
    service.transcribe(media,request,lambda *args:None)
    assert len(loaded)==1
    service.transcribe(media,request.model_copy(update={'model':'medium'}),lambda *args:None)
    assert len(loaded)==2

def test_precision_fallback_is_visible(engine):
    service,media,loaded,_=engine
    result=service.transcribe(media,TranscriptionRequest(media_id='x',quality='fast'),lambda *args:None)
    assert loaded[0][1]['compute_type']=='float16'
    assert result['message'] and 'float16' in result['message']
    with pytest.raises(ValueError):
        service.transcribe(media,TranscriptionRequest(media_id='x',device='cuda',compute_type='int8'),lambda *args:None)

def test_failure_releases_model_and_chunk(engine,monkeypatch):
    service,media,_,_=engine
    def fail(*args,**kwargs):raise RuntimeError('inference failure')
    import faster_whisper
    monkeypatch.setattr(faster_whisper.WhisperModel,'transcribe',fail)
    with pytest.raises(RuntimeError):
        service.transcribe(media,TranscriptionRequest(media_id='x'),lambda *args:None)
    assert service.model is None and service.key is None
    assert not (media['path'].parent/'audio-chunk.wav').exists()


def test_arm_cpu_float32_fallback(engine, monkeypatch):
    service, media, loaded, _ = engine
    monkeypatch.setattr('app.services.hardware_service.info', lambda: {
        'cuda': False, 'compute_types': {'cpu': ['float32'], 'cuda': []}})
    result = service.transcribe(media, TranscriptionRequest(media_id='x', quality='fast'), lambda *args: None)
    assert loaded[0][1]['device'] == 'cpu'
    assert loaded[0][1]['compute_type'] == 'float32'
    assert 'float32' in result['message']
