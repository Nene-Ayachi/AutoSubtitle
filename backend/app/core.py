import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from app.services.transcription_service import TranscriptionService
from app.services.video_process import VideoControl, ExportCancelled

class Store:
    def __init__(self):
        self.media = {}
        self.tasks = {}
        self.video_controls = {}
        self.controls = {}
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='media-worker')
        self.ai = TranscriptionService()

    def submit(self, kind, media_id, action, controlled=False):
        with self.lock:
            for task in self.tasks.values():
                if task['kind'] == kind and task['media_id'] == media_id and task['status'] in ('pending', 'processing', 'cancelling'):
                    raise ValueError('该媒体已有同类任务正在等待或处理')
            task_id = uuid4().hex
            task = {'id': task_id, 'kind': kind, 'media_id': media_id, 'status': 'pending', 'stage': None, 'progress': None, 'error': None}
            self.tasks[task_id] = task
            control = VideoControl(task_id, self.lock, seal_on_process_exit=kind == 'video')
            self.controls[task_id] = control
            if kind == 'video':
                self.video_controls[task_id] = control
        def work():
            def update(stage, progress=None):
                with self.lock:
                    if task['status'] != 'cancelling':
                        task.update(stage=stage, progress=progress)
                        control.stage = stage
                control.check()
            with self.lock:
                if task['status'] == 'cancelled':
                    return
                task['status'] = 'processing'
            try:
                control.check()
                result = action(update, control) if kind == 'video' or controlled else action(update)
                with self.lock:
                    control.check()
                    control.finished = True
                    task.update(status='completed', result=result, progress=1)
            except ExportCancelled:
                with self.lock:
                    task.update(status='cancelled', stage='cancelled', error=None)
            except Exception as e:
                message = str(e)
                if 'out of memory' in message.lower():
                    message = 'GPU 显存不足，请选择 small/int8 或 CPU 后重试'
                with self.lock:
                    if control.cancel.is_set() and '清理失败' not in message:
                        logging.info('Task %s cancelled after current operation returned', task_id)
                        task.update(status='cancelled', stage='cancelled', error=None)
                    else:
                        logging.exception('Task %s failed', task_id)
                        task.update(status='failed', error=message[:1800], progress=None)
                    if control.cancel.is_set() and task['status'] == 'failed':
                        task['stage'] = 'cancel_cleanup_failed'
            finally:
                with self.lock:
                    self.video_controls.pop(task_id, None)
                    self.controls.pop(task_id, None)
                    if control:
                        control.future = None
        with self.lock:
            initial = task.copy()
            future = self.pool.submit(work)
            if control:
                control.future = future
        return initial

    def cancel_video(self, task_id):
        with self.lock:
            if self.tasks[task_id]['kind'] != 'video':
                raise ValueError('该任务不是视频导出任务')
            return self.cancel_task(task_id)

    def cancel_task(self, task_id):
        with self.lock:
            task = self.tasks[task_id]
            if task['status'] in ('completed', 'failed', 'cancelled', 'cancelling'):
                return task.copy()
            control = self.controls.get(task_id)
            if control is None:
                raise ValueError('任务缺少进程控制信息，无法取消')
            if not control.request_cancel():
                task['stage'] = 'finalizing'
                return task.copy()
            if task['status'] == 'pending':
                task.update(status='cancelled', stage='cancelled')
                if control.future:
                    control.future.cancel()
                self.video_controls.pop(task_id, None)
                self.controls.pop(task_id, None)
                control.future = None
            else:
                stage = 'cancelling'
                if task['kind'] == 'transcription':
                    stage = {'loading_model': 'cancel_wait_model', 'transcribing': 'cancel_wait_inference',
                             'generating_subtitles': 'cancel_subtitles', 'extracting_audio': 'cancel_ffmpeg'}.get(control.stage, 'cancelling')
                task.update(status='cancelling', stage=stage)
            return task.copy()

store = Store()
