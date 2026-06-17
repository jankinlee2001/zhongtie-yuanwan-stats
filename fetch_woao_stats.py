#!/usr/bin/env python3
"""从我奥篮球网页拉取球队球员每场数据，导出 CSV 供分析。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.woaoo.net"
SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": BASE_URL,
    }
)

PER_GAME_COLUMNS = [
    "日期",
    "阶段",
    "球队",
    "比分",
    "对手",
    "二分",
    "三分",
    "罚球",
    "前板",
    "后板",
    "总板",
    "失误",
    "犯规",
    "抢断",
    "助攻",
    "盖帽",
    "得分",
    "效率值",
]


def fetch_team_players(sid: int, team_id: int) -> list[dict]:
    """获取球队球员名单（公开接口，无需登录）。"""
    resp = SESSION.post(
        f"{BASE_URL}/playerComparison/getTeamPlayers",
        data={"sid": sid, "teamId": team_id},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != 1:
        raise RuntimeError(f"获取球员名单失败: {payload}")

    players = json.loads(payload["message"])
    # 只保留当前赛季、在队球员
    return [p for p in players if p.get("seasonId") == sid and p.get("state") == "active"]


def parse_shooting_cell(text: str) -> tuple[int | None, int | None, float | None]:
    """解析如 '3-6 (50%)' 或 '7-7 (100.0%)'。"""
    text = text.strip()
    match = re.match(r"(\d+)\s*-\s*(\d+)\s*\(([\d.]+)\s*%\)", text)
    if not match:
        return None, None, None
    made, attempted, pct = int(match.group(1)), int(match.group(2)), float(match.group(3))
    return made, attempted, pct


def parse_per_game_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("div.tab table")
    if not table:
        return []

    rows: list[dict] = []
    for tr in table.select("tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < 17:
            continue

        date_text = cells[0]
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", date_text)
        stage_match = re.search(r"\s+(\S+)$", date_text)

        fg2_made, fg2_att, fg2_pct = parse_shooting_cell(cells[4])
        fg3_made, fg3_att, fg3_pct = parse_shooting_cell(cells[5])
        ft_made, ft_att, ft_pct = parse_shooting_cell(cells[6])

        row = {
            "日期": date_match.group(1) if date_match else date_text,
            "阶段": stage_match.group(1) if stage_match else "",
            "球队": cells[1],
            "比分": cells[2],
            "对手": cells[3],
            "二分": cells[4],
            "三分": cells[5],
            "罚球": cells[6],
            "二分命中": fg2_made,
            "二分出手": fg2_att,
            "二分命中率": fg2_pct,
            "三分命中": fg3_made,
            "三分出手": fg3_att,
            "三分命中率": fg3_pct,
            "罚球命中": ft_made,
            "罚球出手": ft_att,
            "罚球命中率": ft_pct,
            "前板": cells[7],
            "后板": cells[8],
            "总板": cells[9],
            "失误": cells[10],
            "犯规": cells[11],
            "抢断": cells[12],
            "助攻": cells[13],
            "盖帽": cells[14],
            "得分": cells[15],
            "效率值": cells[16],
        }
        rows.append(row)
    return rows


def fetch_player_games(uid: int, sid: int) -> list[dict]:
    params = {"uid": uid, "sid": sid, "s_sid": sid}
    url = f"{BASE_URL}/yz/player/data?{urlencode(params)}"
    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return parse_per_game_table(resp.text)


def collect_team_stats(sid: int, team_id: int, player_ids: list[int] | None = None) -> pd.DataFrame:
    players = fetch_team_players(sid, team_id)
    if player_ids:
        player_set = set(player_ids)
        players = [p for p in players if p["userId"] in player_set]

    if not players:
        raise RuntimeError("未找到符合条件的在队球员，请检查 sid / team_id 是否正确。")

    all_rows: list[dict] = []
    for player in players:
        uid = player["userId"]
        name = player["playerName"]
        jersey = player.get("jerseyNumber")
        print(f"拉取: {name} (uid={uid})")
        games = fetch_player_games(uid, sid)
        for game in games:
            game["球员"] = name
            game["uid"] = uid
            game["球衣号"] = jersey
            game["位置"] = player.get("location", "")
            all_rows.append(game)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    numeric_cols = [
        "二分命中", "二分出手", "二分命中率", "三分命中", "三分出手", "三分命中率",
        "罚球命中", "罚球出手", "罚球命中率", "前板", "后板", "总板", "失误", "犯规",
        "抢断", "助攻", "盖帽", "得分", "效率值", "球衣号", "uid",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    front_cols = ["球员", "uid", "球衣号", "位置", "日期", "阶段", "球队", "比分", "对手"]
    other_cols = [c for c in df.columns if c not in front_cols]
    return df[front_cols + other_cols]


def parse_url_ids(team_url: str) -> tuple[int, int]:
    """从球队主页 URL 解析 sid 和 tid。"""
    sid_match = re.search(r"[?&]sid=(\d+)", team_url)
    tid_match = re.search(r"[?&]tid=(\d+)", team_url)
    if not sid_match or not tid_match:
        raise ValueError("URL 需包含 sid 和 tid，例如: https://www.woaoo.net/yz/team/data?sid=23655&tid=341")
    return int(sid_match.group(1)), int(tid_match.group(1))


def main() -> None:
    parser = argparse.ArgumentParser(description="从我奥篮球拉取球队球员每场数据")
    parser.add_argument("--sid", type=int, help="赛季 ID (s_sid)")
    parser.add_argument("--tid", type=int, help="球队 ID (team_id)")
    parser.add_argument("--url", help="球队页面 URL，可自动解析 sid/tid")
    parser.add_argument("--uids", help="只拉取指定球员 uid，逗号分隔，如 2810,372")
    parser.add_argument("-o", "--output", default="team_stats.csv", help="输出 CSV 路径")
    args = parser.parse_args()

    if args.url:
        sid, tid = parse_url_ids(args.url)
    elif args.sid and args.tid:
        sid, tid = args.sid, args.tid
    else:
        parser.error("请提供 --url 或同时提供 --sid 与 --tid")

    uids = None
    if args.uids:
        uids = [int(x.strip()) for x in args.uids.split(",") if x.strip()]

    print(f"赛季 sid={sid}, 球队 tid={tid}")
    df = collect_team_stats(sid, tid, uids)
    if df.empty:
        print("未拉取到比赛数据。可能该赛季暂无统计，或页面结构有变化。")
        return

    out = Path(args.output)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"完成: {len(df)} 条记录 -> {out.resolve()}")
    print("\n场均概览:")
    summary = df.groupby("球员")[["得分", "总板", "助攻"]].mean().round(2)
    summary["场次"] = df.groupby("球员")["得分"].count()
    summary = summary[["场次", "得分", "总板", "助攻"]]
    summary.columns = ["场次", "场均得分", "场均篮板", "场均助攻"]
    print(summary.to_string())


if __name__ == "__main__":
    main()
