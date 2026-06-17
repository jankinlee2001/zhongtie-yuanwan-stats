"""从球队 CSV 生成交互式 HTML 数据看板（完全离线，无需外网）。"""
from __future__ import annotations

import argparse
import json
import re
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Timer

import pandas as pd

from team_utils import get_player_keywords, get_team_keyword, load_config, match_team_name

STAT_COLS = ["得分", "篮板", "助攻", "抢断", "盖帽", "失误", "犯规", "效率"]


def parse_matchup(matchup: str) -> tuple[str, int, int, str] | None:
    m = re.match(r"(.+?)\s+(\d+):(\d+)\s+(.+)", str(matchup))
    if not m:
        return None
    return m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)


def resolve_our_side(
    matchup: tuple[str, int, int, str] | None,
    keywords: list[str],
    gdf: pd.DataFrame | None = None,
    focus_user_id: int | None = None,
) -> str | None:
    """根据对阵 / 球员数据判断我方是主场还是客场。"""
    if matchup:
        home, _, _, away = matchup
        home_hit = match_team_name(home, keywords)
        away_hit = match_team_name(away, keywords)
        if home_hit and not away_hit:
            return "主场"
        if away_hit and not home_hit:
            return "客场"
        if home_hit and away_hit and gdf is not None:
            return _side_from_players(gdf, keywords, focus_user_id)

    if gdf is not None:
        return _side_from_players(gdf, keywords, focus_user_id)
    return None


def _side_from_players(
    gdf: pd.DataFrame, keywords: list[str], focus_user_id: int | None
) -> str | None:
    """用球员队名 / 关注球员判定主客场（处理内部赛、别名队名）。"""
    if focus_user_id is not None and "userId" in gdf.columns:
        focus = gdf[gdf["userId"] == focus_user_id]
        if not focus.empty and "主客场" in focus.columns:
            return str(focus.iloc[0]["主客场"])

    if "球队" not in gdf.columns or "主客场" not in gdf.columns:
        return None

    alias_sides: list[str] = []
    for side in ("主场", "客场"):
        side_rows = gdf[gdf["主客场"] == side]
        if side_rows["球队"].map(lambda n: match_team_name(n, keywords)).any():
            alias_sides.append(side)

    if len(alias_sides) == 1:
        return alias_sides[0]
    if len(alias_sides) > 1 and focus_user_id is not None:
        focus = gdf[gdf["userId"] == focus_user_id]
        if not focus.empty:
            return str(focus.iloc[0]["主客场"])
    return alias_sides[0] if alias_sides else None


def our_rows_for_game(
    gdf: pd.DataFrame,
    matchup: tuple[str, int, int, str] | None,
    keywords: list[str],
    focus_user_id: int | None = None,
) -> pd.DataFrame:
    side = resolve_our_side(matchup, keywords, gdf, focus_user_id)
    if side and "主客场" in gdf.columns:
        rows = gdf[gdf["主客场"] == side]
        if not rows.empty:
            return rows
    rows = gdf[gdf["球队"].map(lambda n: match_team_name(n, keywords))]
    if rows.empty or "主客场" not in rows.columns:
        return rows
    sides = rows["主客场"].unique()
    if len(sides) == 1:
        return rows
    if focus_user_id is not None and "userId" in gdf.columns:
        focus = gdf[gdf["userId"] == focus_user_id]
        if not focus.empty:
            return gdf[gdf["主客场"] == focus.iloc[0]["主客场"]]
    return rows[rows["主客场"] == sides[0]]


