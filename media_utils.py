"""媒体链接规范化（HTTPS 等）。"""
from __future__ import annotations


def normalize_media_url(url: str | None) -> str | None:
    """我奥 CDN 返回 http，GitHub Pages 为 https，需统一否则手机无法播放/保存。"""
    if not url or not isinstance(url, str):
        return url
    u = url.strip()
    if u.startswith("http://"):
        return "https://" + u[7:]
    return u


def resolve_avatar_url(path: str | None) -> str | None:
    """我奥球员头像：相对路径拼 www.woaoo.net，微信头像等为完整 URL。"""
    if not path or not isinstance(path, str):
        return None
    p = path.strip()
    if not p:
        return None
    if p.startswith("http://") or p.startswith("https://"):
        return normalize_media_url(p)
    return normalize_media_url("https://www.woaoo.net/" + p.lstrip("/"))


def _norm_obj_urls(obj: dict, keys: tuple[str, ...]) -> None:
    for key in keys:
        if key in obj and obj[key]:
            obj[key] = normalize_media_url(obj[key])


def normalize_video_entry(entry: dict | None) -> dict | None:
    if not entry:
        return entry
    out = dict(entry)
    _norm_obj_urls(out, ("playbackUrl", "highlightUrl", "coverUrl"))
    return out


def normalize_player_highlight(info: dict | None) -> dict | None:
    if not info:
        return info
    out = dict(info)
    _norm_obj_urls(out, ("highlightUrl", "highlightCover"))
    clips = out.get("clips")
    if isinstance(clips, list):
        out["clips"] = [
            {**c, "url": normalize_media_url(c.get("url")), "coverUrl": normalize_media_url(c.get("coverUrl"))}
            for c in clips
        ]
    return out


def normalize_payload_media(payload: dict) -> None:
    """就地规范化 payload 中所有视频/封面链接。"""
    for game in payload.get("games") or []:
        _norm_obj_urls(game, ("playbackUrl", "highlightUrl", "coverUrl"))
        for player in game.get("players") or []:
            _norm_obj_urls(player, ("highlightUrl", "highlightCover", "avatarUrl"))
            if player.get("avatarUrl"):
                player["avatarUrl"] = resolve_avatar_url(player["avatarUrl"])
            clips = player.get("clips")
            if isinstance(clips, list):
                for clip in clips:
                    _norm_obj_urls(clip, ("url", "coverUrl"))
        for player in game.get("oppPlayers") or []:
            _norm_obj_urls(player, ("highlightUrl", "highlightCover", "avatarUrl"))
            if player.get("avatarUrl"):
                player["avatarUrl"] = resolve_avatar_url(player["avatarUrl"])
            clips = player.get("clips")
            if isinstance(clips, list):
                for clip in clips:
                    _norm_obj_urls(clip, ("url", "coverUrl"))
