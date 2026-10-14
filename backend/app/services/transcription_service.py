import gc
import logging
import math
import time
from uuid import uuid4
from app.config import MODELS, PRESETS, CHUNK_SECONDS
from app.services import hardware_service, media_service, subtitle_service
from app.services.video_process import TaskControl
from app.services.export_service import remove_temporary

class TranscriptionService:
    def __init__(self):
        self.model = None
        self.key = None

    def unload(self):
        self.model = None
        self.key = None
        gc.collect()

    def transcribe(self, media, request, update, control=None):
        control = control or TaskControl(uuid4().hex, seal_on_process_exit=False)
        control.check()
        from faster_whisper import WhisperModel
        hw = hardware_service.info()
        control.check()
        device = ('cuda' if hw['cuda'] else 'cpu') if request.device == 'auto' else request.device
        model, preset_compute = PRESETS[request.quality]
        model = request.model or model
        compute = request.compute_type
        precision_notice = None
        if compute == 'auto':
            compute = preset_compute if device == 'cuda' else 'int8'
            supported = hw['compute_types'][device]
            if compute not in supported:
                replacement = next((c for c in ('int8_float16', 'float16', 'int8', 'float32') if c in supported), None)
                if replacement:
                    precision_notice = f'{device} 不支持预设精度 {compute}，自动精度使用 {replacement}；模型保持 {model}'
                    logging.warning(precision_notice)
                    compute = replacement
        if compute not in hw['compute_types'][device]:
            raise ValueError(f'{device} 不支持 {compute}，请选择自动或可用精度')
        key = (model, device, compute)
        raw_segments, language = [], request.language
        work = media['path'].parent / 'work' / control.task_id
        work.mkdir(parents=True, exist_ok=True)
        chunk = work / 'audio-chunk.wav'
        segments = None
        try:
            if self.key != key:
                control.check()
                self.unload()
                update('loading_model')
                try:
                    # Synchronous HF downloads/model constructors cannot be
                    # forcibly stopped safely. Keep cancelling until return.
                    self.model = WhisperModel(model, device=device, compute_type=compute, download_root=str(MODELS), local_files_only=not request.allow_download)
                    self.key = key
                except Exception as e:
                    control.check()
                    raise ValueError(f'模型加载/下载失败；首次使用请同意下载，离线时请检查缓存。{e}') from e
                control.check()
            started = time.perf_counter()
            for i in range(math.ceil(media['duration'] / CHUNK_SECONDS)):
                control.check()
                offset = i * CHUNK_SECONDS
                update('extracting_audio', offset / media['duration'])
                media_service.extract(media['path'], chunk, offset, CHUNK_SECONDS, control=control)
                control.check()
                update('transcribing', offset / media['duration'])
                segments, detected = self.model.transcribe(str(chunk), language=language, beam_size=request.beam_size, vad_filter=request.vad, word_timestamps=request.word_timestamps)
                control.check()
                language = language or detected.language
                iterator = iter(segments)
                while True:
                    control.check()
                    try:
                        segment = next(iterator)
                    except StopIteration:
                        break
                    control.check()
                    raw_segments.append(subtitle_service.snapshot(segment, offset))
                    update('transcribing', min(1, (offset + segment.end) / media['duration']))
                if hasattr(segments, 'close'):
                    segments.close()
                segments = None
            control.check()
            update('generating_subtitles')
            cleaned = subtitle_service.split_segments(raw_segments, language, media['duration'], check_cancel=control.check)
            control.check()
            elapsed = time.perf_counter() - started
            duration = media.get('audio_duration', media['duration'])
            metrics = {'model': model, 'device': device, 'compute_type': compute, 'duration': duration, 'elapsed': elapsed, 'rtf': elapsed/duration}
            logging.info('transcription %s', metrics)
            return {'cues': cleaned, 'language': language, 'metrics': metrics, 'message': precision_notice if cleaned else '没有检测到可识别语音', '_segments': raw_segments, '_edited': False}
        except Exception:
            self.unload()
            raise
        finally:
            try:
                if segments is not None and hasattr(segments, 'close'):
                    segments.close()
            finally:
                remove_temporary(chunk)
                try:
                    work.rmdir()
                except OSError:
                    logging.exception('识别任务临时目录清理失败：%s', work)
                    raise ValueError(f'识别临时目录清理失败，残留路径：{work}') from None
