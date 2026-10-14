"""Relocate and exercise the actual release with no developer PATH/PYTHONPATH."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.test-work' / 'portable-verification'
SYSTEM = Path(os.environ.get('SystemRoot', 'C:/Windows'))
POWERSHELL = SYSTEM / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'


def isolated_environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CONDA', 'PYTHON', 'MEDIA_TOOL'))}
    env['PATH'] = str(SYSTEM / 'System32') + os.pathsep + str(SYSTEM)
    return env


def bootstrap(bundle, *args, **kwargs):
    return subprocess.run([str(POWERSHELL), '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                           '-File', str(bundle / 'bootstrap.ps1'), *args],
                          env=isolated_environment(), creationflags=subprocess.CREATE_NO_WINDOW,
                          **kwargs)


def check_runtime(bundle):
    result = bootstrap(bundle, '--check', capture_output=True, timeout=300)
    def decode(raw):
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            return raw.decode('gb18030', errors='replace')
    output, errors = decode(result.stdout), decode(result.stderr)
    if result.returncode:
        raise RuntimeError(output + errors)
    data = json.loads(output[output.index('{'):])
    assert Path(data['prefix']) == bundle / 'runtime'
    assert Path(data['models']) == bundle / 'models'
    for filename in data['libraries'].values():
        assert Path(filename).is_relative_to(bundle)
    assert data['hardware']['ffmpeg'] and data['hardware']['ffprobe']
    return data


def request(url, path, data=None, method=None):
    headers = {}
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    response = urllib.request.urlopen(urllib.request.Request(url + path.lstrip('/'), data=data,
                                        headers=headers, method=method), timeout=30)
    raw = response.read()
    return json.loads(raw) if 'application/json' in response.headers.get('Content-Type', '') else raw


def wait_task(url, task_id):
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        task = request(url, f'api/tasks/{task_id}')
        if task['status'] == 'failed':
            raise RuntimeError(task['error'])
        if task['status'] in ('completed', 'cancelled'):
            return task
        time.sleep(.1)
    raise TimeoutError('Portable task timeout')


def upload(url, source):
    boundary = 'MediaTool' + uuid.uuid4().hex
    payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.mp4"\r\n'
               'Content-Type: video/mp4\r\n\r\n').encode() + source.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(url + 'api/media', data=payload,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--download', action='store_true', help='Explicitly download small into the isolated validation bundle')
    parser.add_argument('--skip-inference', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise RuntimeError('Verify the Windows portable bundle on Windows x64')
    if WORK.exists():
        if not WORK.resolve().is_relative_to((ROOT / '.test-work').resolve()):
            raise RuntimeError('Unsafe verification cleanup path')
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    archive = ROOT / 'release' / 'MediaTool-Portable-Windows-x64.zip'
    print('Extracting actual release...', flush=True)
    with zipfile.ZipFile(archive) as zip_file:
        zip_file.extractall(WORK / '首次解压 空格')
    initial = WORK / '首次解压 空格' / 'MediaTool-Portable-Windows-x64'
    first = check_runtime(initial)
    relocated = WORK / '移动后 中文空格' / 'Media Tool'
    relocated.parent.mkdir()
    # Both resolved targets are inside the explicit verification workspace.
    assert initial.resolve().is_relative_to(WORK.resolve()) and relocated.resolve().is_relative_to(WORK.resolve())
    shutil.move(str(initial), str(relocated))
    (relocated / 'models' / 'relocation-check.txt').write_text('preserve cache', encoding='utf-8')
    second = check_runtime(relocated)
    assert (relocated / 'models' / 'relocation-check.txt').read_text() == 'preserve cache'
    print('Private runtime and folder relocation passed.', flush=True)
    blocker = socket.socket()
    blocker.bind(('127.0.0.1', 16765))
    blocker.listen(1)
    log_path = WORK / 'server.log'
    process = None
    report = {'first_runtime': first, 'relocated_runtime': second}
    try:
        with log_path.open('wb') as log:
            process = subprocess.Popen([str(POWERSHELL), '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                '-File', str(relocated / 'bootstrap.ps1'), '--no-browser', '--port', '16765'],
                env=isolated_environment(), stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 60
            url = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(log_path.read_text(encoding='utf-8', errors='replace'))
                found = re.search(r'http://127\.0\.0\.1:\d+/', log_path.read_text(encoding='utf-8', errors='replace'))
                if found:
                    url = found.group()
                    try:
                        if b'<html' in request(url, ''):
                            break
                    except OSError:
                        pass
                time.sleep(.1)
            else:
                raise TimeoutError('Portable server did not start')
            assert ':16765/' not in url
            index = request(url, '').decode()
            asset = re.search(r'src="([^"]+\.js)"', index).group(1)
            assert request(url, asset)
            duplicate = bootstrap(relocated, '--no-browser', capture_output=True, text=True, timeout=10)
            assert duplicate.returncode == 0 and 'already running' in duplicate.stdout
            hw = request(url, 'api/system/info')
            report['hardware'] = hw
            if not args.skip_inference:
                source = ROOT / '.test-work' / '中文 视频 [test].mp4'
                if not source.exists():
                    raise RuntimeError('Generate .test-work synthetic video with backend/smoke.py first')
                media = upload(url, source)
                metrics = {}
                for device in (['cpu', 'cuda'] if hw['cuda'] else ['cpu']):
                    task = request(url, 'api/tasks/transcription', {'media_id': media['id'],
                        'quality': 'fast', 'model': 'small', 'device': device,
                        'language': 'en', 'allow_download': args.download})
                    assert wait_task(url, task['id'])['status'] == 'completed'
                    result = request(url, f'api/tasks/{task["id"]}/result')
                    assert result['cues'] and 'Media' in result['text']
                    metrics[device] = result['metrics']
                prefix = f'api/tasks/{task["id"]}'
                result['cues'][0]['text'] = '便携版本校对。こんにちは。Portable edited.'
                request(url, prefix + '/subtitles', {'cues': result['cues']}, 'PUT')
                txt = request(url, prefix + '/export/txt')
                assert 'Portable edited.' in txt.decode()
                assert 'Portable edited.' in request(url, prefix + '/export/srt').decode()
                for encoder in hw['encoders']:
                    export = request(url, prefix + '/export/video', {'encoder': encoder})
                    assert wait_task(url, export['id'])['status'] == 'completed'
                    output = WORK / f'{encoder}.mp4'
                    output.write_bytes(request(url, f'api/exports/{export["id"]}/content'))
                    probe = subprocess.run([str(relocated / 'tools' / 'ffprobe.exe'), '-v', 'error',
                        '-show_format', '-show_streams', '-of', 'json', str(output)], check=True,
                        capture_output=True, env=isolated_environment())
                    metadata = json.loads(probe.stdout)
                    assert any(s['codec_type'] == 'video' for s in metadata['streams'])
                    assert any(s['codec_type'] == 'audio' for s in metadata['streams'])
                    assert abs(float(metadata['format']['duration']) - media['duration']) < .5
                export = request(url, prefix + '/export/video', {'mode': 'mux'})
                assert wait_task(url, export['id'])['output_format'] == 'mkv'
                assert request(url, f'api/exports/{export["id"]}/content')
                cancelled = request(url, prefix + '/export/video', {'encoder': 'libx264'})
                time.sleep(.1)
                response = request(url, f'api/exports/{cancelled["id"]}/cancel', {}, 'POST')
                assert response['status'] in ('cancelling', 'cancelled')
                assert wait_task(url, cancelled['id'])['status'] == 'cancelled'
                assert request(url, prefix + '/export/txt') == txt
                assert request(url, f'api/media/{media["id"]}/content')
                retry = request(url, prefix + '/export/video', {})
                assert wait_task(url, retry['id'])['status'] == 'completed'
                report['metrics'] = metrics
                print('CPU/CUDA recognition, edits, TXT/SRT, MP4/MKV and cancel/retry passed.', flush=True)
            (relocated / 'stop.request').touch()
            assert process.wait(timeout=30) == 0
        assert not list((relocated / 'data').glob('session-*'))
        report['passed'] = True
        (WORK / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Portable verification passed. Report:', WORK / 'report.json', flush=True)
    finally:
        blocker.close()
        if process is not None and process.poll() is None:
            (relocated / 'stop.request').touch()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], check=False,
                               creationflags=subprocess.CREATE_NO_WINDOW)
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
