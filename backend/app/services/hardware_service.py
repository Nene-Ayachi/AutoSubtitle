import functools
import json
import platform
import sys
from app.config import FFMPEG, FFPROBE
from app.services.media_service import run

@functools.lru_cache(maxsize=1)
def info():
    result = {'gpu': [], 'cuda': False, 'metal': False, 'compute_types': {'cpu': ['int8'], 'cuda': [], 'metal': []}, 'ffmpeg': False, 'ffprobe': False, 'encoders': ['libx264'], 'warnings': []}
    result['platform'] = sys.platform
    result['architecture'] = platform.machine()
    result['apple_silicon'] = sys.platform == 'darwin' and platform.machine().lower() == 'arm64'
    result['inference_note'] = ''
    if result['apple_silicon']:
        try:
            import mlx.core as mx
            import mlx_whisper
            if not mx.metal.is_available():
                raise RuntimeError('Metal 设备不可用')
            with mx.stream(mx.gpu):
                probe = mx.array([1.0]) + 1
                mx.eval(probe)
            result['metal'] = True
            result['compute_types']['metal'] = ['float16', 'float32']
        except Exception as e:
            result['warnings'].append(f'Metal 检测失败，自动使用 CPU；请重新安装便携包或运行 scripts/macos/Setup-MediaTool.command 安装 MLX：{e}')
        result['inference_note'] = ('Apple Silicon · Metal GPU 识别（MLX）' if result['metal']
                                    else 'Apple Silicon · ARM CPU 识别（Metal 不可用）')
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
    result['recommended_model'] = 'large-v3-turbo' if result['cuda'] or result['metal'] else 'small'
    result['recommended_device'] = 'cuda' if result['cuda'] else ('metal' if result['metal'] else 'cpu')
    types = result['compute_types'][result['recommended_device']]
    result['recommended_compute'] = next((c for c in ('int8_float16', 'int8', 'float16', 'float32') if c in types), 'auto')
    return result
