import json
import subprocess
from pathlib import Path
from app.config import FFMPEG, FFPROBE

def run(args: list[str], cwd: Path | None = None, timeout: int | None = None):
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except FileNotFoundError:
        raise ValueError(f'找不到 {args[0]}，请安装或配置程序路径') from None
    if p.returncode:
        raise ValueError(f'{Path(args[0]).name} 处理失败：{p.stderr[-1500:]}')
    return p.stdout

def probe(path: Path, control=None):
    args = [FFPROBE, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]
    if control is None:
        data = json.loads(run(args, timeout=30))
    else:
        from app.services.video_process import run_video
        data = json.loads(run_video(args, path.parent, control, capture_stdout=True, timeout=30))
    streams = data.get('streams', [])
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    video = next((s for s in streams if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')), None)
    if not audio:
        raise ValueError('媒体没有音轨')
    duration = float(data.get('format', {}).get('duration', audio.get('duration', 0)))
    if duration <= 0:
        raise ValueError('无法读取有效媒体时长')
    audio_duration = float(audio.get('duration') or duration)
    return {'duration': duration, 'audio_duration': audio_duration, 'video': bool(video), 'width': video.get('width') if video else None, 'height': video.get('height') if video else None, 'hdr': bool(video and video.get('color_transfer') in ('smpte2084', 'arib-std-b67'))}

def extract(path: Path, out: Path, start: float, seconds: float, control=None):
    args = [FFMPEG, '-v', 'error', '-y', '-ss', str(start), '-i', str(path), '-t', str(seconds), '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(out)]
    if control is None:
        run(args)
    else:
        from app.services.video_process import run_video
        run_video(args, cwd=out.parent, control=control)
