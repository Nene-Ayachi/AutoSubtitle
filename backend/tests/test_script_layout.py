"""Keep moved entry points rooted in the project and platform templates separate."""
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('relative', [
    'scripts/windows/build_portable.py', 'scripts/windows/verify_portable.py',
    'scripts/macos/build_portable.py', 'scripts/macos/verify_portable.py',
    'scripts/macos/start.py',
])
def test_entry_point_root_is_independent_of_cwd(relative, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    module = runpy.run_path(str(ROOT / relative))
    assert module['ROOT'] == ROOT


def test_windows_assembly_uses_shared_launcher_and_release(tmp_path, monkeypatch):
    module = runpy.run_path(str(ROOT / 'scripts/windows/build_portable.py'))
    main = module['main']
    root = tmp_path / 'source'
    build = root / '.tools/portable-build'
    for relative, content in {
        'backend/app/__init__.py': '', 'frontend/dist/index.html': '<html>',
        'frontend/package-lock.json': '{}',
        'scripts/windows/portable/Start-MediaTool.cmd': 'windows startup',
        'scripts/common/launcher.py': 'shared launcher',
        '.tools/ffmpeg/bin/ffmpeg.exe': 'fixture', '.tools/ffmpeg/bin/ffprobe.exe': 'fixture',
        'docs/PORTABLE_QUICKSTART.md': 'usage', 'docs/PORTABLE_NOTICES.md': 'licenses',
        'docs/licenses/CTranslate2-4.6.2-LICENSE.txt': 'CTranslate2 MIT license',
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    main.__globals__['ROOT'] = root
    main.__globals__['BUILD'] = build
    def pack(**options):
        with zipfile.ZipFile(options['output'], 'w') as archive:
            archive.writestr('python.exe', 'fixture runtime')
    monkeypatch.setitem(sys.modules, 'conda_pack', SimpleNamespace(pack=pack))
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sys, 'prefix', str(tmp_path / 'media-tool'))
    monkeypatch.setattr(sys, 'argv', ['build_portable.py'])
    monkeypatch.setattr(main.__globals__['subprocess'], 'run', lambda *a, **k: None)
    main()
    archive = root / 'release/MediaTool-Portable-Windows-x64.zip'
    assert archive.exists() and archive.with_suffix('.zip.sha256').exists()
    with zipfile.ZipFile(archive) as package:
        prefix = 'MediaTool-Portable-Windows-x64/'
        assert package.read(prefix + 'launcher.py') == b'shared launcher'
        assert package.read(prefix + 'Start-MediaTool.cmd') == b'windows startup'
        assert package.read(prefix + 'runtime.zip')
        assert package.read(prefix + 'licenses/CTranslate2-4.6.2-LICENSE.txt') == b'CTranslate2 MIT license'
        assert not any(name.endswith('.command') for name in package.namelist())


@pytest.mark.parametrize('inside_workspace', [True, False])
def test_windows_verifier_rejects_unsafe_cache_before_cleanup(tmp_path, monkeypatch, inside_workspace):
    main = runpy.run_path(str(ROOT / 'scripts/windows/verify_portable.py'))['main']
    work = tmp_path / 'verification'
    work.mkdir()
    sentinel = work / 'keep.txt'
    sentinel.write_text('existing report')
    cache = work / 'models' if inside_workspace else tmp_path / 'missing-models'
    if inside_workspace:
        cache.mkdir()
    main.__globals__['WORK'] = work
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sys, 'argv', ['verify_portable.py', '--model-cache', str(cache)])
    with pytest.raises(ValueError, match='Model cache must exist outside'):
        main()
    assert sentinel.read_text() == 'existing report'
