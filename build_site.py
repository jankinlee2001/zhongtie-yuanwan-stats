"""生成可部署的静态看板站点（docs/），纯 HTML 图表，双击/微信均可看。"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from media_utils import normalize_payload_media
from team_utils import get_schedule_keyword, get_team_aliases, get_team_keyword, load_config
from video_cache import load_cache, player_map_from_cache, video_map_from_cache
from visualize_team_stats import build_payload, render_dashboard_html

DOCS_DIR = Path("docs")


def _prepare_bgm(cfg: dict, output_dir: Path) -> dict:
    """复制本地 BGM 到站点目录，并写入 payload（无视频占位时播放）。"""
    bgm_cfg = cfg.get("bgm") or {}
    if not bgm_cfg.get("enabled", False):
        return {"enabled": False}
    url = str(bgm_cfg.get("url") or "assets/until-the-end.mp3").lstrip("/")
    src = Path(bgm_cfg.get("source") or url)
    if src.exists():
        dest = output_dir / url
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"BGM 已复制 -> {dest.resolve()}")
    elif not (output_dir / url).exists():
        print(f"提示: 未找到 BGM 文件 {src.resolve()}，请将 MP3 放到该路径后重新生成看板")
    return {
        "enabled": True,
        "url": url,
        "title": bgm_cfg.get("title") or "直到世界尽头",
        "volume": float(bgm_cfg.get("volume", 0.45)),
    }


def _prepare_share(cfg: dict, output_dir: Path, payload: dict, team_name: str) -> dict:
    """复制分享图并生成 Open Graph 元信息（微信链接卡片）。"""
    site = cfg.get("site") or {}
    base = str(site.get("url") or "https://jankinlee2001.github.io/zhongtie-yuanwan-stats/").rstrip("/")
    rel = str(site.get("share_image") or "assets/share.jpg").lstrip("/")
    src = Path(site.get("share_image_source") or rel)
    if src.exists():
        dest = output_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"分享图已复制 -> {dest.resolve()}")
    elif not (output_dir / rel).exists():
        print(f"提示: 未找到分享图 {src.resolve()}，微信卡片可能无缩略图")
    gc = payload.get("gameCount") or 0
    wins = payload.get("wins") or 0
    losses = payload.get("losses") or 0
    wp = round(wins / gc * 100) if gc else 0
    title = f"{team_name} · 数据看板"
    desc = f"近{gc}场 {wins}胜{losses}负 · 胜率{wp}% · 比分走势、回放与球员数据"
    return {
        "title": title,
        "description": desc,
        "image": f"{base}/{rel}",
        "url": f"{base}/",
    }


def _write_share_preview(output_dir: Path, share: dict) -> None:
    """本地预览微信分享卡片样式。"""
    title = share.get("title", "")
    desc = share.get("description", "")
    image = share.get("image", "")
    url = share.get("url", "")
    local_img = "assets/share.jpg"
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>分享卡片预览</title>
  <style>
    body {{ font-family: -apple-system, "PingFang SC", sans-serif; background: #ededed; margin: 0; padding: 24px 16px; }}
    h1 {{ font-size: 1rem; color: #333; margin: 0 0 16px; font-weight: 600; }}
    .hint {{ font-size: .82rem; color: #666; margin-bottom: 20px; line-height: 1.5; }}
    .card {{
      max-width: 360px; background: #fff; border-radius: 8px; overflow: hidden;
      box-shadow: 0 2px 12px rgba(0,0,0,.08);
    }}
    .card img {{ width: 100%; display: block; aspect-ratio: 1.91/1; object-fit: cover; background: #111; }}
    .card-body {{ padding: 12px 14px 14px; }}
    .card-title {{ font-size: .95rem; font-weight: 600; color: #111; line-height: 1.35; margin-bottom: 6px; }}
    .card-desc {{ font-size: .8rem; color: #888; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
    .card-url {{ font-size: .72rem; color: #b2b2b2; margin-top: 8px; }}
    .meta {{ margin-top: 24px; max-width: 360px; font-size: .75rem; color: #666; word-break: break-all; }}
    .meta dt {{ font-weight: 600; margin-top: 10px; }}
    .meta dd {{ margin: 4px 0 0; }}
    a {{ color: #576b95; }}
  </style>
</head>
<body>
  <h1>微信分享卡片预览（本地模拟）</h1>
  <p class="hint">实际微信聊天里的样式与此类似。线上分享请用 HTTPS 链接；本地仅预览布局与文案。</p>
  <div class="card">
    <img src="{local_img}" alt="分享图" />
    <div class="card-body">
      <div class="card-title">{title}</div>
      <div class="card-desc">{desc}</div>
      <div class="card-url">{url.replace("https://", "")}</div>
    </div>
  </div>
  <dl class="meta">
    <dt>og:title</dt><dd>{title}</dd>
    <dt>og:description</dt><dd>{desc}</dd>
    <dt>og:image（线上）</dt><dd>{image}</dd>
    <dt>og:url</dt><dd>{url}</dd>
  </dl>
  <p style="margin-top:20px;font-size:.82rem"><a href="index.html">← 返回看板</a></p>
</body>
</html>"""
    (output_dir / "share-preview.html").write_text(html, encoding="utf-8")


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
    team_stats_map: dict | None = None,
) -> Path:
    keyword = team_keyword or get_team_keyword()
    df = pd.read_csv(str(csv_path.resolve()), encoding="utf-8-sig", engine="python")
    if team_stats_map is None:
        cache_path = csv_path.with_name("team_stats_cache.json")
        if cache_path.exists():
            try:
                team_stats_map = json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                team_stats_map = None
    payload = build_payload(df, focus_user_id, team_keyword=keyword, team_stats_map=team_stats_map)
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
    output_dir.mkdir(parents=True, exist_ok=True)
    dash = cfg.get("dashboard") or {}
    payload["range"] = {
        "default": str(dash.get("last_n_games", 5)),
        "seasonMinDate": dash.get("min_date"),
        "seasonYear": dash.get("year"),
        "fetched": len(payload.get("games") or []),
    }
    payload["bgm"] = _prepare_bgm(cfg, output_dir)
    share = _prepare_share(cfg, output_dir, payload, team_name)
    payload["share"] = share
    normalize_payload_media(payload)

    (output_dir / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "index.html").write_text(
        render_dashboard_html(payload, team_name, share=share), encoding="utf-8"
    )
    _write_share_preview(output_dir, share)
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
