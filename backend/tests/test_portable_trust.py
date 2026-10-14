"""Exercise the actual first-run shell with real macOS extended attributes."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='macOS extended attributes')
SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/macos/portable/首次信任并启动.command'
ATTRIBUTE = 'com.apple.quarantine'
VALUE = b'0081;test;MediaToolTrustTest;'


def set_attribute(path, name, value):
    subprocess.run(['/usr/bin/xattr', '-w', name, value.decode(), str(path)], check=True)


def get_attribute(path, name):
    return subprocess.check_output(['/usr/bin/xattr', '-p', name, str(path)]).rstrip(b'\n')


def attributes(path):
    return subprocess.check_output(['/usr/bin/xattr', str(path)], text=True).splitlines()


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / '中文 空格包'
    root.mkdir()
    for folder in ('runtime', 'tools', 'backend', 'web'):
        (root / folder).mkdir()
    for name in ('bundle-manifest.json', 'bootstrap.py', 'runtime/dependency.so'):
        (root / name).touch()
    (root / 'Start-MediaTool.command').write_text('#!/bin/bash\nprintf started > started.txt\n')
    shutil.copyfile(SCRIPT, root / SCRIPT.name)
    target = root / 'runtime/dependency.so'
    set_attribute(target, ATTRIBUTE, VALUE)
    set_attribute(target, 'com.example.mediatool.test', b'preserve')
    outside = tmp_path / 'outside'
    outside.mkdir()
    sentinel = outside / 'sentinel'
    sentinel.touch()
    set_attribute(sentinel, ATTRIBUTE, VALUE)
    (root / 'runtime/external-file').symlink_to(sentinel)
    (root / 'runtime/external-directory').symlink_to(outside, target_is_directory=True)
    return root, target, sentinel


def run(root, answer, *args):
    return subprocess.run(['/bin/bash', str(root / SCRIPT.name), *args], input=answer,
                          capture_output=True, text=True, timeout=15)


@pytest.mark.parametrize('answer', ['', '\n', 'no\n', 'trust\n'])
def test_without_explicit_consent_changes_nothing(bundle, answer):
    root, target, sentinel = bundle
    result = run(root, answer)
    assert result.returncode == 0, result.stderr
    assert '已取消' in result.stdout
    assert get_attribute(target, ATTRIBUTE) == VALUE
    assert get_attribute(sentinel, ATTRIBUTE) == VALUE
    assert not (root / 'started.txt').exists()


@pytest.mark.parametrize('trust_only', [True, False])
def test_consent_is_scoped_and_preserves_other_attributes(bundle, trust_only):
    root, target, sentinel = bundle
    args = ['--trust-only'] if trust_only else []
    result = run(root, 'TRUST\n', *args)
    assert result.returncode == 0, result.stderr
    assert str(root) in result.stdout
    assert ATTRIBUTE not in attributes(target)
    assert get_attribute(target, 'com.example.mediatool.test') == b'preserve'
    assert get_attribute(sentinel, ATTRIBUTE) == VALUE
    assert (root / 'started.txt').exists() == (not trust_only)
    assert run(root, 'TRUST\n', '--trust-only').returncode == 0


def test_incomplete_bundle_is_rejected_before_consent(bundle):
    root, target, _ = bundle
    (root / 'bundle-manifest.json').unlink()
    result = run(root, 'TRUST\n')
    assert result.returncode != 0
    assert get_attribute(target, ATTRIBUTE) == VALUE
    assert not (root / 'started.txt').exists()
