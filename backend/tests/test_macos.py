from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from app import config
from app.schemas import ExportRequest, Cue
from app.services import hardware_service, export_service


def test_platform_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    assert config.default_data_dir('darwin') == tmp_path / 'Library/Application Support/MediaTool'
    monkeypatch.setattr(config, 'TOOLS', tmp_path)
    (tmp_path / 'ffmpeg.exe').touch()
    assert config.tool_path('ffmpeg', 'win32') == str(tmp_path / 'ffmpeg.exe')
    (tmp_path / 'ffmpeg').touch()
    assert config.tool_path('ffmpeg', 'darwin') == str(tmp_path / 'ffmpeg')


@pytest.mark.parametrize('available', [True, False])
def test_apple_hardware_only_advertises_working_encoders(monkeypatch, available):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert args[0] != 'nvidia-smi'
        if 'h264_videotoolbox' in args:
            assert args[args.index('-allow_sw') + 1] == '0'
            if not available:
                raise ValueError('unavailable')
        return ''
    monkeypatch.setattr(hardware_service.sys, 'platform', 'darwin')
    monkeypatch.setattr(hardware_service.platform, 'machine', lambda: 'arm64')
    monkeypatch.setitem(sys.modules, 'ctranslate2', SimpleNamespace(
        get_supported_compute_types=lambda device: {'float32'}, get_cuda_device_count=lambda: 0))
    monkeypatch.setattr(hardware_service, 'run', run)
    hardware_service.info.cache_clear()
    try:
        result = hardware_service.info()
        assert result['apple_silicon'] and not result['cuda']
        assert result['recommended_compute'] == 'float32'
        assert ('h264_videotoolbox' in result['encoders']) == available
        assert not any('nvenc' in str(args) for args in calls)
    finally:
        hardware_service.info.cache_clear()


def test_videotoolbox_export_parameters_and_cleanup(tmp_path, monkeypatch):
    request = ExportRequest(encoder='h264_videotoolbox')
    monkeypatch.setattr(hardware_service, 'info', lambda: {'encoders': [request.encoder]})
    monkeypatch.setattr(export_service.media_service, 'probe', lambda path: {'video': True})
    def run(args, **kwargs):
        assert args[args.index('-c:v') + 1] == request.encoder
        assert args[args.index('-allow_sw') + 1] == '0'
        assert '-b:v' in args and '-vf' in args
        Path(args[-1]).write_bytes(b'validated by probe stub')
    monkeypatch.setattr(export_service, 'run_video', run)
    output = export_service.export_video(
        {'path': tmp_path / '原始.mp4', 'video': True, 'hdr': False},
        [Cue(id=1, start=0, end=1, text='字幕')], request.encoder)
    assert output.is_file()
    assert not list((tmp_path / 'exports/temp').iterdir())
