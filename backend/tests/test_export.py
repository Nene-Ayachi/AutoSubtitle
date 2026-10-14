import json
import shutil
from pathlib import Path
import pytest
from app.config import FFMPEG, FFPROBE
from app.schemas import Cue
from app.services import media_service, export_service

def test_mux_copies_packets_and_exports_edited_subtitles(tmp_path, monkeypatch):
    if not (Path(FFMPEG).is_file() or shutil.which(FFMPEG)):
        pytest.skip('实际封装测试需要 FFmpeg')
    source = tmp_path / '中文 视频.mp4'
    media_service.run([
        FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=size=320x240:rate=25',
        '-f', 'lavfi', '-i', 'sine=frequency=440', '-f', 'lavfi', '-i', 'sine=frequency=880',
        '-t', '1', '-map', '0:v', '-map', '1:a', '-map', '2:a',
        '-c:v', 'libx264', '-c:a', 'aac', str(source),
    ])
    def no_encoder_probe():
        raise AssertionError('外挂封装不得依赖视频编码器')
    monkeypatch.setattr('app.services.hardware_service.info', no_encoder_probe)
    cues = [Cue(id=1, start=0, end=.8, text='编辑后的字幕。こんにちは。Hello!')]
    output = export_service.export_video({'path': source, 'video': True, 'hdr': True}, cues, 'h264_nvenc', 'mux')
    assert output.suffix == '.mkv'
    def packets(path):
        data = json.loads(media_service.run([
            FFPROBE, '-v', 'error', '-show_packets', '-show_data_hash', 'sha256',
            '-show_entries', 'packet=stream_index,data_hash', '-of', 'json', str(path),
        ]))
        return {index: [p['data_hash'] for p in data['packets'] if p['stream_index'] == index] for index in range(3)}
    # Identical compressed packets prove video and both audio tracks were not re-encoded.
    assert packets(source) == packets(output)
    streams = json.loads(media_service.run([FFPROBE, '-v', 'error', '-show_streams', '-of', 'json', str(output)]))['streams']
    assert [s['codec_type'] for s in streams] == ['video', 'audio', 'audio', 'subtitle']
    assert streams[-1]['codec_name'] == 'subrip'
    extracted = media_service.run([FFMPEG, '-v', 'error', '-i', str(output), '-map', '0:s:0', '-f', 'srt', '-'])
    assert cues[0].text in extracted
    assert not list(tmp_path.glob('*.srt'))

def test_mux_failure_cleans_partial_files(tmp_path, monkeypatch):
    def fail(args, **kwargs):
        Path(args[-1]).write_bytes(b'incomplete')
        raise ValueError('封装失败')
    monkeypatch.setattr(export_service, 'run_video', fail)
    with pytest.raises(ValueError, match='封装失败'):
        export_service.export_video({'path': tmp_path/'source.mp4', 'video': True, 'hdr': False}, [], 'libx264', 'mux')
    assert not list(tmp_path.glob('*.mkv'))
    assert not list(tmp_path.glob('*.srt'))
    assert not list(tmp_path.rglob('*.mkv'))
    assert not list(tmp_path.rglob('*.srt'))
