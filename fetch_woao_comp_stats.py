"""
我奥篮球 · 新版联赛数据导出（competitionId + userId）

联赛：中铁元湾篮球队 · competitionId=14120
示例球员：吴金潮 userId=324467

数据来源（自 H5 数据页 JS 逆向）：
  POST {gateway}/data-service/compPlayerStatistics/pagePlayerDataRankingComp
    query: currentPage, pageSize
    body:  competition, compSeason?, orderType, action
  POST {gateway}/data-service/compPlayerStatistics/getTopScheduleData

鉴权：网关返回 601 时需完整签名/请求头，见 team_config.json 与 probe_*.py
"""

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
GATEWAY = "https://gatewayapi.woaolanqiu.cn"
DEFAULT_CONFIG = Path(__file__).with_name("team_config.json")


def sign_md5(params: dict) -> dict:
    """页面 globalConfig 中的 appkey/secret（网关微服务常用，实测仍可能需额外头）。"""
    p = dict(params)
    p["appkey"] = APPKEY
    p["timestamp"] = str(int(time.time() * 1000))
    items = sorted((k, str(v)) for k, v in p.items() if v is not None and k != "sign")
    raw = SECRET + "".join(f"{k}{v}" for k, v in items) + SECRET
    p["sign"] = hashlib.md5(raw.encode()).hexdigest().upper()
    return p


def post_data_service(path: str, data: dict, page: int = 1, page_size: int = 20) -> dict:
    url = f"{GATEWAY}{path}"
    body = sign_md5(data)
    params = sign_md5({"currentPage": page, "pageSize": page_size})
    headers = {
        "Content-Type": "application/json",
        "appkey": APPKEY,
        "App-source": "woaoocomph5",
        "Woao-Platform": "h5",
    }
    r = requests.post(url, params=params, json=body, headers=headers, timeout=30)
    r.raise_for_status()
    out = r.json()
    if out.get("code") not in (0, 200, None):
        raise RuntimeError(f"API {path} code={out.get('code')} msg={out.get('message')}")
    return out.get("data") or out


def fetch_player_ranking(competition_id: int, action: str = "score", page_size: int = 50) -> list[dict]:
    data = {
        "competition": competition_id,
        "currentPage": 1,
        "pageSize": page_size,
        "orderType": 1,
        "action": action,
    }
    resp = post_data_service(
        "/data-service/compPlayerStatistics/pagePlayerDataRankingComp",
        data,
        page=1,
        page_size=page_size,
    )
    if isinstance(resp, dict) and "records" in resp:
        return resp["records"]
    return resp if isinstance(resp, list) else []


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="导出我奥篮球联赛球员榜（新版 H5）")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=Path("comp_player_ranking.csv"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    comp_id = cfg["competition_id"]
    print(f"联赛 {cfg.get('team_name')} competitionId={comp_id}")

    rows = fetch_player_ranking(comp_id)
    df = pd.DataFrame(rows)
    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"已写入 {args.output}（{len(df)} 行）")

    known = {p["user_id"]: p["name"] for p in cfg.get("players", [])}
    if not df.empty and "userId" in df.columns:
        for uid, name in known.items():
            hit = df[df["userId"] == uid]
            if not hit.empty:
                print(f"  {name} (userId={uid}): 在榜 {len(hit)} 条")


if __name__ == "__main__":
    main()
