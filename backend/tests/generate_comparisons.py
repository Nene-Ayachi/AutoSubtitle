"""Reproduce old/new comparisons without loading or invoking an ASR model."""
from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

fixtures = runpy.run_path(str(Path(__file__).with_name('test_semantic_subtitles.py')))
from app.services.subtitle_service import split_segment
from app.config import SUBTITLE_POLICIES

lines = [
    '# 字幕语义断句优化与对比', '',
    '以下是合成词时间戳夹具上的实际算法输出；旧算法为修改前的 36 字/7 秒贪心版本，新算法为当前实现。它们用于验证规则，不是对真实语音识别准确率的测量。` / ` 表示字幕边界，原始文字没有改写。', '',
    '| 场景 | 旧算法 | 新算法 |', '|---|---|---|',
]
for name, language, text in fixtures['CASES']:
    segment = fixtures['make_segment'](text, language)
    old = ' / '.join(fixtures['legacy_split'](segment))
    new = ' / '.join(c.text for c in split_segment(segment, 0, 1, language))
    lines.append(f'| {name} | {old} | {new} |')
lines += [
    '', '## 选择断点', '',
    '在实际 Word 边界上建立候选位置，为句末标点、逗号/分号、停顿和语言边界评分。对拆开已知中文搭配、数量词、日文谓语/助词以及英文单词、冠词/介词后切分进行惩罚。动态规划比较整个 Segment 的多种方案，联合考虑长度、持续时间、长静音与极短尾句，而非达到固定字数立刻截断。', '',
    '每条字幕使用对应首词 start、末词 end；标点后有停顿时，不再把下一条开始时间提前到上一词结束。词时间戳缺失、非有限数、顺序重叠，或 Word 文本无法与 Segment.text 对齐时，保留原始 Segment 边界和文本，不估算比例时间。原 Segment 自身没有合法时间范围时明确报错，避免静默丢弃内容。跨 Segment 重叠会夹紧开始时间；完全被上一条时间覆盖的文本按顺序合并到前一条。', '',
    '切分保持原始文本中字幕之间的空格，通过 Cue.join_before 保存；group 保留原片段段落归属。TXT 和前端纯文本都使用同一组数据，因此字幕边界不会凭空增加空格、丢掉标点或改变段落。沿用原来的空白规范化，未进行中文分词改写、标点补写或语言润色。', '',
    '## 集中参数（config.py）', '',
    '| 语言 | 目标字数 | 最大字数参考 | 最短时长 | 最长时长参考 | 静音阈值 | 句末/句中标点权重 | 语义权重 |',
    '|---|---:|---:|---:|---:|---:|---|---:|',
]
for language, policy in SUBTITLE_POLICIES.items():
    lines.append(f'| {language} | {policy.target_chars} | {policy.max_chars} | {policy.min_seconds}s | {policy.max_seconds}s | {policy.silence_seconds}s | {policy.sentence_weight}/{policy.clause_weight} | {policy.semantic_weight} |')
lines += [
    '', '最大长度/时长是评分参考，可在 1.5 倍候选窗口内浮动；单个不可分的 Word 或异常时保留的原 Segment 可能更长。最短时长是强惩罚项，不通过人为延长时间来强制达标。短于最低时长的独立原 Segment 不跨段强行合并。规则短语与语言边界配置也集中在 config.py。', '',
    '## 无需重复识别', '',
    '新识别任务将纯数据的原始片段/词时间戳保存在内存中，与模型对象解耦。`POST /api/tasks/{task_id}/subtitles/resplit` 使用这些数据重新切分，不调用 faster-whisper、不下载模型。已人工修改的结果返回 409，避免覆盖校对内容；旧版任务没有保存词数据或应用重启后无法恢复的任务不能使用此接口。没有增加前端参数面板。', '',
    '复现对比：在 media-tool 环境中于 backend 执行 `python tests/generate_comparisons.py`。测试执行 `python -m pytest -q`，前端执行 `npm run build`。没有增加依赖或修改 Conda/nvm 配置。', '',
    '## 剩余限制', '',
    '- 规则不是真正的语法解析；未收录的中文词语、日文活用与长谓语、英文专名/缩写仍可能在不理想的位置断开。没有引入 jieba、SudachiPy 或 LLM。',
    '- 动态规划只优化单个 Whisper Segment，不跨 Segment 或 60 秒音频窗口推测新的词时间戳；模型本身在句中结束 Segment 时，仍可能保留不自然边界。',
    '- 异常时间戳回退可能产生较长字幕；原始时间重叠时只能在保持文字顺序的前提下夹紧/合并，无法恢复准确词时间。',
    '- 新旧效果对比基于合成词时间戳；真实中日英口语、不同语速和标点质量还需要持续用实际素材验证。',
    '- 服务没有热重载；新算法用于重启后端后的识别任务。重启前先导出正在校对的结果。', '',
]
lines += [
    '## 修改文件', '',
    '- backend/app/config.py：语言参数及轻量语言边界规则。',
    '- backend/app/services/subtitle_service.py：候选评分、动态规划、词时间戳回退及完整文本拼接。',
    '- backend/app/services/transcription_service.py：保存原始识别快照并应用新断句。',
    '- backend/app/schemas.py、backend/app/main.py：保留文本分隔符，提供重复切分接口并保护人工编辑。',
    '- frontend/src/types.ts、frontend/src/App.tsx：纯文本显示保留原始字幕间分隔符。',
    '- backend/tests/test_semantic_subtitles.py、test_subtitles.py、test_api.py：语言边界、完整文本、时间轴与接口回归测试。',
    '- backend/tests/generate_comparisons.py：生成可重复验证的六组新旧对比。',
    '- README.md、VALIDATION.md、docs/SUBTITLE_SPLITTING.md：使用说明、验证结果和算法限制。', '',
]
destination = Path(__file__).resolve().parents[2] / 'docs' / 'SUBTITLE_SPLITTING.md'
destination.parent.mkdir(exist_ok=True)
destination.write_text('\n'.join(lines), encoding='utf-8')
print(destination)
