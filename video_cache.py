"""视频与个人集锦本地缓存，避免 API 偶发失败或仅 build_site 时丢失链接。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "video_cache.json"

_VIDEO_KEYS = ("playbackUrl", "highlightUrl", "coverUrl", "partName")


def load_cache(path: Path | None = None) -> dict:
    p = path or CACHE_PATH
    if not p.exists():
        return {"videos": {}, "playerHighlights": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"videos": {}, "playerHighlights": {}}
    data.setdefault("videos", {})
    data.setdefault("playerHighlights", {})
    return data


def save_cache(cache: dict, path: Path | None = None) -> None:
    p = path or CACHE_PATH
    p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def has_video(entry: dict | None) -> bool:
    if not entry:
        return False
    return bool(entry.get("playbackUrl") or entry.get("highlightUrl"))


def merge_video(cached: dict | None, fresh: dict | None) -> dict:
    """合并单场视频：新数据有值则更新，失败或空字段保留缓存。"""
    out = dict(cached or {})
    fresh = fresh or {}
    for key in _VIDEO_KEYS:
        val = fresh.get(key)
        if val:
            out[key] = val
    if has_video(fresh) or has_video(out):
        out["updatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return out


def merge_player_highlights(
    cached: dict[int, dict] | None, fresh: dict[int, dict] | None
) -> dict[int, dict]:
    """合并球员集锦：按 userId 更新，新拉取为空时保留旧数据。"""
    out: dict[int, dict] = {int(k): dict(v) for k, v in (cached or {}).items()}
    for uid, info in (fresh or {}).items():
        uid = int(uid)
        if info and info.get("highlightUrl"):
            out[uid] = info
    return out


def video_map_from_cache(cache: dict, schedule_ids: list[int] | None = None) -> dict[int, dict]:
    raw = cache.get("videos") or {}
    out: dict[int, dict] = {}
    for sid, entry in raw.items():
        sid = int(sid)
        if schedule_ids is not None and sid not in schedule_ids:
            continue
        if has_video(entry):
            out[sid] = {k: entry.get(k) for k in _VIDEO_KEYS if entry.get(k)}
    return out


def player_map_from_cache(cache: dict, schedule_ids: list[int] | None = None) -> dict[int, dict[int, dict]]:
    raw = cache.get("playerHighlights") or {}
    out: dict[int, dict[int, dict]] = {}
    for sid, players in raw.items():
        sid = int(sid)
        if schedule_ids is not None and sid not in schedule_ids:
            continue
        pmap: dict[int, dict] = {}
        for uid, info in (players or {}).items():
            if info and info.get("highlightUrl"):
                pmap[int(uid)] = info
        if pmap:
            out[sid] = pmap
    return out
