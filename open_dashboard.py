"""启动本地看板服务并在浏览器打开（解决双击 HTML 打不开的问题）。"""
from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Timer

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
MIRROR = Path.home() / "woao_dashboard"


def ensure_dashboard() -> Path:
  if not (DOCS / "index.html").exists():
    print("未找到 docs/index.html，正在生成...")
    subprocess.check_call([sys.executable, str(ROOT / "publish_dashboard.py")], cwd=ROOT)
  return DOCS


def mirror_to_home(docs: Path) -> Path:
  """复制到用户目录（纯英文路径），避免中文路径导致浏览器打不开。"""
  MIRROR.mkdir(parents=True, exist_ok=True)
  for name in ("index.html", "data.json", "save.html"):
    src = docs / name
    if src.exists():
      shutil.copy2(src, MIRROR / name)
  assets = docs / "assets"
  if assets.is_dir():
    dst_assets = MIRROR / "assets"
    if dst_assets.exists():
      shutil.rmtree(dst_assets)
    shutil.copytree(assets, dst_assets)
  return MIRROR


def local_lan_ips() -> list[str]:
  """获取本机局域网 IP，供手机同 WiFi 访问。"""
  ips: set[str] = set()
  try:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
      s.connect(("8.8.8.8", 80))
      ips.add(s.getsockname()[0])
  except OSError:
    pass
  try:
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
      ip = info[4][0]
      if not ip.startswith("127."):
        ips.add(ip)
  except OSError:
    pass
  return sorted(ips)


def serve(directory: Path, port: int, *, host: str = "0.0.0.0") -> None:
  local_url = f"http://127.0.0.1:{port}/index.html?t={int(__import__('time').time())}"

  class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
      super().__init__(*args, directory=str(directory), **kwargs)

    def log_message(self, fmt, *args):
      print(fmt % args)

  print(f"\n电脑打开: {local_url}", flush=True)
  lan_ips = local_lan_ips()
  if lan_ips:
    print("手机打开（需与电脑同一 WiFi，并保持本窗口不关）:", flush=True)
    for ip in lan_ips:
      if ip.startswith(("192.168.", "10.", "172.")):
        print(f"  http://{ip}:{port}/index.html", flush=True)
  else:
    print("未检测到局域网 IP；手机请用 GitHub Pages 链接，或检查 WiFi。", flush=True)
  print("\n不要关闭此窗口。按 Ctrl+C 结束。\n", flush=True)
  Timer(1.0, lambda: webbrowser.open(local_url)).start()
  server = ThreadingHTTPServer((host, port), Handler)
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    print("\n已关闭")


def main() -> int:
  parser = argparse.ArgumentParser(description="打开篮球数据看板")
  parser.add_argument("--port", type=int, default=8899)
  parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0 允许手机同 WiFi 访问")
  parser.add_argument("--local-only", action="store_true", help="仅本机可访问（127.0.0.1）")
  parser.add_argument("--no-mirror", action="store_true", help="不复制到用户目录")
  parser.add_argument("--regen", action="store_true", help="重新拉取数据并生成看板")
  args = parser.parse_args()

  if args.regen:
    subprocess.check_call([sys.executable, str(ROOT / "publish_dashboard.py")], cwd=ROOT)

  docs = ensure_dashboard()
  serve_dir = docs if args.no_mirror else mirror_to_home(docs)
  if not args.no_mirror:
    print(f"已同步到: {serve_dir}")
  serve(serve_dir, args.port, host="127.0.0.1" if args.local_only else args.host)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