def build_payload(df: pd.DataFrame, focus_user_id: int | None, team_keyword: str | None = None) -> dict:
    keywords = get_player_keywords() if team_keyword is None else get_player_keywords(
        {**load_config(), "team_keyword": team_keyword}
    )
    for col in STAT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    games = []
    all_our_parts: list[pd.DataFrame] = []

    for sid, gdf in df.groupby("scheduleId", sort=False):
        row0 = gdf.iloc[0]
        matchup = parse_matchup(row0["对阵"])
        our_rows = our_rows_for_game(gdf, matchup, keywords, focus_user_id)
        all_our_parts.append(our_rows)

        our_team = ""
        if matchup:
            side = resolve_our_side(matchup, keywords, gdf, focus_user_id)
            if side == "主场":
                our_team = matchup[0]
            elif side == "客场":
                our_team = matchup[3]
            elif match_team_name(matchup[0], keywords):
                our_team = matchup[0]
            elif match_team_name(matchup[3], keywords):
                our_team = matchup[3]
        if not our_team and not our_rows.empty:
            our_team = str(our_rows.iloc[0]["球队"])

        if matchup:
            side = resolve_our_side(matchup, keywords, gdf, focus_user_id)
            if side == "主场":
                our_score, opp_score, opponent = matchup[1], matchup[2], matchup[3]
            elif side == "客场":
                our_score, opp_score, opponent = matchup[2], matchup[1], matchup[0]
            elif match_team_name(matchup[0], keywords):
                our_score, opp_score, opponent = matchup[1], matchup[2], matchup[3]
            elif match_team_name(matchup[3], keywords):
                our_score, opp_score, opponent = matchup[2], matchup[1], matchup[0]
            else:
                our_score = int(our_rows["得分"].sum()) if not our_rows.empty else 0
                opp_score = 0
                opponent = "对手"
        else:
            our_score = int(our_rows["得分"].sum()) if not our_rows.empty else 0
            opp_score = 0
            opponent = "对手"

        top = (
            our_rows.nlargest(5, "得分")[["球员", "得分", "篮板", "助攻"]]
            .to_dict(orient="records")
        )
        player_cols = ["球员", "userId", *STAT_COLS]
        if "首发" in our_rows.columns:
            player_cols.append("首发")
        players = (
            our_rows.sort_values("得分", ascending=False)[player_cols]
            .to_dict(orient="records")
        )
        for p in players:
            if "userId" in p and p["userId"] is not None:
                p["userId"] = int(p["userId"])
            for col in STAT_COLS:
                p[col] = int(p[col])
            if "首发" in p:
                p["首发"] = bool(p["首发"])
        games.append(
            {
                "scheduleId": int(sid),
                "date": str(row0["比赛时间"])[:10],
                "matchup": str(row0["对阵"]),
                "ourTeam": our_team,
                "opponent": opponent,
                "ourScore": our_score,
                "oppScore": opp_score,
                "win": our_score > opp_score,
                "topScorers": top,
                "players": players,
            }
        )

    games.sort(key=lambda x: x["date"])

    our_df = pd.concat(all_our_parts, ignore_index=True) if all_our_parts else df.iloc[0:0]
    agg = (
        our_df.groupby("球员", as_index=False)[STAT_COLS[:4]]
        .sum()
        .sort_values("得分", ascending=False)
        .head(8)
    )
    top_players = agg.to_dict(orient="records")

    return {
        "games": games,
        "topPlayers": top_players,
        "gameCount": len(games),
        "wins": sum(1 for g in games if g["win"]),
        "losses": sum(1 for g in games if not g["win"]),
    }


_TEMPLATE_PATH = Path(__file__).resolve().parent / "dashboard_template.html"


def _load_template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")

def render_dashboard_html(payload: dict, team_name: str = "中铁元湾篮球队") -> str:
    win_pct = round(payload["wins"] / payload["gameCount"] * 100) if payload["gameCount"] else 0
    updated = payload.get("updatedAt") or datetime.now().strftime("%Y-%m-%d %H:%M")
    html = _load_template()
    html = html.replace("__TEAM_NAME__", team_name)
    html = html.replace("__GAME_COUNT__", str(payload["gameCount"]))
    html = html.replace("__WINS__", str(payload["wins"]))
    html = html.replace("__LOSSES__", str(payload["losses"]))
    html = html.replace("__WIN_PCT__", str(win_pct))
    html = html.replace("__GEN_TIME__", updated)
    html = html.replace("__DATA_JSON__", json.dumps(payload, ensure_ascii=False))
    return html


def render_html(payload: dict, output: Path, team_name: str = "中铁元湾篮球队") -> None:
    output.write_text(render_dashboard_html(payload, team_name), encoding="utf-8")


def serve_and_open(html_path: Path, port: int = 8765) -> None:
    """用本地 HTTP 服务打开，避免 file:// 协议限制。"""
    directory = str(html_path.parent.resolve())
    filename = html_path.name
    url = f"http://127.0.0.1:{port}/{filename}"

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"看板地址: {url}", flush=True)
    print("按 Ctrl+C 关闭服务", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已关闭")


def main():
    parser = argparse.ArgumentParser(description="生成球队数据 HTML 看板")
    parser.add_argument("csv", type=Path, nargs="?", default=Path("team_last5.csv"))
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--user-id", type=int, default=324467)
    parser.add_argument("--serve", action="store_true", help="启动本地服务并在浏览器打开")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    csv_path = args.csv.resolve()
    df = pd.read_csv(str(csv_path), encoding="utf-8-sig", engine="python")
    payload = build_payload(df, args.user_id, get_team_keyword())
    out = (args.output or csv_path.with_suffix(".html")).resolve()
    render_html(payload, out)
    print(f"已生成看板 -> {out}", flush=True)
    print(f"{payload['gameCount']} 场比赛，{payload['wins']} 胜 {payload['losses']} 负", flush=True)

    if args.serve:
        serve_and_open(out, args.port)
    else:
        print(f"提示: 若双击 HTML 打不开，请运行: python visualize_team_stats.py --serve", flush=True)
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
