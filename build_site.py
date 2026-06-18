"""生成可部署的静态看板站点（docs/），纯 HTML 图表，双击/微信均可看。"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from media_utils import normalize_payload_media
from team_utils import get_schedule_keyword, get_team_aliases, get_team_keyword, load_config
from video_cache import load_cache, player_map_from_cache, video_map_from_cache
from visualize_team_stats import build_payload, render_dashboard_html

DOCS_DIR = Path("docs")


def _perspective_teams(cfg: dict) -> list[dict]:
    """看板统计视角：各分队/别名独立计算胜率。"""
    seen: set[str] = set()
    teams: list[dict] = []
    primary = get_schedule_keyword(cfg)
    teams.append({"label": "中铁元湾", "keyword": primary})
    seen.add(primary)
    for alias in get_team_aliases(cfg):
        if alias not in seen:
            teams.append({"label": alias, "keyword": alias})
            seen.add(alias)
    return teams


def build_site(
    csv_path: Path,
    output_dir: Path,
    *,
    team_name: str = "中铁元湾篮球队",
    focus_user_id: int | None = 324467,
    team_keyword: str | None = None,
    video_map: dict[int, dict] | None = None,
    player_highlight_map: dict[int, dict[int, dict]] | None = None,
) -> Path:
    keyword = team_keyword or get_team_keyword()
    df = pd.read_csv(str(csv_path.resolve()), encoding="utf-8-sig", engine="python")
    payload = build_payload(df, focus_user_id, team_keyword=keyword)
    schedule_ids = [g["scheduleId"] for g in payload["games"]]
    if video_map is None:
        cache = load_cache()
        video_map = video_map_from_cache(cache, schedule_ids)
    if player_highlight_map is None:
        cache = load_cache()
        player_highlight_map = player_map_from_cache(cache, schedule_ids)
    if video_map:
        for game in payload["games"]:
            vid = video_map.get(game["scheduleId"]) or {}
            game["playbackUrl"] = vid.get("playbackUrl")
            game["highlightUrl"] = vid.get("highlightUrl")
            game["coverUrl"] = vid.get("coverUrl")
            game["partName"] = vid.get("partName")
    if player_highlight_map:
        for game in payload["games"]:
            phm = player_highlight_map.get(game["scheduleId"]) or {}
            for player in game.get("players") or []:
                uid = player.get("userId")
                if uid in phm:
                    player.update(phm[uid])
            for player in game.get("oppPlayers") or []:
                uid = player.get("userId")
                if uid in phm:
                    player.update(phm[uid])
    payload["teamName"] = team_name
    payload["updatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    cfg = load_config()
    payload["perspectiveTeams"] = _perspective_teams(cfg)
    normalize_payload_media(payload)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "index.html").write_text(
        render_dashboard_html(payload, team_name), encoding="utf-8"
    )
    print(f"站点已生成 -> {output_dir.resolve()}")
    return output_dir


def main():
    parser = argparse.ArgumentParser(description="生成 GitHub Pages 静态看板")
    parser.add_argument("csv", type=Path, nargs="?", default=Path("team_dashboard.csv"))
    parser.add_argument("-o", "--output", type=Path, default=DOCS_DIR)
    parser.add_argument("--team-name", default=None)
    parser.add_argument("--user-id", type=int, default=324467)
    args = parser.parse_args()
    cfg = load_config()
    team_name = args.team_name or cfg.get("team_name", "中铁元湾篮球队")
    build_site(
        args.csv,
        args.output,
        team_name=team_name,
        focus_user_id=args.user_id,
        team_keyword=get_team_keyword(cfg),
    )


if __name__ == "__main__":
    main()
