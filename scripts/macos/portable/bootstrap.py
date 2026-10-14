"""Relocatable launcher using only the bundled Python and POSIX file lock."""
import fcntl
from pathlib import Path
import launcher

root = Path(__file__).resolve().parent
with (root / '.media-tool.lock').open('a') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Media Tool 已经运行 / already running，请先停止现有实例。')
    launcher.main()
