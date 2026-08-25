"""材料文本切分：段落 → 句子，记录字符偏移，用于前端风险高亮定位。

OCR/PDF 原文常把同一句拆到多行；先合并软换行再按句末标点切分，避免风险句半截。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENTENCE_END = re.compile(r"(?<=[。！？!?；;])")
_HEADING = re.compile(r"^\s*(#{1,6}\s|第[一二三四五六七八九十]+[章节条]|[一二三四五六七八九十]+[、.])")
_LIST_ITEM = re.compile(
    r"^\s*(?:"
    r"\d+[\.、．]"
    r"|[（(]?[一二三四五六七八九十百千]+[）)、.、]"
    r"|[-•●▪]"
    r")\s*"
)
# 行尾已是完整句，不再与下行粘连
_HARD_LINE_END = frozenset("。！？!?")


@dataclass
class Sentence:
    text: str
    start: int  # 在原文中的字符偏移
    end: int
    paragraph_idx: int
    is_heading: bool = False


def _should_soft_join(prev_line: str, next_line: str) -> bool:
    """上一行未收尾、下一行不是新段/标题/列表时，视为排版软换行。"""
    prev = prev_line.rstrip()
    nxt = next_line.strip()
    if not prev or not nxt:
        return False
    if prev[-1] in _HARD_LINE_END:
        return False
    if _HEADING.match(next_line) or _LIST_ITEM.match(next_line):
        return False
    return True


def _iter_logical_blocks(raw_text: str) -> list[tuple[int, int, int, bool]]:
    """把软换行拼成逻辑块，返回 (start, end, paragraph_idx, is_heading)。

    start/end 覆盖原文闭开区间，中间可含换行符，便于高亮跨行。
    """
    lines = raw_text.split("\n")
    blocks: list[tuple[int, int, int, bool]] = []
    offset = 0
    para_idx = 0

    buf_start: int | None = None
    buf_end = 0
    buf_is_heading = False
    prev_line = ""

    def flush() -> None:
        nonlocal buf_start, buf_end, buf_is_heading, para_idx, prev_line
        if buf_start is not None and buf_end > buf_start:
            # 去掉块首尾空白（保留中间换行），收紧高亮区间
            while buf_start < buf_end and raw_text[buf_start] in " \t　":
                buf_start += 1
            while buf_end > buf_start and raw_text[buf_end - 1] in " \t　\r":
                buf_end -= 1
            if buf_end > buf_start:
                blocks.append((buf_start, buf_end, para_idx, buf_is_heading))
                para_idx += 1
        buf_start = None
        buf_end = 0
        buf_is_heading = False
        prev_line = ""

    for i, line in enumerate(lines):
        line_start = offset
        line_end = offset + len(line)
        stripped = line.strip()

        if not stripped:
            flush()
        elif buf_start is None:
            buf_start = line_start
            buf_end = line_end
            buf_is_heading = bool(_HEADING.match(line))
            prev_line = line
        elif _should_soft_join(prev_line, line):
            # 跨行续写：区间延伸到本行末（含中间的 \n）
            buf_end = line_end
            prev_line = line
        else:
            flush()
            buf_start = line_start
            buf_end = line_end
            buf_is_heading = bool(_HEADING.match(line))
            prev_line = line

        offset = line_end + 1  # +1 换行；末行无换行时多算 1 无影响（循环结束）

    flush()
    return blocks


def segment_text(raw_text: str) -> list[Sentence]:
    sentences: list[Sentence] = []
    if not raw_text:
        return sentences

    for block_start, block_end, para_idx, is_heading in _iter_logical_blocks(raw_text):
        block = raw_text[block_start:block_end]
        # 展示/判别用：去掉软换行，避免「中华人民\n共和国」半截句
        flat = re.sub(r"[\r\n]+", "", block)
        if not flat.strip():
            continue

        # 在「去换行后的扁平串」上切句，再映射回原文偏移
        flat_to_orig: list[int] = []
        for i, ch in enumerate(block):
            if ch not in "\r\n":
                flat_to_orig.append(block_start + i)

        pos = 0
        for piece in _SENTENCE_END.split(flat):
            if piece.strip():
                lead = len(piece) - len(piece.lstrip())
                trail = len(piece) - len(piece.rstrip())
                core = piece.strip()
                a = pos + lead
                b = pos + len(piece) - trail
                # flat 下标 → 原文下标
                orig_start = flat_to_orig[a] if a < len(flat_to_orig) else block_start
                orig_end = flat_to_orig[b - 1] + 1 if 0 < b <= len(flat_to_orig) else block_end
                sentences.append(
                    Sentence(
                        text=core,
                        start=orig_start,
                        end=orig_end,
                        paragraph_idx=para_idx,
                        is_heading=is_heading,
                    )
                )
            pos += len(piece)

    return sentences
