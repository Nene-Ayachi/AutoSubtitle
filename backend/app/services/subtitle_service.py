import re
import logging
import math
from dataclasses import dataclass
from app.config import (
    SubtitlePolicy, SUBTITLE_POLICIES, CHINESE_PHRASES, CHINESE_STARTERS,
    CHINESE_DANGLING, JAPANESE_PHRASES, JAPANESE_PARTICLES,
    JAPANESE_STARTERS, ENGLISH_DANGLING, ENGLISH_STARTERS,
)
from app.schemas import Cue

def timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def validate(cues: list[Cue], duration: float):
    previous = 0.0
    ids = set()
    for cue in cues:
        if cue.id in ids or cue.start < previous - 0.0001 or cue.end > duration + 0.1:
            raise ValueError('字幕编号必须唯一，时间须有序、无重叠且不超过媒体时长')
        ids.add(cue.id)
        previous = cue.end

def srt(cues: list[Cue]) -> str:
    return '\n\n'.join(f'{i}\n{timestamp(c.start)} --> {timestamp(c.end)}\n{c.text.strip()}' for i, c in enumerate(cues, 1)) + ('\n' if cues else '')

def join_text(left: str, right: str) -> str:
    if not left:
        return right
    space = bool(re.search(r'[A-Za-z0-9.,!?]$', left) and re.match(r'[A-Za-z0-9]', right))
    return left + (' ' if space else '') + right

def txt(cues: list[Cue]) -> str:
    paragraphs: list[str] = []
    last = None
    for cue in cues:
        text = ' '.join(cue.text.split())
        if cue.group != last:
            paragraphs.append(text)
        else:
            paragraphs[-1] = (paragraphs[-1] + cue.join_before + text) if cue.join_before is not None else join_text(paragraphs[-1], text)
        last = cue.group
    return '\n'.join(paragraphs) + ('\n' if paragraphs else '')

@dataclass(frozen=True)
class WordData:
    word: str
    start: float | None
    end: float | None

@dataclass(frozen=True)
class SegmentData:
    text: str
    start: float
    end: float
    words: tuple[WordData, ...]

def snapshot(segment, offset: float = 0) -> SegmentData:
    """Keep only the inference data needed for repeatable splitting, not the model."""
    return SegmentData(segment.text, offset + segment.start, offset + segment.end, tuple(
        WordData(w.word, None if w.start is None else offset+w.start,
                 None if w.end is None else offset+w.end)
        for w in (segment.words or [])
    ))

def language_policy(text: str, language: str | None) -> SubtitlePolicy:
    if language in SUBTITLE_POLICIES:
        return SUBTITLE_POLICIES[language]
    if re.search(r'[ぁ-ゟァ-ヿ]', text):
        return SUBTITLE_POLICIES['ja']
    if re.search(r'[\u4e00-\u9fff]', text):
        return SUBTITLE_POLICIES['mixed' if re.search(r'[A-Za-z]', text) else 'zh']
    return SUBTITLE_POLICIES['en']

def _protected_boundaries(text: str) -> set[int]:
    protected = set()
    for phrase in CHINESE_PHRASES + JAPANESE_PHRASES:
        start = 0
        while (position := text.find(phrase, start)) != -1:
            protected.update(range(position+1, position+len(phrase)))
            start = position+1
    # Number + classifier/unit, including decimal values and common Chinese counts.
    for match in re.finditer(r'(?:\d+(?:[.,]\d+)?|[一二三四五六七八九十百千万两]+)\s*(?:个|位|名|台|次|分钟|小时|秒|公里|公斤|岁|年|月|日|円|枚|人|本|GB|MB|kg|km|%)', text):
        protected.update(range(match.start()+1, match.end()))
    return protected

def _boundary_score(text: str, position: int, gap: float, policy: SubtitlePolicy, protected: set[int]) -> float:
    left, right = text[:position].rstrip(), text[position:].lstrip()
    score = 0.0
    if re.search(r'[。！？!?](?:["”’」』）)]*)$', left) or re.search(r'(?<!\d)\.(?:["”’)]*)$', left):
        score += policy.sentence_weight
    elif re.search(r'[,，;；:：、]$', left):
        score += policy.clause_weight
    if gap >= policy.silence_seconds:
        score += policy.semantic_weight * min(3, gap/policy.silence_seconds)
    if position in protected:
        score -= policy.semantic_weight * 5
    if left and right:
        # Whisper may timestamp fragments of English words; never prefer these boundaries.
        if re.search(r'[A-Za-z0-9]$', left) and re.match(r'[A-Za-z0-9]', right) and not text[position:position+1].isspace():
            score -= policy.semantic_weight * 8
        if re.match(r'[,，。!?！？;；、）)」』]', right):
            score -= policy.semantic_weight * 5
        if right.startswith(CHINESE_STARTERS + JAPANESE_STARTERS):
            score = max(score, policy.semantic_weight)
        if left.endswith(CHINESE_DANGLING):
            score -= policy.semantic_weight * 1.5
        if right.startswith(JAPANESE_PARTICLES):
            score -= policy.semantic_weight * 2
        elif left.endswith(JAPANESE_PARTICLES):
            score += policy.semantic_weight * .35
        match = re.search(r'([A-Za-z]+)$', left)
        if match and match.group(1).lower() in ENGLISH_DANGLING:
            score -= policy.semantic_weight * 2
        next_word = re.match(r'([A-Za-z]+)\b', right)
        if next_word and next_word.group(1).lower() in ENGLISH_STARTERS:
            score += policy.semantic_weight * .7
    return score

