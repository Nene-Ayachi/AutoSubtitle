import functools
import json
import platform
import sys
from app.config import FFMPEG, FFPROBE
from app.services.media_service import run

@functools.lru_cache(maxsize=1)
def info():
    result = {'gpu': [], 'cuda': False, 'compute_types': {'cpu': ['int8'], 'cuda': []}, 'ffmpeg': False, 'ffprobe': False, 'encoders': ['libx264'], 'warnings': []}
    result['platform'] = sys.platform
    result['architecture'] = platform.machine()
    result['apple_silicon'] = sys.platform == 'darwin' and platform.machine().lower() == 'arm64'
    result['inference_note'] = 'Apple Silicon · ARM CPU 识别（当前后端不支持 Metal GPU）' if result['apple_silicon'] else ''
    try:
        if sys.platform == 'darwin':
            raise RuntimeError('CUDA is not available on macOS')
        lines = run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'], timeout=10)
        result['gpu'] = [{'name': line.rsplit(',', 1)[0].strip(), 'memory_mb': int(line.rsplit(',', 1)[1])} for line in lines.strip().splitlines()]
    except Exception:
        pass
    try:
        import ctranslate2
        result['compute_types']['cpu'] = sorted(ctranslate2.get_supported_compute_types('cpu'))
        if ctranslate2.get_cuda_device_count():
            result['compute_types']['cuda'] = sorted(ctranslate2.get_supported_compute_types('cuda'))
            result['cuda'] = True
    except Exception as e:
        result['warnings'].append(f'CTranslate2 检测失败：{e}')
    for name, exe in [('ffmpeg', FFMPEG), ('ffprobe', FFPROBE)]:
        try:
            run([exe, '-version'], timeout=10)
            result[name] = True
        except Exception as e:
            result['warnings'].append(str(e))
    if result['ffmpeg']:
        result['encoders'] = []
        candidates = ('libx264', 'h264_videotoolbox') if sys.platform == 'darwin' else ('libx264', 'h264_nvenc', 'hevc_nvenc')
        for encoder in candidates:
            try:
                options = ['-allow_sw', '0', '-b:v', '5M'] if encoder == 'h264_videotoolbox' else []
                run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'color=size=640x360:rate=1', '-frames:v', '1', '-c:v', encoder, *options, '-f', 'null', '-'], timeout=20)
                result['encoders'].append(encoder)
            except Exception as e:
                result['warnings'].append(f'{encoder} 实际编码检测未通过：{str(e)[:350]}')
    result['recommended_model'] = 'large-v3-turbo' if result['cuda'] else 'small'
    types = result['compute_types']['cuda'] if result['cuda'] else result['compute_types']['cpu']
    result['recommended_compute'] = next((c for c in ('int8_float16', 'int8', 'float16', 'float32') if c in types), 'auto')
    return result
