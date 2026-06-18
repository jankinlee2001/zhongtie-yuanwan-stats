"""批量拉取联赛近期/本年度赛程球员数据并合并导出 CSV。"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from fetch_schedule_stats import APPKEY, get_schedule_data, get_schedule_info, players_to_rows, team_stats_from_payload
from team_utils import get_player_keywords, get_schedule_keyword, is_internal_match, is_our_internal_match, load_config, schedule_has_our_team

GATEWAY = "https://gatewayapi.woaolanqiu.cn"
SECRET = "9ce3c5643a14fadf33a2b882"


def sign(params: dict) -> dict:
    p = dict(params)
    p["appkey"] = APPKEY
    p["timestamp"] = str(int(time.time() * 1000))
    items = sorted((k, str(v)) for k, v in p.items() if v is not None and k != "sign")
    raw = SECRET + "".join(f"{k}{v}" for k, v in items) + SECRET
    p["sign"] = hashlib.md5(raw.encode()).hexdigest().upper()
    return p


def list_league_schedules(
    league_id: int,
    season_id: int | None = None,
    page_size: int = 50,
) -> list[dict]:
    """分页拉取联赛全部赛程。"""
    body: dict = {"leagueId": league_id}
    if season_id is not None:
        body["seasonId"] = season_id

    records: list[dict] = []
    page = 1
    while True:
        query = {"currentPage": page, "pageSize": page_size}
        merged = sign({**query, **body})
        q = {k: merged[k] for k in query}
        b = {k: merged[k] for k in body}
        r = requests.post(
            f"{GATEWAY}/schedule-service/schedule/pages",
            params=q,
            json=b,
            headers={"Content-Type": "application/json", "appkey": APPKEY},
            timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("code") != 200:
            raise RuntimeError(f"schedule/pages: {payload.get('message')}")

        data = payload.get("data") or {}
        batch = data.get("records") or []
        records.extend(batch)
        total_pages = data.get("pages") or 1
        if page >= total_pages or not batch:
            break
        page += 1
    return records


def filter_schedules(
    schedules: list[dict],
    *,
    team_id: int | None = None,
    team_ids: set[int] | None = None,
    team_name: str | list[str] | None = None,
    year: int | None = None,
    min_date: str | None = None,
    last: int | None = None,
    finished_only: bool = True,
    exclude_internal: bool = False,
    internal_keyword: str | None = None,
) -> list[dict]:
    def team_match(item: dict) -> bool:
        if team_ids:
            hid, aid = item.get("homeTeamId"), item.get("awayTeamId")
            if hid not in team_ids and aid not in team_ids:
                return False
        elif team_id is not None and item.get("homeTeamId") != team_id and item.get("awayTeamId") != team_id:
            return False
        if team_name:
            home = item.get("homeTeamName") or ""
            away = item.get("awayTeamName") or ""
            names = team_name if isinstance(team_name, list) else [team_name]
            if not schedule_has_our_team(home, away, names):
                return False
            if exclude_internal:
                kw = internal_keyword or (names[0] if isinstance(names, list) and len(names) == 1 else (names[0] if names else None))
                if kw and is_internal_match(home, away, kw):
                    return False
                if is_our_internal_match(home, away, get_player_keywords()):
                    return False
        return True

    filtered = [s for s in schedules if team_match(s)]
    if finished_only:
        filtered = [s for s in filtered if (s.get("liveStatus") or 0) == 2 or s.get("homeTeamScore") is not None]

    def parse_time(item: dict) -> datetime:
        text = item.get("matchTime") or "1970-01-01 00:00:00"
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")

    if year is not None:
        filtered = [s for s in filtered if parse_time(s).year == year]

    if min_date is not None:
        cutoff = datetime.strptime(min_date, "%Y-%m-%d")
        filtered = [s for s in filtered if parse_time(s) >= cutoff]

    filtered.sort(key=parse_time, reverse=True)

    if last is not None:
        filtered = filtered[:last]
    return filtered


def collect_team_ids(schedules: list[dict], team_name: str | list[str]) -> set[int]:
    """收集历史上所有队名含关键词的 teamId（同一俱乐部会有多个分队 id）。"""
    names = team_name if isinstance(team_name, list) else [team_name]
    ids: set[int] = set()
    for item in schedules:
        home, away = item.get("homeTeamName") or "", item.get("awayTeamName") or ""
        if schedule_has_our_team(home, away, names):
            if any(n in home for n in names):
                ids.add(item["homeTeamId"])
            if any(n in away for n in names):
                ids.add(item["awayTeamId"])
    return ids


def schedule_players_df(schedule_id: int) -> tuple[pd.DataFrame, dict[str, dict | None]]:
    info = get_schedule_info(schedule_id)
    payload = get_schedule_data(schedule_id)
    rows = players_to_rows(payload, "home") + players_to_rows(payload, "away")
    df = pd.DataFrame(rows)
    df.insert(0, "scheduleId", schedule_id)
    df.insert(1, "比赛时间", info.get("matchTime"))
    df.insert(2, "对阵", f"{info.get('homeTeamName')} {info.get('homeTeamScore')}:{info.get('awayTeamScore')} {info.get('awayTeamName')}")
    return df, team_stats_from_payload(payload)


def export_batch(
    schedule_ids: list[int],
    output: Path,
    user_id: int | None = None,
    team_stats_path: Path | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    team_stats_map: dict[str, dict] = {}
    for sid in schedule_ids:
        print(f"拉取 scheduleId={sid} ...")
        try:
            df, stats = schedule_players_df(sid)
            frames.append(df)
            team_stats_map[str(sid)] = stats
        except Exception as exc:
            print(f"  跳过 {sid}: {exc}")

    if not frames:
        raise RuntimeError("没有成功拉取到任何比赛数据")

    df = pd.concat(frames, ignore_index=True)
    cols = [
        "scheduleId", "比赛时间", "对阵", "球队", "主客场", "球员", "userId", "avatarUrl",
        "得分", "篮板", "助攻", "抢断", "盖帽", "失误", "犯规", "效率", "首发",
    ]
    df = df[[c for c in cols if c in df.columns]]
    df.to_csv(output, index=False, encoding="utf-8-sig")
    stats_out = team_stats_path or output.with_name("team_stats_cache.json")
    stats_out.write_text(json.dumps(team_stats_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n共 {len(schedule_ids)} 场，合并 {len(df)} 条球员记录 -> {output}")
    print(f"球队统计已保存 -> {stats_out}")

    if user_id is not None:
        hit = df[df["userId"] == user_id]
        print(f"userId={user_id} 共 {len(hit)} 条记录")
        if not hit.empty:
            print(hit.to_string(index=False))
    return df


def main():
    parser = argparse.ArgumentParser(description="批量导出我奥篮球近期/年度球员技术统计")
    parser.add_argument("--config", type=Path, default=Path("team_config.json"))
    parser.add_argument("--league-id", type=int, default=None)
    parser.add_argument("--season-id", type=int, default=None, help="限定赛季；不传则拉取联赛全部赛程")
    parser.add_argument("--team-id", type=int, default=None, help="精确匹配主/客队 teamId")
    parser.add_argument("--team-name", default=None, help="队名关键词，如 中铁")
    parser.add_argument("--year", type=int, default=None, help="只保留该年份比赛，如 2026")
    parser.add_argument("--last", type=int, default=None, help="只取最近 N 场")
    parser.add_argument("--user-id", type=int, default=None, help="导出后高亮指定球员")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--list-only", action="store_true", help="只列出匹配赛程，不拉球员数据")
    args = parser.parse_args()

    cfg = load_config(args.config)
    league_id = args.league_id or cfg.get("league_id")
    season_id = args.season_id
    team_id = args.team_id
    team_name = args.team_name
    if team_name is None and team_id is None:
        team_name = get_schedule_keyword(cfg)

    if league_id is None:
        raise SystemExit("缺少 league_id，请在 team_config.json 中配置或传 --league-id")

    print(f"拉取联赛赛程 leagueId={league_id} seasonId={season_id} ...")
    schedules = list_league_schedules(league_id, season_id)
    print(f"联赛共 {len(schedules)} 场比赛")

    matched = filter_schedules(
        schedules,
        team_id=team_id,
        team_name=team_name,
        year=args.year,
        last=args.last,
    )
    print(f"筛选后 {len(matched)} 场（team_name={team_name!r}, year={args.year}, last={args.last}）")
    for item in matched:
        print(
            f"  {item['scheduleId']}  {item['matchTime']}  "
            f"{item['homeTeamName']} {item.get('homeTeamScore')}:{item.get('awayTeamScore')} {item['awayTeamName']}"
        )

    if args.list_only or not matched:
        return

    out = args.output or Path(f"team_schedules_{league_id}_{args.year or 'all'}_{args.last or 'all'}.csv")
    export_batch([s["scheduleId"] for s in matched], out, user_id=args.user_id)


if __name__ == "__main__":
    main()