def split_segment(segment, offset: float, group: int, language: str | None = None,
                  policy: SubtitlePolicy | None = None, check_cancel=None) -> list[Cue]:
    """Optimize the complete segment; every boundary uses actual word times."""
    text = ' '.join(segment.text.split())
    if not text:
        return []
    if not math.isfinite(segment.start) or not math.isfinite(segment.end) or segment.start < 0 or segment.end <= segment.start:
        raise ValueError('原始识别片段时间范围无效，无法安全生成字幕；没有丢弃其文本')
    words = segment.words or []
    valid = bool(words) and all(
        w.start is not None and w.end is not None and math.isfinite(w.start) and math.isfinite(w.end)
        and segment.start <= w.start < w.end <= segment.end + .1 and w.word.strip()
        for w in words
    )
    valid = valid and all(a.end <= b.start for a, b in zip(words, words[1:]))
    compact = ''.join(text.split())
    # Align word spans to the original text. Never silently replace Segment.text with Word.word.
    valid = valid and ''.join(''.join(w.word.split()) for w in words) == compact
    if not valid:
        logging.warning('Subtitle fallback group=%s: missing/invalid word timing or text mismatch; using original Segment boundary', group)
        return [Cue(id=1, group=group, start=offset+segment.start, end=offset+segment.end, text=text, join_before='')]

    positions = [i for i, char in enumerate(text) if not char.isspace()]
    spans, cursor = [], 0
    for word in words:
        count = len(''.join(word.word.split()))
        spans.append((positions[cursor], positions[cursor+count-1]+1))
        cursor += count
    policy = policy or language_policy(text, language)
    protected = _protected_boundaries(text)
    count = len(words)
    scores = [0.0] * (count+1)
    gaps = [0.0] * (count+1)
    for j in range(1, count):
        gaps[j] = words[j].start - words[j-1].end
        scores[j] = _boundary_score(text, spans[j-1][1], gaps[j], policy, protected)
    pause_costs = [0.0] * (count+1)
    for j in range(count):
        pause_costs[j+1] = pause_costs[j] + (policy.semantic_weight*gaps[j]/policy.silence_seconds if gaps[j] >= policy.silence_seconds else 0)

    # Dynamic programming balances ALL cues, including the final short remainder.
    costs, previous = [math.inf]*(count+1), [-1]*(count+1)
    costs[0] = 0.0
    for end in range(1, count+1):
        if check_cancel:
            check_cancel()
        for start in range(end-1, -1, -1):
            length = spans[end-1][1] - spans[start][0]
            duration = words[end-1].end - words[start].start
            # A single indivisible Word can exceed these limits; keep its real boundary.
            if end-start > 1 and (length > policy.max_chars*1.5 or duration > policy.max_seconds*1.5):
                break
            cost = 3 + 2*((length-policy.target_chars)/policy.target_chars)**2
            shortfall = max(0, (policy.min_seconds-duration)/policy.min_seconds)
            cost += 24*shortfall + 18*shortfall**2
            cost += 12*max(0, (policy.target_chars*.3-length)/(policy.target_chars*.3))**2
            cost += 16*max(0, (length-policy.max_chars)/policy.max_chars)**2
            cost += 20*max(0, (duration-policy.max_seconds)/policy.max_seconds)**2
            # Joining across a long silence is also penalized, even without punctuation.
            cost += pause_costs[end] - pause_costs[start+1]
            candidate = costs[start] + cost - (scores[end] if end < count else 0)
            if candidate < costs[end]:
                costs[end], previous[end] = candidate, start
    boundaries, end = [], count
    while end:
        start = previous[end]
        boundaries.append((start, end))
        end = start
    result, last_end = [], 0
    for start, end in reversed(boundaries):
        left, right = spans[start][0], spans[end-1][1]
        result.append(Cue(id=len(result)+1, group=group, start=offset+words[start].start,
                          end=offset+words[end-1].end, text=text[left:right],
                          join_before=text[last_end:left]))
        last_end = right
    return result

def split_segments(segments: list[SegmentData], language: str | None = None, duration: float | None = None, check_cancel=None) -> list[Cue]:
    result = []
    for group, segment in enumerate(segments, 1):
        if check_cancel:
            check_cancel()
        cues = split_segment(segment, 0, group, language, check_cancel=check_cancel)
        # Cross-Segment anomalies retain the transcript in an ordered fallback cue.
        for cue in cues:
            if duration is not None:
                cue.end = min(cue.end, duration)
                if cue.start >= cue.end:
                    continue
            if result and cue.start < result[-1].end:
                if cue.end <= result[-1].end:
                    result[-1].text = join_text(result[-1].text, cue.text)
                    continue
                cue.start = result[-1].end
            cue.id = len(result)+1
            result.append(cue)
    return result
