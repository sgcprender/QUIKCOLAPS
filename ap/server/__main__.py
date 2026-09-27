"""python -m server [--port 8765] [--no-browser]"""
from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"QuickColApps on {url}  (Ctrl+C to stop)")
    uvicorn.run("server.app:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
