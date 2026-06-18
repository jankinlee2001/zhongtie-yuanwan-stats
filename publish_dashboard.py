"""一键拉取数据并生成可部署的线上看板（docs/）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from build_site import build_site
from fetch_batch_schedule_stats import collect_team_ids, export_batch, filter_schedules, list_league_schedules
from schedule_video import fetch_player_highlights_for_schedule, get_schedule_videos
from team_utils import get_player_keywords, get_schedule_filter_keywords, get_schedule_keyword, load_config, match_team_name, pick_schedule_side
from video_cache import (
    has_video,
    load_cache,
    merge_player_highlights,
    merge_video,
    player_map_from_cache,
    save_cache,
    video_map_from_cache,
)

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "team_config.json"
CSV_PATH = ROOT / "team_dashboard.csv"
DOCS_DIR = ROOT / "docs"
TEAM_STATS_CACHE = ROOT / "team_stats_cache.json"


def _load_team_stats_map() -> dict | None:
    if not TEAM_STATS_CACHE.exists():
        return None
    try:
        return json.loads(TEAM_STATS_CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _schedule_user_ids(df: pd.DataFrame, schedule_id: int) -> list[int]:
    """一场比赛双方所有有效球员 userId（用于拉取个人集锦）。"""
    gdf = df[df["scheduleId"] == schedule_id]
    if gdf.empty or "userId" not in gdf.columns:
        return []
    out: set[int] = set()
    for x in gdf["userId"].dropna().unique():
        uid = int(x)
        if uid > 0:
            out.add(uid)
    return sorted(out)


def main() -> int:
    cfg = load_config(CONFIG_PATH)
    dash = cfg.get("dashboard") or {}
    league_id = cfg["league_id"]
    team_name = cfg.get("team_name", "中铁元湾篮球队")
    schedule_kw = get_schedule_keyword(cfg)
    schedule_filter_kws = get_schedule_filter_keywords(cfg)
    player_keywords = get_player_keywords(cfg)
    team_keyword = cfg.get("team_keyword", "中铁")
    last_n = dash.get("last_n_games", 5)
    fetch_n = int(dash.get("fetch_max_games") or max(last_n, 30))
    year = dash.get("year")
    min_date = dash.get("min_date")
    match_mode = dash.get("match_mode", "keyword")
    exclude_internal = dash.get("exclude_internal", True)
    focus_uid = dash.get("focus_user_id") or (cfg.get("players") or [{}])[0].get("user_id")

    print(f"拉取赛程 leagueId={league_id}，最多 {fetch_n} 场（页面可切换近5/近10/本赛季）...")
    schedules = list_league_schedules(league_id, season_id=None)

    filter_kw: dict = {
        "year": year,
        "min_date": min_date,
        "last": fetch_n,
        "exclude_internal": exclude_internal,
        "internal_keyword": "中铁",
    }
    if match_mode == "team_id" and cfg.get("team_id"):
        filter_kw["team_id"] = cfg["team_id"]
    elif match_mode == "team_cluster":
        ids = collect_team_ids(schedules, schedule_kw)
        filter_kw["team_ids"] = ids
        print(f"  匹配 {len(ids)} 个历史 teamId（{schedule_kw}）")
    else:
        filter_kw["team_name"] = schedule_filter_kws

    matched = filter_schedules(schedules, **filter_kw)
    if not matched:
        print("没有匹配到比赛", file=sys.stderr)
        return 1

    print("将包含以下比赛（按时间从新到旧）：")
    for item in matched:
        print(
            f"  {item['matchTime'][:10]}  {item['scheduleId']}  "
            f"{item['homeTeamName']} {item.get('homeTeamScore')}:{item.get('awayTeamScore')} {item['awayTeamName']}"
        )

    schedule_ids = [s["scheduleId"] for s in matched]
    print(f"\n共 {len(matched)} 场，拉取球员数据 ...")
    export_batch(schedule_ids, CSV_PATH, user_id=focus_uid)
    df = pd.read_csv(str(CSV_PATH), encoding="utf-8-sig", engine="python")

    print("拉取比赛回放视频 ...")
    cache = load_cache()
    video_map: dict[int, dict] = video_map_from_cache(cache, schedule_ids)
    player_highlight_map: dict[int, dict[int, dict]] = player_map_from_cache(cache, schedule_ids)
    for item in matched:
        sid = item["scheduleId"]
        our_tid = None
        home, away = item.get("homeTeamName") or "", item.get("awayTeamName") or ""
        side = pick_schedule_side(home, away, player_keywords)
        cfg_tid = cfg.get("team_id")
        if side == "home":
            our_tid = item.get("homeTeamId")
        elif side == "away":
            our_tid = item.get("awayTeamId")
        elif schedule_kw in home:
            our_tid = item.get("homeTeamId")
        elif schedule_kw in away:
            our_tid = item.get("awayTeamId")
        elif cfg_tid and (item.get("homeTeamId") == cfg_tid or item.get("awayTeamId") == cfg_tid):
            our_tid = cfg_tid
        cached_vid = (cache.get("videos") or {}).get(str(sid)) or (cache.get("videos") or {}).get(sid) or {}
        try:
            fresh = get_schedule_videos(sid, our_tid)
            merged = merge_video(cached_vid, fresh)
            video_map[sid] = merged
            cache.setdefault("videos", {})[str(sid)] = merged
            has = "有回放" if merged.get("playbackUrl") else ("有集锦" if merged.get("highlightUrl") else "无视频")
            src = "缓存" if has_video(cached_vid) and not has_video(fresh) else "在线"
            print(f"  {sid} {has} ({src})")
        except Exception as exc:
            print(f"  {sid} 视频拉取失败，使用缓存: {exc}")
            if cached_vid:
                video_map[sid] = {k: cached_vid.get(k) for k in ("playbackUrl", "highlightUrl", "coverUrl", "partName") if cached_vid.get(k)}
            else:
                video_map[sid] = {}

        print(f"  {sid} 拉取双方球员个人集锦 ...")
        uids = _schedule_user_ids(df, sid)
        cached_phm = (cache.get("playerHighlights") or {}).get(str(sid)) or (cache.get("playerHighlights") or {}).get(sid) or {}
        cached_phm = {int(k): v for k, v in cached_phm.items()}
        try:
            fresh_phm = fetch_player_highlights_for_schedule(sid, uids)
            merged_phm = merge_player_highlights(cached_phm, fresh_phm)
            player_highlight_map[sid] = merged_phm
            cache.setdefault("playerHighlights", {})[str(sid)] = {
                str(uid): info for uid, info in merged_phm.items()
            }
            print(f"    {len(merged_phm)}/{len(uids)} 人有集锦")
        except Exception as exc:
            print(f"    球员集锦拉取失败，使用缓存: {exc}")
            if cached_phm:
                player_highlight_map[sid] = cached_phm

    save_cache(cache)

    build_site(
        CSV_PATH,
        DOCS_DIR,
        team_name=team_name,
        focus_user_id=focus_uid,
        team_keyword=team_keyword,
        video_map=video_map,
        player_highlight_map=player_highlight_map,
        team_stats_map=_load_team_stats_map(),
    )
    try:
        from open_dashboard import mirror_to_home

        mirror = mirror_to_home(DOCS_DIR)
        print(f"本地镜像已同步 -> {mirror}")
    except Exception as exc:
        print(f"本地镜像同步失败（可手动重启 open_dashboard.py）: {exc}")
    print("完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
