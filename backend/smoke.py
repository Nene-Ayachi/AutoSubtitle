"""Manual integration runner. Run inside media-tool; needs .test-work/speech.wav.

Downloads no model by default. Use --download to explicitly authorize small.
"""
import argparse
import json
import time
import logging
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.config import FFMPEG
from app.services.media_service import run, probe

logging.getLogger('httpx').setLevel(logging.WARNING)

parser=argparse.ArgumentParser()
parser.add_argument('--device',choices=['cpu','cuda'],default='cpu')
parser.add_argument('--download',action='store_true')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
work=root/'.test-work'
work.mkdir(exist_ok=True)
source=work/'中文 视频 [test].mp4'
run([FFMPEG,'-v','error','-y','-f','lavfi','-i','color=c=0x202b40:size=1920x1080:rate=30','-i',str(work/'speech.wav'),'-shortest','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',str(source)])

def wait(client,task_id):
    old=None
    for _ in range(2400):
        task=client.get(f'/api/tasks/{task_id}').json()
        current=(task['status'],task['stage'])
        if current != old:
            print(current,flush=True)
            old=current
        if task['status']=='failed':raise RuntimeError(task['error'])
        if task['status']=='completed':return task
        time.sleep(.25)
    raise TimeoutError('任务超过十分钟')

with TestClient(app) as client:
    hw=client.get('/api/system/info').json()
    print(json.dumps(hw,ensure_ascii=False),flush=True)
    with source.open('rb') as file:
        response=client.post('/api/media',files={'file':(source.name,file,'video/mp4')})
    response.raise_for_status()
    media=response.json()
    task=client.post('/api/tasks/transcription',json={'media_id':media['id'],'quality':'fast','device':args.device,'language':'en','allow_download':args.download}).json()
    wait(client,task['id'])
    prefix=f"/api/tasks/{task['id']}"
    result=client.get(prefix+'/result').json()
    assert result['cues'],result
    print('RECOGNIZED:',result['text'],flush=True)
    result['cues'][0]['text']='你好。こんにちは。Hello, edited subtitle.'
    edit=client.put(prefix+'/subtitles',json={'cues':result['cues']})
    edit.raise_for_status()
    for format in ['txt','srt']:
        response=client.get(prefix+'/export/'+format)
        response.raise_for_status()
        assert 'Hello, edited subtitle.' in response.text
        (work/f'result-{args.device}.{format}').write_bytes(response.content)
    for encoder in hw['encoders']:
        task=client.post(prefix+'/export/video',json={'encoder':encoder}).json()
        wait(client,task['id'])
        exported=client.get(f"/api/exports/{task['id']}/content")
        exported.raise_for_status()
        path=work/f'result-{args.device}-{encoder}.mp4'
        path.write_bytes(exported.content)
        metadata=probe(path)
        assert metadata['width']==1920 and metadata['height']==1080
        assert abs(metadata['duration']-media['duration']) < .5
    (work/f'validation-{args.device}.json').write_text(json.dumps({'hardware':hw,'metrics':result['metrics'],'media':media,'text':result['text']},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Real upload -> transcription -> edit -> TXT/SRT -> all available MP4 encoders passed',flush=True)
