import os
import sys
from dataclasses import dataclass
from pathlib import Path

def default_data_dir(platform=None):
    platform = platform or sys.platform
    if platform == 'darwin':
        return Path.home() / 'Library/Application Support/MediaTool'
    if platform == 'win32':
        return Path(os.getenv('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'media-tool'
    return Path(os.getenv('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'media-tool'

DATA = Path(os.getenv('MEDIA_TOOL_DATA', str(default_data_dir()))).resolve()
MODELS = Path(os.getenv('MEDIA_TOOL_MODELS', str(Path(__file__).resolve().parents[2] / 'models'))).resolve()
TOOLS = Path(__file__).resolve().parents[2] / '.tools' / 'ffmpeg' / 'bin'
def tool_path(name, platform=None):
    platform = platform or sys.platform
    filename = name + ('.exe' if platform == 'win32' else '')
    candidates = [TOOLS / filename]
    if platform == 'darwin':
        candidates += [Path(prefix) / 'bin' / name for prefix in
                       ('/opt/homebrew/opt/ffmpeg-full', '/usr/local/opt/ffmpeg-full', '/opt/homebrew', '/usr/local')]
    return next((str(p) for p in candidates if p.is_file()), name)

FFMPEG = os.getenv('MEDIA_TOOL_FFMPEG', tool_path('ffmpeg'))
FFPROBE = os.getenv('MEDIA_TOOL_FFPROBE', tool_path('ffprobe'))
FONT = os.getenv('MEDIA_TOOL_FONT', 'PingFang SC' if sys.platform == 'darwin' else 'Microsoft YaHei')
WEB = Path(os.environ['MEDIA_TOOL_WEB']).resolve() if os.getenv('MEDIA_TOOL_WEB') else None
@dataclass(frozen=True)
class SubtitlePolicy:
    target_chars: int
    max_chars: int
    min_seconds: float = 1.0
    max_seconds: float = 7.0
    silence_seconds: float = 0.45
    sentence_weight: float = 7.0
    clause_weight: float = 3.0
    semantic_weight: float = 5.0

SUBTITLE_POLICIES = {
    'zh': SubtitlePolicy(target_chars=22, max_chars=36),
    'ja': SubtitlePolicy(target_chars=20, max_chars=34, semantic_weight=6.0),
    'en': SubtitlePolicy(target_chars=48, max_chars=76),
    'mixed': SubtitlePolicy(target_chars=28, max_chars=44),
}
# Lightweight boundary hints, not a tokenizer: text is never rewritten.
CHINESE_PHRASES = (
    '实际表现', '非常不错', '我觉得', '这个产品', '人工智能', '语音识别',
    '与此同时', '总而言之', '不仅如此', '不可思议', '越来越', '高质量',
    '字幕生成', '字幕编辑', '纯文本', '时间戳', '本地处理', '没有问题',
)
CHINESE_STARTERS = ('还是', '但是', '不过', '因此', '所以', '然后', '而且', '同时', '如果', '虽然', '因为', '我们', '接下来')
CHINESE_DANGLING = ('的', '地', '得', '把', '被', '与', '和', '及', '或', '很', '非常', '更加', '这个', '那个', '而且', '但是', '所以', '然后', '因为', '虽然', '如果', '不过', '同时')
JAPANESE_PHRASES = ('と思います', 'と思う', 'してください', 'しています', 'している', 'できません', 'できます', 'ではありません', 'ではない', 'なければならない', 'ことができます', '実際の性能', '非常に良い', 'この製品', 'について', '調べてみる', 'もう少し', '説明してください')
JAPANESE_PARTICLES = ('は', 'が', 'を', 'に', 'で', 'と', 'の', 'も', 'へ', 'から', 'まで', 'より')
JAPANESE_STARTERS = ('しかし', 'それでも', 'そして', 'そのため', '一方', '次に')
ENGLISH_DANGLING = frozenset('a an the of in on at to for with from by into over under about as and or not very'.split())
ENGLISH_STARTERS = frozenset('and but however because while although therefore'.split())
CHUNK_SECONDS = 60
PRESETS = {'fast': ('small', 'int8'), 'balanced': ('large-v3-turbo', 'int8_float16'), 'quality': ('large-v3', 'float16')}
