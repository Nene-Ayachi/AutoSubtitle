"""Verify the real ZIP after relocating, with only Apple's system tools on PATH."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
NAME = 'MediaTool-Portable-macOS-arm64'


def environment():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('PYTHON', 'CONDA', 'VIRTUAL_ENV', 'DYLD_', 'MEDIA_TOOL'))}
    env['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
    env['PYTHONNOUSERSITE'] = '1'
    return env


def launch(bundle, *args, **kwargs):
    return subprocess.run([str(bundle / 'Start-MediaTool.command'), *args],
                          env=environment(), **kwargs)


def check(bundle):
    result = launch(bundle, '--check', capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    data = json.loads(result.stdout)
    assert Path(data['prefix']).resolve() == (bundle / 'runtime').resolve()
    assert Path(data['models']) == bundle / 'models'
    assert all(Path(p).resolve().is_relative_to(bundle) for p in data['libraries'].values())
    assert data['hardware']['ffmpeg'] and data['hardware']['ffprobe']
    assert data['hardware']['metal'], data['hardware']['warnings']
    assert 'libx264' in data['hardware']['encoders']
    return data


def fetch(url, path=''):
    with urllib.request.urlopen(url + path, timeout=30) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    work = ROOT / '.test-work' / ('macos-portable-' + uuid.uuid4().hex[:8])
    work.mkdir(parents=True)
    archive = ROOT / 'release' / (NAME + '.zip')
    initial = work / '首次解压 空格'
    subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), str(initial)], check=True)
    bundle = initial / NAME
    trust = bundle / '首次信任并启动.command'
    marker = bundle / '.trust-verification'
    marker.touch()
    subprocess.run(['/usr/bin/xattr', '-w', 'com.apple.quarantine', '0081;test;MediaToolTrustTest;', str(marker)], check=True)
    cancelled = subprocess.run(['/bin/bash', str(trust), '--trust-only'], input='no\n', capture_output=True, text=True, check=True)
    assert '已取消' in cancelled.stdout
    assert 'com.apple.quarantine' in subprocess.check_output(['/usr/bin/xattr', str(marker)], text=True)
    approved = subprocess.run(['/bin/bash', str(trust), '--trust-only'], input='TRUST\n', capture_output=True, text=True, check=True)
    assert '初始化完成' in approved.stdout
    assert 'com.apple.quarantine' not in subprocess.check_output(['/usr/bin/xattr', str(marker)], text=True)
    marker.unlink()
    first = check(bundle)
    relocated = work / '移动后 中文目录' / 'Media Tool'
    relocated.parent.mkdir()
    shutil.move(bundle, relocated)
    bundle = relocated
    (bundle / 'models/relocation-check.txt').write_text('preserve')
    second = check(bundle)
    assert (bundle / 'models/relocation-check.txt').read_text() == 'preserve'
    # Verify extraction, Chinese/Japanese subtitle burn-in, mux and bundled ffprobe.
    media_script = r'''
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
import launcher
launcher.configure()
from app.config import FFMPEG
from app.schemas import Cue
from app.services import media_service, export_service
path = root / 'data' / '中文 测试.mp4'
media_service.run([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=size=320x240:rate=25', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)])
media = dict(path=path, video=True, hdr=False)
cues = [Cue(id=1, start=0, end=1.5, text='你好。こんにちは。Portable subtitle.')]
output = export_service.export_video(media, cues, 'libx264')
assert media_service.probe(output)['video']
muxed = export_service.export_video(media, cues, 'libx264', mode='mux')
assert media_service.probe(muxed)['video']
print('Subtitle burn-in and MKV mux passed', flush=True)
'''
    subprocess.run([str(bundle / 'runtime/bin/python3'), '-E', '-s', '-c', media_script, str(bundle)],
                   env=environment(), check=True, timeout=180)
    blocker = socket.socket()
    blocker.bind(('127.0.0.1', 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    if port > 65515:
        raise RuntimeError('Retry verification: ephemeral port is too high')
    log_path = work / 'server.log'
    process = None
    try:
        with log_path.open('w') as log:
            process = subprocess.Popen([str(bundle / 'Start-MediaTool.command'), '--no-browser', '--port', str(port)],
                                       env=environment(), stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(log_path.read_text())
                found = re.search(r'http://127\.0\.0\.1:\d+/', log_path.read_text())
                if found:
                    url = found.group()
                    try:
                        index = fetch(url).decode()
                        if '<html' in index:
                            break
                    except OSError:
                        pass
                time.sleep(.2)
            else:
                raise TimeoutError('Portable server did not start')
            assert f':{port}/' not in url
            asset = re.search(r'src="/([^\"]+\.js)"', index).group(1)
            assert fetch(url, asset)
            hw = json.loads(fetch(url, 'api/system/info'))
            assert hw['metal'] and hw['ffmpeg'] and hw['ffprobe']
            duplicate = launch(bundle, '--no-browser', capture_output=True, text=True, timeout=15)
            assert duplicate.returncode != 0 and 'already running' in duplicate.stderr
            subprocess.run([str(bundle / 'Stop-MediaTool.command')], env=environment(), check=True)
            assert process.wait(timeout=30) == 0
        report = {'passed': True, 'explicit_trust_flow_tested': True, 'first_runtime': first, 'relocated_runtime': second,
                  'hardware': hw, 'model_inference_tested': False}
        report_path = work / 'report.json'
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print('Portable relocation, runtime, Metal, video burn-in, HTTP, port conflict and shutdown passed.')
        print('Report:', report_path)
    finally:
        blocker.close()
        if process is not None and process.poll() is None:
            (bundle / 'stop.request').touch()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
