"""Per-export process ownership; no process-name based termination."""
import logging
import subprocess
import tempfile
import threading
import time
from pathlib import Path


class ExportCancelled(Exception):
    pass

TaskCancelledError = ExportCancelled


class VideoControl:
    def __init__(self, task_id, lock=None, seal_on_process_exit=True):
        self.task_id = task_id
        self.lock = lock or threading.RLock()
        self.cancel = threading.Event()
        self.process = None
        self.finished = False
        self.future = None
        self.seal_on_process_exit = seal_on_process_exit
        self.stage = None

    def request_cancel(self):
        # An observed process exit wins over a later cancellation request.
        with self.lock:
            if self.finished or (self.seal_on_process_exit and self.process is not None and self.process.poll() is not None):
                self.finished = True
                return False
            self.cancel.set()
            return True

    def check(self):
        if self.cancel.is_set():
            raise ExportCancelled()


def stop_process(process):
    # FFmpeg's stdin 'q' provides graceful shutdown on Windows too. Windows
    # terminate/kill both use TerminateProcess, not POSIX SIGTERM/SIGKILL.
    if process.poll() is not None:
        return
    try:
        process.stdin.write(b'q\n')
        process.stdin.flush()
    except (OSError, ValueError, AttributeError):
        pass
    try:
        process.wait(timeout=1.5)
        return
    except subprocess.TimeoutExpired:
        pass
    for method in (process.terminate, process.kill):
        try:
            method()
            process.wait(timeout=2)
            return
        except (OSError, subprocess.TimeoutExpired):
            logging.exception('FFmpeg termination attempt failed pid=%s', process.pid)
    # Never clean files or report cancelled while FFmpeg still owns them.
    # Keep this worker/handle alive and retry; the HTTP cancel route never waits.
    while process.poll() is None:
        logging.error('FFmpeg still alive after cancellation pid=%s; retrying', process.pid)
        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            time.sleep(.5)


TaskControl = VideoControl


def run_video(args, cwd, control, capture_stdout=False, timeout=None):
    control.check()
    # File-backed logs cannot fill a pipe and deadlock an encoder. stdout is unused.
    with tempfile.TemporaryFile() as errors, tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(
                args, cwd=cwd, stdin=subprocess.PIPE, stdout=output if capture_stdout else subprocess.DEVNULL,
                stderr=errors, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except FileNotFoundError:
            raise ValueError(f'找不到 {args[0]}，请安装或配置程序路径') from None
        with control.lock:
            control.process = process
        try:
            deadline = time.monotonic() + timeout if timeout else None
            while True:
                with control.lock:
                    cancelled = control.cancel.is_set()
                    code = process.poll()
                    if not cancelled and code is not None and control.seal_on_process_exit:
                        control.finished = True
                if cancelled:
                    stop_process(process)
                    raise ExportCancelled()
                if code is not None:
                    break
                if deadline and time.monotonic() >= deadline:
                    raise ValueError(f'{Path(args[0]).name} 处理超时')
                control.cancel.wait(.05)
            process.wait()
            if code:
                errors.seek(0, 2)
                errors.seek(max(0, errors.tell() - 6000))
                message = errors.read().decode('utf-8', errors='replace')[-1500:]
                raise ValueError(f'{Path(args[0]).name} 处理失败：{message}')
            if capture_stdout:
                output.seek(0)
                return output.read().decode('utf-8', errors='replace')
        finally:
            if process.poll() is None:
                stop_process(process)
            process.wait()
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    logging.exception('FFmpeg stdin close failed pid=%s', process.pid)
            with control.lock:
                control.process = None
