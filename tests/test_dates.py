"""core.dates 单元测试。"""

from datetime import date

import pytest

from core.dates import parse_optional_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("  ", None),
        ("2026-04-24", date(2026, 4, 24)),
        ("2026-4-24", date(2026, 4, 24)),
        ("2026/4/24", date(2026, 4, 24)),
        ("2026年4月24日", date(2026, 4, 24)),
        (date(2026, 4, 24), date(2026, 4, 24)),
    ],
)
def test_parse_optional_date_ok(raw, expected):
    assert parse_optional_date(raw) == expected


def test_parse_optional_date_invalid():
    with pytest.raises(ValueError):
        parse_optional_date("not-a-date")
