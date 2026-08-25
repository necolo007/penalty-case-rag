"""竞赛配套数据目录解析（供 link / import 脚本共用）。"""

from __future__ import annotations

from pathlib import Path

# 相对 Monorepo 根（penalty-case-rag 的上一级）
COMP_DATA_REL = Path(
    "docs/data/05-金融大模型与智能体赛道-基于知识增强检索的保险监管处罚案例知识库构建与合规审查智能匹配/配套数据"
)
# 赛题数据包根（含 raw_text / 配套数据）
COMP_PACKAGE_REL = COMP_DATA_REL.parent

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MONOREPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_comp_dir(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        from core.config import get_settings

        settings = get_settings()
        if (settings.COMP_DATA_DIR or "").strip():
            return Path(settings.COMP_DATA_DIR).expanduser().resolve()
    except Exception:  # noqa: BLE001
        pass
    candidate = _MONOREPO_ROOT / COMP_DATA_REL
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(
        "未找到配套数据目录。请传 --comp-dir / --excel，或设置 COMP_DATA_DIR。"
        f" 已尝试: {candidate}"
    )


def resolve_comp_file(filename: str, *, explicit: str | None = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_absolute():
            p = _REPO_ROOT / p
        return p.resolve()
    return (resolve_comp_dir(None) / filename).resolve()
