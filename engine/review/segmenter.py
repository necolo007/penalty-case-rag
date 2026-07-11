"""材料文本切分：段落 → 句子，记录字符偏移，用于前端风险高亮定位。"""

import re
from dataclasses import dataclass

_SENTENCE_END = re.compile(r"(?<=[。！？!?；;])")
_HEADING = re.compile(r"^\s*(#{1,6}\s|第[一二三四五六七八九十]+[章节条]|[一二三四五六七八九十]+[、.])")


@dataclass
class Sentence:
    text: str
    start: int            # 在原文中的字符偏移
    end: int
    paragraph_idx: int
    is_heading: bool = False


def segment_text(raw_text: str) -> list[Sentence]:
    sentences: list[Sentence] = []
    offset = 0
    for para_idx, paragraph in enumerate(raw_text.split("\n")):
        stripped = paragraph.strip()
        if stripped:
            is_heading = bool(_HEADING.match(paragraph))
            # 段内按句末标点切分
            pos = 0
            for piece in _SENTENCE_END.split(paragraph):
                if piece.strip():
                    start = offset + pos
                    sentences.append(Sentence(
                        text=piece.strip(),
                        start=start + (len(piece) - len(piece.lstrip())),
                        end=start + len(piece.rstrip()),
                        paragraph_idx=para_idx,
                        is_heading=is_heading,
                    ))
                pos += len(piece)
        offset += len(paragraph) + 1  # +1 换行符
    return sentences
