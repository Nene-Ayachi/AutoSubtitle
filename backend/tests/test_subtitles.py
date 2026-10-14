from types import SimpleNamespace as NS
import pytest
from pydantic import ValidationError
from app.schemas import Cue, TranscriptionRequest
from app.services.subtitle_service import timestamp, txt, srt, split_segment, validate

def cue(**changes):
    return Cue(**({'id':1,'group':1,'start':1.2,'end':3.8,'text':'大家好。'} | changes))

@pytest.mark.parametrize('seconds,expected', [(1.2,'00:00:01,200'), (59.9996,'00:01:00,000'), (3661.002,'01:01:01,002')])
def test_timestamp(seconds, expected):
    assert timestamp(seconds) == expected

def test_utf8_and_paragraphs():
    cues = [cue(text='大家好'),cue(id=2,start=4,end=5,text='，欢迎。'),cue(id=3,group=2,start=6,end=7,text='こんにちは。'),cue(id=4,group=3,start=8,end=9,text='Hello'),cue(id=5,group=3,start=10,end=11,text='world!')]
    text = txt(cues)
    assert text.encode('utf-8').decode('utf-8') == '大家好，欢迎。\nこんにちは。\nHello world!\n'
    assert '-->' not in text and '00:' not in text

def test_edit_sync_and_time_independence():
    c = cue()
    c.text='修改后的内容。'
    before=txt([c])
    assert c.text in srt([c]) and c.text in before
    c.start=2
    c.end=4
    assert txt([c]) == before
    assert '00:00:02,000 --> 00:00:04,000' in srt([c])

def test_srt_format():
    assert srt([cue()]) == '1\n00:00:01,200 --> 00:00:03,800\n大家好。\n'
    assert srt([]) == '' and txt([]) == ''

def test_split_uses_words_and_preserves_group():
    from app.config import SubtitlePolicy
    words = [NS(word='这是一个较长的中文字幕片段',start=1,end=2), NS(word='第二部分继续说一些内容',start=3,end=4), NS(word='最后的部分结束。',start=5,end=6)]
    result = split_segment(NS(start=1,end=6,text=''.join(w.word for w in words),words=words),60,7,policy=SubtitlePolicy(target_chars=16,max_chars=20))
    assert len(result)==3
    assert result[0].start==61 and result[0].end==62
    assert result[1].start==63 and result[1].end==64
    assert result[2].start==65 and result[2].end==66
    assert all(c.group==7 for c in result)

def test_bad_words_preserve_original_boundary():
    result=split_segment(NS(start=2,end=9,text='原始片段',words=[NS(start=0,end=0,word='坏')]),60,1)
    assert (result[0].start,result[0].end)==(62,69)

@pytest.mark.parametrize('change', [{'end':1}, {'text':' '}, {'start':float('nan')}])
def test_bad_cue(change):
    with pytest.raises(ValidationError):cue(**change)

def test_overlap():
    with pytest.raises(ValueError):validate([cue(),cue(id=2,start=3,end=5)],10)
    with pytest.raises(ValueError):validate([cue(end=11)],10)

def test_invalid_options():
    with pytest.raises(ValidationError):TranscriptionRequest(media_id='x',beam_size=0)
    with pytest.raises(ValidationError):TranscriptionRequest(media_id='x',device='remote')
