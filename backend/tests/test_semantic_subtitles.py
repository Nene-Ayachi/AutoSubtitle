"""Synthetic timestamped fixtures: evaluate splitting, not ASR accuracy."""
import math
import re
from types import SimpleNamespace as NS
import pytest
from app.config import SubtitlePolicy
from app.services.subtitle_service import split_segment, split_segments, snapshot, txt, srt

CASES = [
    ('中文无标点长句', 'zh', '我觉得这个产品的实际表现还是非常不错的而且我们可以在日常工作中放心使用它'),
    ('中文固定搭配及数量词', 'zh', '这台设备每天可以处理三十个视频文件同时支持人工智能语音识别和字幕生成所以使用起来非常方便。'),
    ('日文助词与谓语', 'ja', 'この製品について詳しく調べてみると実際の性能は非常に良いと思いますが設定についてはもう少し説明してください。'),
    ('英文介词短语', 'en', 'We worked with the new team in the office and prepared the final report for our customers.'),
    ('混合文本', 'mixed', '这个工具支持 local speech recognition，而且日本語の字幕も編集できます，最后可以 export plain text。'),
    ('极短尾句', 'zh', '这个工具可以在本地完成语音识别和字幕编辑同时支持导出完整的纯文本内容结果很好'),
]

def make_segment(text, language='zh', step=None, pause_after=None):
    # CJK char-level Words model the important Whisper subword case.
    tokens = re.findall(r'\s*[A-Za-z0-9]+(?:[\x27-][A-Za-z0-9]+)*|\s*[^\sA-Za-z0-9]', text)
    words, time, consumed = [], 0.0, ''
    for token in tokens:
        duration = step if step is not None else (.38 if re.search('[A-Za-z]', token) else .14)
        time += (pause_after or {}).get(len(consumed), 0)
        words.append(NS(word=token,start=time,end=time+duration))
        time += duration
        consumed += token
    return NS(text=text,start=0,end=time,words=words)

def legacy_split(segment):
    """Frozen pre-change greedy algorithm, only for comparison documentation."""
    result, text, start, end = [], '', segment.words[0].start, segment.words[0].end
    for word in segment.words:
        if text and (len(text+word.word)>36 or word.end-start>7):
            result.append(NS(text=text.strip(),start=start,end=end))
            text,start='',word.start
        text+=word.word
        end=word.end
        if len(text.strip())>=8 and re.search(r'[。！？.!?]$',text.strip()):
            result.append(NS(text=text.strip(),start=start,end=end))
            text,start='',end
    if text.strip():result.append(NS(text=text.strip(),start=start,end=end))
    merged=[]
    for cue in result:
        if merged and (cue.end-cue.start<.65 or merged[-1].end-merged[-1].start<.65) and cue.start-merged[-1].end<=.4 and cue.end-merged[-1].start<=7 and len(merged[-1].text+cue.text)<=36:
            from app.services.subtitle_service import join_text
            merged[-1].text=join_text(merged[-1].text,cue.text)
            merged[-1].end=cue.end
        else:merged.append(cue)
    return [c.text for c in merged]

@pytest.mark.parametrize('name,language,text',CASES,ids=[c[0] for c in CASES])
def test_complete_text_and_real_word_boundaries(name,language,text):
    segment=make_segment(text,language)
    cues=split_segment(segment,10,1,language)
    assert txt(cues).rstrip('\n')==' '.join(text.split())
    assert len(cues)>1
    assert all(c.start in [10+w.start for w in segment.words] for c in cues)
    assert all(c.end in [10+w.end for w in segment.words] for c in cues)
    assert all(a.end<=b.start for a,b in zip(cues,cues[1:]))
    assert [c.model_dump() for c in cues]==[c.model_dump() for c in split_segment(segment,10,1,language)]

