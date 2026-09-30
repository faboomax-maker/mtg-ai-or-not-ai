"""Send a mode's answer key (pipeline/work/key-<mode>.json, written by build.py) to the game
server, which reveals each card only after it has been answered.

Usage: python pipeline/upload_deck.py --mode normal|hardcore
Needs QUIZ_API_URL (the Worker's URL) and QUIZ_ADMIN_TOKEN (the secret shared with it).
"""
from __future__ import annotations

import argparse
import sys

from common import WORK, env, load_json, session


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["normal", "hardcore"], required=True)
    args = ap.parse_args()
    url, token = (env("QUIZ_API_URL") or "").rstrip("/"), env("QUIZ_ADMIN_TOKEN")
    if not url or not token:
        sys.exit("QUIZ_API_URL and QUIZ_ADMIN_TOKEN are required")
    key = load_json(WORK / f"key-{args.mode}.json", None)
    if not key:
        sys.exit(f"no answer key for {args.mode}: run build.py first")
    r = session().post(f"{url}/admin/deck", json={"mode": args.mode, "key": key}, timeout=60,
                       headers={"Authorization": f"Bearer {token}"})
    if not r.ok:                     # the deck must not be published without its answers
        sys.exit(f"upload failed: HTTP {r.status_code} {r.text[:300]}")
    print(f"answers of {len(key)} {args.mode} cards sent to the game server")


if __name__ == "__main__":
    main()
