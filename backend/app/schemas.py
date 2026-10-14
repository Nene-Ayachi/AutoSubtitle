from typing import Literal
from pydantic import BaseModel, Field, model_validator, ConfigDict

class Cue(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    id: int = Field(ge=1)
    group: int = Field(default=1, ge=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=10000)
    # Exact original separator between display cues in the same paragraph.
    join_before: str | None = Field(default=None, max_length=100)

    @model_validator(mode='after')
    def valid(self):
        if self.end <= self.start or not self.text.strip():
            raise ValueError('字幕结束必须晚于开始，文本不能为空')
        self.text = '\n'.join(line.strip() for line in self.text.splitlines() if line.strip())
        return self

class TranscriptionRequest(BaseModel):
    media_id: str
    quality: Literal['fast', 'balanced', 'quality'] = 'balanced'
    model: Literal['small', 'medium', 'large-v3-turbo', 'large-v3'] | None = None
    device: Literal['auto', 'cuda', 'cpu'] = 'auto'
    compute_type: Literal['auto', 'float16', 'int8_float16', 'int8', 'float32'] = 'auto'
    language: Literal['zh', 'ja', 'en'] | None = None
    beam_size: int = Field(default=5, ge=1, le=10)
    vad: bool = True
    word_timestamps: bool = True
    allow_download: bool = False

class EditRequest(BaseModel):
    cues: list[Cue]

class ExportRequest(BaseModel):
    mode: Literal['burn', 'mux'] = 'burn'
    encoder: Literal['libx264', 'h264_nvenc', 'hevc_nvenc', 'h264_videotoolbox'] = 'libx264'

class MediaInfo(BaseModel):
    id: str
    name: str
    size: int
    duration: float
    audio_duration: float | None = None
    video: bool
    width: int | None = None
    height: int | None = None
    hdr: bool

class TaskInfo(BaseModel):
    id: str
    kind: Literal['transcription', 'video']
    media_id: str
    status: Literal['pending', 'processing', 'cancelling', 'cancelled', 'completed', 'failed']
    stage: str | None = None
    progress: float | None = None
    error: str | None = None
    output_format: Literal['mp4', 'mkv'] | None = None

class TranscriptionResult(BaseModel):
    cues: list[Cue]
    language: str | None = None
    metrics: dict
    message: str | None = None
    text: str
