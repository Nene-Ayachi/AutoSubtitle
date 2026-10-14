"""Source installation launcher. Requires a native Apple Silicon Python."""
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('请使用 Apple Silicon Mac 的原生 ARM64 Python，勿通过 Rosetta 启动。')
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise SystemExit('前端尚未构建，请先运行 scripts/macos/Setup-MediaTool.command。')
    import fcntl
    # Keep the descriptor open for the server lifetime; OS releases it on exit.
    with (ROOT / '.media-tool.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('此目录的 Media Tool 已经运行，请先停止现有实例。')
        sys.path.insert(0, str(ROOT / 'scripts/common'))
        import launcher
        launcher.ROOT = ROOT
        launcher.main()


if __name__ == '__main__':
    main()
