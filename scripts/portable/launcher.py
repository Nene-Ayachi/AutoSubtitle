"""Launcher executed by the bundle's private Python, never system Python."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parent


def configure():
    sys.path.insert(0, str(ROOT / 'backend'))
    for key, folder in (('DATA', 'data'), ('MODELS', 'models'), ('WEB', 'web')):
        location = ROOT / folder
        if key == 'WEB' and not location.exists():
            location = ROOT / 'frontend' / 'dist'
        os.environ[f'MEDIA_TOOL_{key}'] = str(location)
    for name in ('FFMPEG', 'FFPROBE'):
        executable = ROOT / 'tools' / (name.lower() + ('.exe' if sys.platform == 'win32' else ''))
        if executable.is_file():
            os.environ[f'MEDIA_TOOL_{name}'] = str(executable)
    for folder in ('data', 'models', 'logs'):
        (ROOT / folder).mkdir(exist_ok=True)


def bind_local(port):
    for candidate in range(port, port + 20):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Windows must not allow another process to share our listener.
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(('127.0.0.1', candidate))
            sock.listen(128)
            return sock
        except OSError:
            sock.close()
    raise RuntimeError('没有可用的本地端口，请关闭重复启动的程序后重试。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Check private runtime without starting a server')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    options = parser.parse_args()
    if not 1024 <= options.port <= 65515:
        parser.error('port must be between 1024 and 65515')
    configure()
    if options.check:
        import app  # Register bundled NVIDIA library directories first.
        import av
        import ctranslate2
        import faster_whisper
        import numpy
        from app.services.hardware_service import info
        from app.config import MODELS
        print(json.dumps({'python': sys.version, 'executable': sys.executable,
                          'prefix': sys.prefix, 'models': str(MODELS),
                          'libraries': {m.__name__: m.__file__ for m in (av, ctranslate2, faster_whisper, numpy)},
                          'hardware': info()}, ensure_ascii=False, indent=2))
        return
    import logging
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    handler = RotatingFileHandler(ROOT / 'logs' / 'media-tool.log', maxBytes=5_000_000, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.getLogger().addHandler(handler)
    import uvicorn
    sock = bind_local(options.port)
    url = f'http://127.0.0.1:{sock.getsockname()[1]}/'
    server = uvicorn.Server(uvicorn.Config('app.main:app', host='127.0.0.1', port=sock.getsockname()[1], workers=1))
    stop_file = ROOT / 'stop.request'
    stop_file.unlink(missing_ok=True)
    ended = threading.Event()
    def open_when_ready():
        while not server.started and not server.should_exit and not ended.is_set():
            time.sleep(.1)
        if server.started and not options.no_browser:
            webbrowser.open(url)
        while not ended.wait(.2):
            if stop_file.exists():
                server.should_exit = True
                return
    threading.Thread(target=open_when_ready, daemon=True).start()
    stop_name = 'Stop-MediaTool.cmd' if sys.platform == 'win32' else 'Stop-MediaTool.command'
    print(f'\nMedia Tool：{url}\n模型缓存：{ROOT / "models"}\n退出：按 Ctrl+C 或双击 {stop_name}。关闭浏览器不会停止后台任务。\n', flush=True)
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
        ended.set()
        stop_file.unlink(missing_ok=True)
        logging.getLogger().removeHandler(handler)
        handler.close()


if __name__ == '__main__':
    main()
