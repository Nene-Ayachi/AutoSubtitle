import threading
import time
from fastapi.testclient import TestClient
from app.main import app
from app.core import store
from app.schemas import Cue
from app.services import media_service, export_service, hardware_service
from app.services.subtitle_service import SegmentData

def wait(client, task_id):
    for _ in range(200):
        task=client.get(f'/api/tasks/{task_id}').json()
        if task['status'] in ('completed','failed'):return task
        time.sleep(.01)
    raise AssertionError('task timeout')

def test_full_api_edit_exports_and_failure(monkeypatch):
    monkeypatch.setattr(media_service,'probe',lambda _:dict(duration=10,video=True,width=1920,height=1080,hdr=False))
    calls=[]
    gate=threading.Event()
    def fake_transcribe(media, options, update, control=None):
        calls.append(options)
        update('transcribing',.5)
        gate.wait(2)
        return {'cues':[Cue(id=1,start=1,end=3,text='你好。')], 'metrics':{},'language':'zh','message':None,'_segments':[SegmentData('你好。',1,3,())]}
    monkeypatch.setattr(store.ai,'transcribe',fake_transcribe)
    monkeypatch.setattr(hardware_service,'info',lambda: {'cuda':False})
    def fail(*args):raise ValueError('模拟编码失败')
    monkeypatch.setattr(export_service,'export_video',fail)
    with TestClient(app) as client:
        assert client.get('/api/system/info').status_code==200
        uploaded=client.post('/api/media',files={'file':('中文 名称.mp4',b'fake','video/mp4')})
        assert uploaded.status_code==201
        media=uploaded.json()
        assert 'path' not in media
        task=client.post('/api/tasks/transcription',json={'media_id':media['id']}).json()
        assert task['status']=='pending'
        assert client.post('/api/tasks/transcription',json={'media_id':media['id']}).status_code==400
        assert client.get(f"/api/tasks/{task['id']}/result").status_code==409
        gate.set()
        assert wait(client,task['id'])['status']=='completed'
        path=f"/api/tasks/{task['id']}"
        result=client.get(path+'/result').json()
        assert '_segments' not in result
        assert client.post(path+'/subtitles/resplit').json()['text']=='你好。\n'
        result['cues'][0]['text']='こんにちは，edited.'
        assert client.put(path+'/subtitles',json={'cues':result['cues']}).status_code==200
        assert client.post(path+'/subtitles/resplit').status_code==409
        original_text=client.get(path+'/export/txt').text
        assert 'こんにちは，edited.' in original_text
        result['cues'][0]['start']=1.5
        assert client.put(path+'/subtitles',json={'cues':result['cues']}).status_code==200
        assert client.get(path+'/export/txt').text==original_text
        assert '00:00:01,500' in client.get(path+'/export/srt').text
        exported=client.post(path+'/export/video',json={}).json()
        assert wait(client,exported['id'])['status']=='failed'
        assert client.get(path+'/export/txt').text==original_text
        assert client.get(path+'/export/srt').status_code==200
        def mux(media, cues, encoder, mode, control=None):
            assert mode == 'mux'
            assert cues[0].text == 'こんにちは，edited.'
            output = media['path'].parent / 'export.mkv'
            output.write_bytes(b'test-mkv')
            return output
        monkeypatch.setattr(export_service,'export_video',mux)
        mux_task=client.post(path+'/export/video',json={'mode':'mux'}).json()
        finished=wait(client,mux_task['id'])
        assert finished['output_format']=='mkv'
        download=client.get(f"/api/exports/{mux_task['id']}/content")
        assert download.content==b'test-mkv'
        assert download.headers['content-type']=='video/x-matroska'
        assert '.mkv' in download.headers['content-disposition']
        assert len(calls)==1
        assert client.post('/api/media',files={'file':('bad.exe',b'x')}).status_code==400
        assert client.post('/api/tasks/transcription',json={'media_id':media['id'],'device':'cloud'}).status_code==422
