"""Build a self-contained Apple Silicon ZIP; never copy a developer virtualenv."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / '.tools' / 'portable-macos-build'
NAME = 'MediaTool-Portable-macOS-arm64'
PYTHON_URL = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261013/cpython-3.12.15%2B20261013-aarch64-apple-darwin-install_only_stripped.tar.gz'
PYTHON_SHA256 = '9866e11cf2ae9caa1e671383786f248859a52dd8bfb702fb4c0dc2c65f1d36de'
FFMPEG_BASE = 'https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, path, expected=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        print('Downloading', url, flush=True)
        temporary = path.with_suffix(path.suffix + '.part')
        subprocess.run(['/usr/bin/curl', '--fail', '--location', '--retry', '3',
                        '--connect-timeout', '30', '--max-time', '600', '--silent', '--show-error',
                        '--output', str(temporary), url], check=True)
        if expected and digest(temporary) != expected:
            raise RuntimeError(f'Checksum mismatch: {url}')
        temporary.replace(path)
    if expected and digest(path) != expected:
        raise RuntimeError(f'Checksum mismatch: {path}')
    return path


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def fresh(path):
    if not path.resolve().is_relative_to(BUILD.resolve()) or path.resolve() == BUILD.resolve():
        raise ValueError('Unsafe build cleanup')
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def audit_dependencies(stage):
    """Fail if native libraries rely on Homebrew, a developer path, or a newer OS."""
    records = []
    magics = {b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xfe\xed\xfa\xcf'}
    for path in stage.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open('rb') as stream:
            if stream.read(4) not in magics:
                continue
        commands = run(['/usr/bin/otool', '-arch', 'arm64', '-l', path], capture_output=True, text=True).stdout
        dependencies = re.findall(
            r'cmd LC_(?:LOAD_DYLIB|LOAD_WEAK_DYLIB|REEXPORT_DYLIB|LOAD_UPWARD_DYLIB)\s+cmdsize \d+\s+name (.*?) \(offset', commands)
        for dependency in dependencies:
            if dependency.startswith('/') and not dependency.startswith(('/usr/lib/', '/System/Library/')):
                raise RuntimeError(f'Nonportable native dependency in {path}: {dependency}')
        minimums = re.findall(r'\bminos (\d+\.\d+)', commands)
        minimums += re.findall(r'cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version (\d+\.\d+)', commands)
        if any(tuple(map(int, value.split('.'))) > (14, 0) for value in minimums):
            raise RuntimeError(f'Native library requires macOS newer than 14: {path}: {minimums}')
        records.append({'file': str(path.relative_to(stage)), 'dependencies': dependencies, 'minimum_macos': minimums})
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reuse-runtime', action='store_true')
    parser.add_argument('--include-models', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('Build on native Apple Silicon macOS')
    BUILD.mkdir(parents=True, exist_ok=True)
    cache = BUILD / 'downloads'
    runtime = BUILD / 'runtime'
    fingerprint = digest(ROOT / 'backend/requirements.txt') + ':mlx-0.29.3:macos14:python-' + PYTHON_SHA256
    marker = BUILD / 'runtime-fingerprint.txt'
    if not (args.reuse_runtime and marker.exists() and marker.read_text() == fingerprint and runtime.exists()):
        archive = download(PYTHON_URL, cache / 'python.tar.gz', PYTHON_SHA256)
        unpack = BUILD / 'unpack-python'
        fresh(unpack)
        with tarfile.open(archive) as source:
            source.extractall(unpack, filter='data')
        fresh(runtime)
        shutil.copytree(unpack / 'python', runtime, dirs_exist_ok=True, symlinks=True)
        constraints = BUILD / 'constraints.txt'
        constraints.write_text('mlx==0.29.3\n', encoding='utf-8')
        # Resolve only wheels usable on macOS 14, even when building on a newer Mac.
        run([runtime / 'bin/python3', '-m', 'pip', 'install', '--disable-pip-version-check',
             '--only-binary=:all:', '--platform', 'macosx_14_0_arm64', '--python-version', '3.12',
             '--implementation', 'cp', '--abi', 'cp312', '--no-compile',
             '--target', runtime / 'lib/python3.12/site-packages',
             '--report', BUILD / 'pip-report.json', '-c', constraints, '-r', ROOT / 'backend/requirements.txt'])
        marker.write_text(fingerprint)
    run(['npm', 'run', 'build'], cwd=ROOT / 'frontend')
    stage = BUILD / 'stage' / NAME
    fresh(stage)
    shutil.copytree(runtime, stage / 'runtime', symlinks=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'backend/app', stage / 'backend/app', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'frontend/dist', stage / 'web')
    shutil.copyfile(ROOT / 'scripts/common/launcher.py', stage / 'launcher.py')
    for source in (ROOT / 'scripts/macos/portable').iterdir():
        if not source.is_file():
            continue
        shutil.copyfile(source, stage / source.name)
        if source.suffix == '.command':
            (stage / source.name).chmod(0o755)
    (stage / 'tools').mkdir()
    licenses = stage / 'licenses'
    licenses.mkdir()
    media_checksums = {}
    for name in ('ffmpeg', 'ffprobe'):
        checksum_file = download(FFMPEG_BASE + name + '.zip.sha256', cache / (name + '.zip.sha256'))
        expected = checksum_file.read_text().split()[0]
        archive = download(FFMPEG_BASE + name + '.zip', cache / (name + '.zip'), expected)
        media_checksums[name] = expected
        with zipfile.ZipFile(archive) as source:
            entries = [i for i in source.infolist() if Path(i.filename).name == name and not i.is_dir() and '__MACOSX' not in i.filename]
            if len(entries) != 1:
                raise RuntimeError(f'Unexpected {name} archive layout')
            (stage / 'tools' / name).write_bytes(source.read(entries[0]))
        (stage / 'tools' / name).chmod(0o755)
    version = run([stage / 'tools/ffmpeg', '-version'], capture_output=True, text=True).stdout
    if '--enable-nonfree' in version or '--enable-libass' not in version or '--enable-libx264' not in version:
        raise RuntimeError('FFmpeg must support libass/x264 and be redistributable')
    (licenses / 'FFmpeg-build.txt').write_text(version)
    (licenses / 'FFmpeg-license.txt').write_text(run([stage / 'tools/ffmpeg', '-L'], capture_output=True, text=True).stdout)
    shutil.copyfile(ROOT / 'docs/PORTABLE_MACOS_NOTICES.md', licenses / 'THIRD_PARTY_NOTICES.md')
    shutil.copyfile(BUILD / 'pip-report.json', licenses / 'python-packages.json')
    for source in (ROOT / 'frontend/node_modules').rglob('LICENSE*'):
        if source.is_file():
            target = licenses / 'frontend' / source.relative_to(ROOT / 'frontend/node_modules')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    shutil.copyfile(ROOT / 'frontend/package-lock.json', licenses / 'frontend-package-lock.json')
    for folder in ('models', 'data', 'logs'):
        (stage / folder).mkdir()
    if args.include_models:
        shutil.copytree(ROOT / 'models', stage / 'models', dirs_exist_ok=True)
    shutil.copyfile(ROOT / 'docs/PORTABLE_MACOS_QUICKSTART.md', stage / '使用说明.md')
    manifest = {'format': 1, 'platform': 'macOS arm64', 'minimum_macos': '14.0',
                'python_source': PYTHON_URL, 'python_sha256': PYTHON_SHA256,
                'ffmpeg_source': FFMPEG_BASE, 'ffmpeg_archive_sha256': media_checksums,
                'includes_models': args.include_models, 'mlx': '0.29.3',
                'native_dependencies': audit_dependencies(stage)}
    (stage / 'bundle-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    destination = ROOT / 'release' / (NAME + '.zip')
    destination.parent.mkdir(exist_ok=True)
    temporary = destination.with_suffix('.building.zip')
    temporary.unlink(missing_ok=True)
    # ditto preserves executable modes, symlinks and macOS metadata for Finder unzip.
    run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', stage, temporary])
    temporary.replace(destination)
    destination.with_suffix('.zip.sha256').write_text(f'{digest(destination)}  {destination.name}\n')
    print(f'Built {destination} ({destination.stat().st_size / 1024**2:.1f} MiB)', flush=True)


if __name__ == '__main__':
    main()