def test_chinese_semantic_boundary_and_fixed_phrases():
    segment=make_segment(CASES[0][2])
    cues=split_segment(segment,0,1,'zh')
    assert any(c.text.endswith('实际表现') for c in cues)
    assert any(c.text.startswith('还是') for c in cues)
    assert all(not c.text.endswith('而且') for c in cues)
    for phrase in ['实际表现','非常不错','这个产品','我觉得']:
        assert any(phrase in c.text for c in cues)

def test_chinese_number_classifier():
    cues=split_segment(make_segment(CASES[1][2]),0,1,'zh')
    for phrase in ['三十个','人工智能','语音识别','字幕生成']:
        assert any(phrase in c.text for c in cues)

def test_japanese_particles_and_predicates():
    cues=split_segment(make_segment(CASES[2][2]),0,1,'ja')
    for phrase in ['と思います','してください','実際の性能']:
        assert any(phrase in c.text for c in cues)
    assert all(not c.text.startswith(('は','が','を','に','で','と','の')) for c in cues)

def test_english_preposition_phrases():
    cues=split_segment(make_segment(CASES[3][2],'en'),0,1,'en')
    for phrase in ['with the new team','in the office','for our customers']:
        assert any(phrase in c.text for c in cues)
    assert all(not c.text.lower().endswith((' the',' with',' in',' for')) for c in cues)

def test_multiple_short_sentences_and_tiny_tail():
    text='好的。明白。我们现在开始介绍这个工具的实际使用方式。'
    cues=split_segment(make_segment(text),0,1,'zh')
    assert txt(cues).strip()==text
    assert all(len(c.text)>3 for c in cues)
    assert all(c.end-c.start>=.9 for c in cues)
    tail=split_segment(make_segment(CASES[-1][2]),0,1,'zh')
    assert len(tail[-1].text)>3

def test_pause_and_punctuation_disagree():
    text='We discussed the proposal in detail but decided to wait, before making a final choice.'
    pause=len('We discussed the proposal in detail')
    segment=make_segment(text,'en',pause_after={pause:1.4})
    cues=split_segment(segment,0,1,'en')
    assert any(c.text.endswith('detail') for c in cues)
    assert txt(cues).strip()==text

def test_near_limit_can_float_instead_of_tiny_remainder():
    text='我们已经完成这个产品的全部测试并且确认它的实际表现非常不错。'
    cues=split_segment(make_segment(text,step=.08),0,1,'zh',policy=SubtitlePolicy(target_chars=28,max_chars=30))
    assert all(len(c.text)>3 for c in cues)
    assert txt(cues).strip()==text

@pytest.mark.parametrize('problem',['missing','nan','overlap','text_mismatch'])
def test_explicit_fallback_preserves_segment(problem):
    segment=make_segment('原始识别文本必须完整保留。')
    if problem=='missing':segment.words=[]
    elif problem=='nan':segment.words[0].start=math.nan
    elif problem=='overlap':segment.words[1].start=0
    else:segment.words[0].word='不同的文本'
    cues=split_segment(segment,60,1,'zh')
    assert len(cues)==1 and cues[0].text==segment.text
    assert (cues[0].start,cues[0].end)==(60,60+segment.end)

def test_preserve_no_space_inside_english_and_mixed_text():
    text='支持OpenAI和GPT-4，Hello,world!'
    segment=make_segment(text)
    cues=split_segment(segment,0,1,'mixed',policy=SubtitlePolicy(target_chars=12,max_chars=18))
    assert txt(cues).strip()==text

def test_snapshot_and_resplit_do_not_depend_on_whisper_or_mutable_words():
    segment=make_segment(CASES[0][2])
    saved=snapshot(segment)
    first=split_segments([saved],'zh')
    segment.words[0].word='修改源对象'
    second=split_segments([saved],'zh')
    assert [c.model_dump() for c in first]==[c.model_dump() for c in second]
    second[0].text='人工校对后的文本'
    assert '人工校对后的文本' in txt(second) and '人工校对后的文本' in srt(second)
