"""拉取单场赛程球员技术统计并导出 CSV。"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pandas as pd
import requests

APPKEY = "f9fee8010d10d8b855ca4172"
SECRET = "9ce3c5643a14fadf33a2b882"
APPAPI = "https://gatewayapi.woaolanqiu.cn/appapi"

FIELD_MAP = {
    "playerName": "球员",
    "userId": "userId",
    "teamId": "球队ID",
    "jerseyNumber": "号码",
    "score": "得分",
    "rs": "篮板",
    "a": "助攻",
    "s": "抢断",
    "b": "盖帽",
    "t": "失误",
    "p": "犯规",
    "y": "两分命中",
    "x": "两分出手",
    "pct2": "两分%",
    "y3": "三分命中",
    "x3": "三分出手",
    "pct3": "三分%",
    "y1": "罚球命中",
    "x1": "罚球出手",
    "pct1": "罚球%",
    "efficiency": "效率",
    "isFirst": "首发",
    "isPlay": "上场",
    "playerHeadPath": "avatarUrl",
}


def sign(params: dict) -> dict:
    p = dict(params)
    p["appkey"] = APPKEY
    p["timestamp"] = str(int(time.time() * 1000))
    items = sorted((k, str(v)) for k, v in p.items() if v is not None and k != "sign")
    raw = SECRET + "".join(f"{k}{v}" for k, v in items) + SECRET
    p["sign"] = hashlib.md5(raw.encode()).hexdigest().upper()
    return p


def get_schedule_info(schedule_id: int) -> dict:
    r = requests.get(
        f"{APPAPI}/schedule/getScheduleInfo",
        params=sign({"scheduleId": schedule_id}),
        headers={"appkey": APPKEY},
        timeout=25,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 200:
        raise RuntimeError(f"getScheduleInfo: {data.get('message')}")
    return data["data"]


def get_schedule_data(schedule_id: int) -> dict:
    r = requests.get(
        f"{APPAPI}/schedule/scheduleData",
        params=sign({"scheduleId": schedule_id}),
        headers={"appkey": APPKEY},
        timeout=25,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 200:
        raise RuntimeError(f"scheduleData: {data.get('message')}")
    return data["data"]


def players_to_rows(payload: dict, side: str) -> list[dict]:
    key = f"{side}TeamPlayerStatistics"
    team_key = f"{side}TeamStatistics"
    team_name = (payload.get(team_key) or {}).get("teamName", side)
    rows = []
    for p in payload.get(key) or []:
        row = {FIELD_MAP.get(k, k): v for k, v in p.items() if k in FIELD_MAP}
        row["球队"] = team_name
        row["主客场"] = "主场" if side == "home" else "客场"
        rows.append(row)
    return rows


def export_schedule(schedule_id: int, output: Path) -> pd.DataFrame:
    info = get_schedule_info(schedule_id)
    payload = get_schedule_data(schedule_id)
    rows = players_to_rows(payload, "home") + players_to_rows(payload, "away")
    df = pd.DataFrame(rows)
    cols = ["球队", "主客场", "球员", "userId", "得分", "篮板", "助攻", "抢断", "盖帽", "失误", "犯规", "效率", "首发"]
    df = df[[c for c in cols if c in df.columns]]
    df.to_csv(output, index=False, encoding="utf-8-sig")
    print(
        f"比赛: {info.get('homeTeamName')} {info.get('homeTeamScore')} "
        f"- {info.get('awayTeamScore')} {info.get('awayTeamName')}"
    )
    print(f"时间: {info.get('matchTime')}  leagueId={info.get('leagueId')} seasonId={info.get('seasonId')}")
    print(f"已导出 {len(df)} 名球员 -> {output}")
    return df


def main():
    parser = argparse.ArgumentParser(description="导出我奥篮球单场球员技术统计")
    parser.add_argument("schedule_id", type=int, nargs="?", default=2306518)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--user-id", type=int, default=None, help="高亮指定 userId")
    args = parser.parse_args()
    out = args.output or Path(f"schedule_{args.schedule_id}_players.csv")
    df = export_schedule(args.schedule_id, out)
    if args.user_id is not None:
        hit = df[df["userId"] == args.user_id]
        if hit.empty:
            print(f"本场未找到 userId={args.user_id}")
        else:
            print(hit.to_string(index=False))


if __name__ == "__main__":
    main()
