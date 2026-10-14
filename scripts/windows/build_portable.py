"""Build a Windows x64 distribution using the validated media-tool runtime."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / '.tools' / 'portable-build'
NAME = 'MediaTool-Portable-Windows-x64'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def clean_build_directory(path):
    resolved = path.resolve()
    if not resolved.is_relative_to(BUILD.resolve()) or resolved == BUILD.resolve():
        raise ValueError(f'Unsafe build cleanup path: {resolved}')
    if path.exists():
        shutil.rmtree(path)


def compress_runtime(path):
    # conda-pack stores rewritten unmanaged files (including large GPU DLLs).
    # Recompress those entries without changing their contents or metadata.
    with zipfile.ZipFile(path) as source:
        if not any(i.compress_type == zipfile.ZIP_STORED and i.file_size > 1_000_000 for i in source.infolist()):
            return
        temporary = path.with_suffix('.compressed.zip')
        print('Compressing bundled GPU/runtime files...', flush=True)
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
            for record in source.infolist():
                metadata = copy.copy(record)
                metadata.compress_type = zipfile.ZIP_DEFLATED
                with source.open(record) as input_file, target.open(metadata, 'w', force_zip64=True) as output_file:
                    shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reuse-runtime', action='store_true', help='Reuse already packed unchanged build environment')
    parser.add_argument('--include-models', action='store_true', help='Include project models cache for offline inference')
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.maxsize <= 2**32:
        raise RuntimeError('Build on Windows x64 in the media-tool environment')
    if Path(sys.prefix).name != 'media-tool':
        raise RuntimeError('Use conda run -n media-tool python scripts/windows/build_portable.py')
    BUILD.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(BUILD / 'pack-tools'))
    import conda_pack
    runtime_archive = BUILD / 'runtime.zip'
    if not args.reuse_runtime or not runtime_archive.exists():
        print('Packing private runtime, CPU/GPU libraries and licenses...', flush=True)
        conda_pack.pack(prefix=sys.prefix, output=str(runtime_archive), format='zip',
                        force=True, filters=[('exclude', '*.pyc'), ('exclude', '**/__pycache__/*')])
    compress_runtime(runtime_archive)
    subprocess.run(['npm.cmd', 'run', 'build'], cwd=ROOT / 'frontend', check=True)
    stage = BUILD / 'stage' / NAME
    clean_build_directory(stage)
    stage.mkdir(parents=True)
    shutil.copytree(ROOT / 'backend' / 'app', stage / 'backend' / 'app', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'frontend' / 'dist', stage / 'web')
    shutil.copyfile(runtime_archive, stage / 'runtime.zip')
    for source in (ROOT / 'scripts/windows/portable').iterdir():
        if source.is_file():
            shutil.copyfile(source, stage / source.name)
    shutil.copyfile(ROOT / 'scripts/common/launcher.py', stage / 'launcher.py')
    (stage / 'tools').mkdir()
    for name in ('ffmpeg.exe', 'ffprobe.exe'):
        shutil.copyfile(ROOT / '.tools' / 'ffmpeg' / 'bin' / name, stage / 'tools' / name)
    licenses = stage / 'licenses'
    licenses.mkdir()
    # The pinned Windows CTranslate2 wheel declares MIT but omits its text.
    shutil.copyfile(ROOT / 'docs/licenses/CTranslate2-4.6.2-LICENSE.txt', licenses / 'CTranslate2-4.6.2-LICENSE.txt')
    modules = ROOT / 'frontend' / 'node_modules'
    for source in modules.rglob('LICENSE*'):
        if source.is_file():
            target = licenses / 'frontend' / source.relative_to(modules)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    shutil.copyfile(ROOT / 'frontend' / 'package-lock.json', licenses / 'frontend-package-lock.json')
    for source in (ROOT / '.tools' / 'ffmpeg').glob('*/ffmpeg-*/LICENSE'):
        shutil.copyfile(source, licenses / 'FFmpeg-LICENSE.txt')
    for source in (ROOT / '.tools' / 'ffmpeg').glob('*/ffmpeg-*/README.txt'):
        shutil.copyfile(source, licenses / 'FFmpeg-README.txt')
    (stage / 'models').mkdir()
    if args.include_models:
        shutil.copytree(ROOT / 'models', stage / 'models', dirs_exist_ok=True)
    shutil.copyfile(ROOT / 'docs' / 'PORTABLE_QUICKSTART.md', stage / '使用说明.md')
    shutil.copyfile(ROOT / 'docs' / 'PORTABLE_NOTICES.md', licenses / 'THIRD_PARTY_NOTICES.md')
    manifest = {'format': 1, 'python': sys.version.split()[0], 'platform': 'Windows x64',
                'runtime_sha256': digest(runtime_archive), 'includes_models': args.include_models}
    (stage / 'bundle-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    destination = ROOT / 'release' / f'{NAME}.zip'
    destination.parent.mkdir(exist_ok=True)
    temporary = destination.with_suffix('.building.zip')
    print('Creating final distribution...', flush=True)
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for source in stage.rglob('*'):
            if source.is_file() or source.is_dir():
                relative = source.relative_to(stage.parent).as_posix()
                archive.write(source, relative, compress_type=zipfile.ZIP_STORED if source.suffix == '.zip' else zipfile.ZIP_DEFLATED)
    temporary.replace(destination)
    destination.with_suffix('.zip.sha256').write_text(f'{digest(destination)}  {destination.name}\n', encoding='ascii')
    print(f'Built {destination} ({destination.stat().st_size / 1024**3:.2f} GiB)', flush=True)


if __name__ == '__main__':
    main()
