"""拉取比赛回放/集锦视频链接。"""
from __future__ import annotations

import time

import requests

from fetch_schedule_stats import APPKEY, APPAPI, sign
from media_utils import normalize_player_highlight, normalize_video_entry


def _get_json(path: str, params: dict, *, retries: int = 3, timeout: int = 25) -> dict:
    """带重试的 API 请求，缓解偶发超时/5xx。"""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(
                f"{APPAPI}{path}",
                params=sign(params),
                headers={"appkey": APPKEY},
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt + 1 < retries:
                time.sleep(0.8 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def get_schedule_videos(schedule_id: int, our_team_id: int | None = None) -> dict:
    """返回全场回放与我方集锦 URL。"""
    data = _get_json(
        "/scheduleHighlightVideo/getSchedulePlaybackAndHighlights",
        {"scheduleId": schedule_id},
    )
    if data.get("code") != 200:
        return {"playbackUrl": None, "highlightUrl": None, "coverUrl": None}

    payload = data.get("data") or {}
    playbacks = payload.get("playbacks") or []
    highlights = payload.get("teamHighlightCollections") or []

    playback_url = None
    cover_url = None
    part_name = None
    if playbacks:
        pb = playbacks[0]
        playback_url = pb.get("videoUrl")
        part_name = pb.get("partName") or "全场回放"

    highlight_url = None
    for item in highlights:
        if our_team_id and item.get("teamId") == our_team_id:
            highlight_url = item.get("url")
            cover_url = cover_url or item.get("coverUrl")
            break
    if not highlight_url and highlights:
        highlight_url = highlights[0].get("url")
        cover_url = cover_url or highlights[0].get("coverUrl")

    return normalize_video_entry({
        "playbackUrl": playback_url,
        "highlightUrl": highlight_url,
        "coverUrl": cover_url,
        "partName": part_name,
    })


def get_user_personal_highlights(schedule_id: int, user_id: int) -> list[dict]:
    """拉取某球员在某场比赛的个人精彩镜头列表。"""
    try:
        data = _get_json(
            "/scheduleHighlightVideo/getUserPersonalHighlights",
            {"scheduleId": schedule_id, "userId": user_id},
            retries=2,
        )
    except Exception:
        return []
    if data.get("code") != 200:
        return []
    clips = data.get("data") or []
    return clips if isinstance(clips, list) else []


def summarize_player_highlights(clips: list[dict]) -> dict | None:
    """整理球员集锦：优先最长片段作为主集锦，保留全部镜头列表。"""
    valid = [c for c in clips if c.get("url")]
    if not valid:
        return None
    best = max(valid, key=lambda c: float(c.get("duration") or 0))
    ordered = sorted(valid, key=lambda c: float(c.get("duration") or 0), reverse=True)
    return normalize_player_highlight({
        "highlightUrl": best.get("url"),
        "highlightCover": best.get("coverUrl"),
        "highlightName": (best.get("name") or "个人集锦").strip(),
        "highlightCount": len(valid),
        "clips": [
            {
                "name": (c.get("name") or "镜头").strip(),
                "url": c.get("url"),
                "duration": round(float(c.get("duration") or 0), 1),
                "coverUrl": c.get("coverUrl"),
            }
            for c in ordered
        ],
    })


def fetch_player_highlights_for_schedule(schedule_id: int, user_ids: list[int]) -> dict[int, dict]:
    """批量拉取一场比赛我方球员个人集锦。key 为 userId。"""
    out: dict[int, dict] = {}
    for uid in user_ids:
        if not uid:
            continue
        try:
            info = summarize_player_highlights(get_user_personal_highlights(schedule_id, int(uid)))
            if info:
                out[int(uid)] = info
        except Exception:
            continue
    return out
