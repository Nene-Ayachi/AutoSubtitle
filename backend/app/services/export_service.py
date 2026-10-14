import time
import logging
from uuid import uuid4
from app.config import FFMPEG, FONT
from app.services import media_service, hardware_service, subtitle_service
from app.services.video_process import VideoControl, ExportCancelled, run_video

def remove_temporary(path):
    for attempt in range(3):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError:
            logging.exception('Export temporary file cleanup failed: %s', path)
            if attempt == 2:
                raise ValueError(f'导出临时文件清理失败，残留路径：{path}') from None
            time.sleep(.1)


def export_video(media, cues, encoder, mode='burn', control=None):
    control = control or VideoControl(uuid4().hex)
    control.check()
    if not media['video']:
        raise ValueError('音频文件不能导出字幕视频')
    if mode not in ('burn', 'mux'):
        raise ValueError('不支持的字幕视频导出方式')
    if mode == 'burn' and media['hdr']:
        raise ValueError('暂不支持 HDR 视频烧录；请先转换为 SDR')
    if mode == 'burn' and encoder not in hardware_service.info()['encoders']:
        raise ValueError('所选编码器未通过实际编码检测，请使用 H.264 CPU')
    directory = media['path'].parent / 'exports' / 'temp'
    directory.mkdir(parents=True, exist_ok=True)
    token = control.task_id
    subtitles = directory / f'{token}.srt'
    temporary = directory / f"{token}.{'mkv' if mode == 'mux' else 'mp4'}"
    output = directory.parent / temporary.name
    start = time.perf_counter()
    try:
        control.check()
        subtitles.write_text(subtitle_service.srt(cues), encoding='utf-8')
        if mode == 'mux':
            # Matroska supports SRT and common input codecs without video/audio encoding.
            run_video([
                FFMPEG, '-v', 'error', '-n',
                '-i', str(media['path']), '-i', str(subtitles),
                '-map', '0:V', '-map', '0:a?', '-map', '1:0',
                '-map_metadata', '0', '-map_chapters', '0',
                '-c', 'copy', '-c:s', 'srt',
                '-metadata:s:s:0', 'title=Media Tool subtitles',
                '-disposition:s:0', 'default', str(temporary),
            ], cwd=directory, control=control)
            logging.info('video_export mode=mux elapsed=%.3f', time.perf_counter()-start)
        else:
            style = f'FontName={FONT},FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=24'
            # Only a generated ASCII basename enters the filter expression; paths are argv entries.
            run_filter = f"subtitles={subtitles.name}:force_style='{style}'"
            encoder_options = ['-allow_sw', '0', '-b:v', '8M'] if encoder == 'h264_videotoolbox' else []
            run_video([FFMPEG, '-v', 'error', '-n', '-i', str(media['path']), '-map', '0:v:0', '-map', '0:a:0', '-vf', run_filter, '-c:v', encoder, *encoder_options, '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(temporary)], cwd=directory, control=control)
            logging.info('video_export encoder=%s elapsed=%.3f', encoder, time.perf_counter()-start)
        control.check()
        if not temporary.is_file() or temporary.stat().st_size == 0 or not media_service.probe(temporary)['video']:
            raise ValueError('视频导出结果验证失败')
        remove_temporary(subtitles)
        temporary.replace(output)
        return output
    except Exception:
        if control.cancel.is_set():
            raise ExportCancelled() from None
        raise
    finally:
        # run_video has waited for the encoder before either cleanup path.
        cleanup_error = None
        for path in (temporary, subtitles):
            try:
                remove_temporary(path)
            except ValueError as exc:
                cleanup_error = exc
        if cleanup_error:
            raise cleanup_error
