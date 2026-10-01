"""Download the chunks of an earlier « Générer les cartes » run (kept one day by GitHub), to
put its cards back in a deck (e.g. after a failed run replaced it).

Without --run, picks the most recent run whose chunks hold cards found in neither published
deck (the cards a later run replaced), with the most chunks.

Usage (in GitHub Actions, GITHUB_TOKEN and GITHUB_REPOSITORY set):
    python pipeline/restore_chunks.py [--run ID] --out chunks
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import requests

from common import DOCS, load_json

API = "https://api.github.com"


def gh(path: str, **kw):
    r = requests.get(API + path, timeout=120, headers={
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Accept": "application/vnd.github+json"}, **kw)
    r.raise_for_status()
    return r


def chunk_artifacts(repo: str, run: int) -> list[dict]:
    arts = gh(f"/repos/{repo}/actions/runs/{run}/artifacts", params={"per_page": 100}).json()["artifacts"]
    return [a for a in arts if a["name"].startswith("chunk-") and not a["expired"]]


def download(repo: str, art: dict, dest: Path) -> None:
    z = zipfile.ZipFile(io.BytesIO(gh(f"/repos/{repo}/actions/artifacts/{art['id']}/zip").content))
    dest.mkdir(parents=True, exist_ok=True)
    z.extractall(dest)


def published_images() -> set[str]:
    return {c["img"] for f in ("cards.json", "hardcore.json")
            for c in (load_json(DOCS / "data" / f, {}) or {}).get("cards", [])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="", help="run ID or URL (default: found automatically)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    repo = os.environ["GITHUB_REPOSITORY"]
    run = args.run.rstrip("/").split("/runs/")[-1].split("/")[0] if args.run else ""
    if not run:
        published = published_images()
        runs = gh(f"/repos/{repo}/actions/workflows/generate.yml/runs", params={"per_page": 30}).json()["workflow_runs"]
        best = None
        for r in runs:
            arts = chunk_artifacts(repo, r["id"])
            if not arts:
                continue
            probe = args.out / f"probe-{r['id']}"
            download(repo, arts[0], probe)
            imgs = {c["img"] for c in load_json(probe / "cards.json", [])}
            gone = imgs and not (imgs & published)
            print(f"run {r['id']} ({r['run_started_at']}): {len(arts)} chunk(s), "
                  f"{'cards no longer published' if gone else 'cards still published'}")
            if gone and (best is None or len(arts) > best[1]):
                best = (r["id"], len(arts))
        if not best:
            sys.exit("no run with chunks of cards that are no longer published (kept one day only)")
        run = str(best[0])
    arts = chunk_artifacts(repo, int(run))
    if not arts:
        sys.exit(f"run {run} has no chunks left (they are kept one day)")
    for a in arts:
        download(repo, a, args.out / a["name"])
    for p in args.out.glob("probe-*"):
        import shutil
        shutil.rmtree(p, ignore_errors=True)
    print(f"restored {len(arts)} chunk(s) of run {run} -> {args.out}")


if __name__ == "__main__":
    main()
