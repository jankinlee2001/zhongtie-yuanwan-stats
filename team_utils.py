"""从 team_config.json 读取队名匹配关键词与别名。"""
from __future__ import annotations

import re
from pathlib import Path
import json

# 我奥 API 球员「球队」字段别名（赛程筛选与球员统计共用）
DEFAULT_ALIASES = ("浪里白条", "魔紫仙境", "季中赛1队", "季中赛2队")

# 队名末尾常见日期代码：616 / 0616 / 20260616 等
_DATE_SUFFIX_PATTERNS = (
    re.compile(r"\d{8}$"),
    re.compile(r"\d{6}$"),
    re.compile(r"\d{3,4}$"),
)

def load_config(path: Path | None = None) -> dict:
    path = path or Path("team_config.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def get_team_keyword(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    return cfg.get("team_keyword") or cfg.get("team_name", "").replace("篮球队", "") or "中铁"


def get_schedule_keyword(cfg: dict | None = None) -> str:
    """赛程主筛选关键词（如元湾）。"""
    cfg = cfg or load_config()
    dash = cfg.get("dashboard") or {}
    return (
        dash.get("schedule_keyword")
        or cfg.get("schedule_keyword")
        or "元湾"
    )


def get_team_aliases(cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_config()
    raw = cfg.get("team_aliases")
    if raw is None:
        return list(DEFAULT_ALIASES)
    return [str(a) for a in raw if a]


def get_player_keywords(cfg: dict | None = None) -> list[str]:
    """球员统计归属用：主关键词 + 别名。"""
    cfg = cfg or load_config()
    seen: set[str] = set()
    out: list[str] = []
    for name in [get_team_keyword(cfg), *get_team_aliases(cfg)]:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def get_team_keywords(cfg: dict | None = None) -> list[str]:
    """兼容旧调用：默认返回球员关键词。"""
    return get_player_keywords(cfg)


def normalize_team_name(name: str) -> str:
    """去掉空格与末尾日期代码，便于别名匹配。"""
    text = re.sub(r"\s+", "", str(name).strip())
    for pat in _DATE_SUFFIX_PATTERNS:
        stripped = pat.sub("", text).strip()
        if stripped and stripped != text:
            return stripped
    return text


def match_team_name(name: str, keywords: list[str] | None = None) -> bool:
    text = str(name)
    base = normalize_team_name(text)
    for kw in keywords or get_player_keywords():
        kw = str(kw)
        kw_base = normalize_team_name(kw)
        if kw in text or kw in base or kw_base in text or kw_base in base:
            return True
    return False


def is_our_team(name: str, keyword: str | list[str] | None = None) -> bool:
    if isinstance(keyword, list):
        return match_team_name(name, keyword)
    if keyword:
        return keyword in str(name)
    return match_team_name(name)


def schedule_has_our_team(home: str, away: str, keywords: list[str] | None = None) -> bool:
    return match_team_name(home, keywords) or match_team_name(away, keywords)


def get_schedule_filter_keywords(cfg: dict | None = None) -> list[str]:
    """赛程筛选用：主关键词 + 球队别名（如季中赛1队）。"""
    cfg = cfg or load_config()
    seen: set[str] = set()
    out: list[str] = []
    for name in [get_schedule_keyword(cfg), *get_team_aliases(cfg)]:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def is_our_internal_match(home: str, away: str, keywords: list[str] | None = None) -> bool:
    """仅排除中铁系内部赛；季中赛、别名分队对阵保留。"""
    cfg = load_config()
    dash = cfg.get("dashboard") or {}
    core = dash.get("internal_exclude_keywords", ["中铁"])
    home_s, away_s = str(home), str(away)
    if not all(any(k in side for k in core) for side in (home_s, away_s)):
        return False
    kws = keywords or get_player_keywords()
    return match_team_name(home, kws) and match_team_name(away, kws)


def is_internal_match(home: str, away: str, keyword: str) -> bool:
    """两边队名都含关键词时为内部赛（如中铁白队 vs 中铁紫队）。"""
    return keyword in home and keyword in away


def pick_schedule_side(home: str, away: str, keywords: list[str] | None = None) -> str | None:
    kws = keywords or get_player_keywords()
    home_hit = match_team_name(home, kws)
    away_hit = match_team_name(away, kws)
    if home_hit and not away_hit:
        return "home"
    if away_hit and not home_hit:
        return "away"
    return None
