"""日期解析工具：asyncpg DATE 列需传入 datetime.date，不能直接传字符串。"""

from __future__ import annotations

from datetime import date, datetime


def parse_optional_date(value: str | date | None) -> date | None:
    """将表单/抽取文本转为 date；空值返回 None。

    支持：
      - date 对象（原样返回）
      - YYYY-MM-DD / YYYY-M-D
      - YYYY/MM/DD、YYYY.MM.DD
      - YYYY年M月D日
    """
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None

    normalized = (
        text.replace("年", "-").replace("月", "-").replace("日", "")
        .replace("/", "-").replace(".", "-")
    )
    parts = [p for p in normalized.split("-") if p]
    if len(parts) != 3:
        raise ValueError(f"invalid date format: {value!r}")

    try:
        year, month, day = (int(parts[0]), int(parts[1]), int(parts[2]))
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"invalid date format: {value!r}") from exc
