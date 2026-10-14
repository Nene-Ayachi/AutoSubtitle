"""MLX adapter; imported only after an Apple Metal device has been detected."""
from importlib import import_module
from types import SimpleNamespace

MODEL_REPOS = {
    'small': 'mlx-community/whisper-small-mlx',
    'medium': 'mlx-community/whisper-medium-mlx',
    'large-v3-turbo': 'mlx-community/whisper-large-v3-turbo',
    'large-v3': 'mlx-community/whisper-large-v3-mlx',
}


class MetalWhisperModel:
    def __init__(self, model, *, compute_type, download_root, local_files_only):
        import mlx.core as mx
        from huggingface_hub import snapshot_download

        self.mx = mx
        self.api = import_module('mlx_whisper.transcribe')
        self.fp16 = compute_type == 'float16'
        # Resolve locally first: mlx-whisper's own downloader has no offline flag.
        self.path = snapshot_download(
            MODEL_REPOS[model], cache_dir=str(download_root / 'mlx'),
            local_files_only=local_files_only,
            allow_patterns=['config.json', '*.safetensors', '*.npz'],
        )
        try:
            with mx.stream(mx.gpu):
                self.api.ModelHolder.get_model(self.path, mx.float16 if self.fp16 else mx.float32)
        except Exception:
            self.close()
            raise

    def close(self):
        # MLX Whisper caches globally, including across dtype changes.
        self.api.ModelHolder.model = None
        self.api.ModelHolder.model_path = None
        self.mx.clear_cache()

    def transcribe(self, path, *, language, beam_size, vad_filter, word_timestamps, check_cancel=lambda: None):
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import get_speech_timestamps

        check_cancel()
        audio = decode_audio(path, sampling_rate=16000)
        clips = [None]
        if vad_filter:
            speech = get_speech_timestamps(audio)
            if not speech:
                return iter(()), SimpleNamespace(language=language)
            # One interval per call: mlx-whisper 0.4.3 does not reset seek at
            # subsequent clip starts. Keep the original waveform/time origin.
            clips = [[span['start'] / 16000, span['end'] / 16000] for span in speech]
        output = []
        for clip in clips:
            check_cancel()
            options = {'clip_timestamps': clip} if clip is not None else {}
            with self.mx.stream(self.mx.gpu):
                result = self.api.transcribe(
                    audio, path_or_hf_repo=self.path, language=language,
                    fp16=self.fp16, word_timestamps=word_timestamps, verbose=None,
                    temperature=0.0,
                    **options,
                )
            check_cancel()
            language = language or result['language']
            output.extend(result['segments'])
        segments = [SimpleNamespace(
            start=s['start'], end=s['end'], text=s['text'],
            words=[SimpleNamespace(**w) for w in s.get('words', [])],
        ) for s in output]
        return iter(segments), SimpleNamespace(language=language)
