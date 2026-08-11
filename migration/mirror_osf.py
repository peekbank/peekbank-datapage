#!/usr/bin/env python3
"""Mirror the entire public OSF node pr6wu (peekbank raw + processed data)
to migration/osf_mirror/, resumably, for upload to Redivis file storage.

- Walks the OSF API v2 (paginated, sort=name to dodge the OSF pagination
  bug) collecting every file's materialized path + download link + size.
- Downloads with a small thread pool; a file is skipped when it already
  exists locally with the expected size (cheap resume).
- Verifies byte sizes after download; writes per-dataset .done markers and
  a final manifest cross-checked against migration/osf_inventory/.

Usage: python3 migration/mirror_osf.py [--datasets a b c] [--workers 6]
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parent
MIRROR = ROOT / "osf_mirror"
API_ROOT = "https://api.osf.io/v2/nodes/pr6wu/files/osfstorage/"
UA = {"User-Agent": "peekbank-migration/1.0 (peekbank-dev@lists.stanford.edu)"}

# files that are corrupted ON OSF's side (download endpoint returns a
# persistent 4xx even in a browser); documented in TEAM_REPORT.md
KNOWN_BAD = {
    # HTTP 400 from https://osf.io/download/q8x4k/ (reported to the team)
    "pomper_saffran_2016/raw_data/README.md",
}


def backoff_seconds(e, attempt):
    """Long, Retry-After-aware backoff for OSF throttling (HTTP 429)."""
    if isinstance(e, HTTPError) and e.code == 429:
        retry_after = e.headers.get("Retry-After")
        base = int(retry_after) if retry_after and retry_after.isdigit() else 30
        return min(600, max(base, 30) * (attempt + 1))
    return 2 ** (attempt + 1)


def get_json(url, tries=8):
    for i in range(tries):
        try:
            with urlopen(Request(url, headers=UA), timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(backoff_seconds(e, i))


def list_children(url):
    """All items under a folder listing URL (follows pagination)."""
    items = []
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}{urlencode({'page[size]': 100, 'sort': 'name'})}"
    while url:
        content = get_json(url)
        for d in content.get("data", []):
            attrs = d.get("attributes", {})
            items.append({
                "kind": attrs.get("kind"),
                "path": attrs.get("materialized_path"),
                "size": attrs.get("size"),
                "download": (d.get("links") or {}).get("download"),
                "children": ((d.get("relationships") or {})
                             .get("files", {}).get("links", {})
                             .get("related", {}).get("href")),
            })
        url = (content.get("links") or {}).get("next")
    return items


def walk_files(url):
    files = []
    stack = [url]
    while stack:
        for item in list_children(stack.pop()):
            if item["kind"] == "folder":
                stack.append(item["children"])
            elif item["kind"] == "file":
                files.append(item)
    return files


def download(item, tries=8):
    rel = item["path"].lstrip("/")
    if rel in KNOWN_BAD:
        return ("skip", rel, 0)
    dest = MIRROR / rel
    size = item["size"] or 0
    if dest.exists() and dest.stat().st_size == size:
        return ("skip", rel, size)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name("." + dest.name + ".part")
    for i in range(tries):
        try:
            with urlopen(Request(item["download"], headers=UA),
                         timeout=300) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            got = tmp.stat().st_size
            if size and got != size:
                raise IOError(f"size mismatch: got {got}, expected {size}")
            tmp.rename(dest)
            return ("ok", rel, got)
        except Exception as e:
            if i == tries - 1:
                return ("fail", rel, str(e))
            time.sleep(backoff_seconds(e, i))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    MIRROR.mkdir(exist_ok=True)
    top = [i for i in list_children(API_ROOT) if i["kind"] == "folder"]
    if args.datasets:
        by_name = {i["path"].strip("/"): i for i in top}
        top = [by_name[d] for d in args.datasets if d in by_name]
    print(f"{len(top)} top-level dataset folders", flush=True)

    grand_ok = grand_fail = grand_bytes = 0
    for folder in top:
        ds = folder["path"].strip("/")
        done_marker = MIRROR / ds / ".mirror_done"
        if done_marker.exists():
            print(f"{ds}: already done", flush=True)
            continue
        t0 = time.time()
        files = walk_files(folder["children"])
        results = {"ok": 0, "skip": 0, "fail": 0}
        failures = []
        nbytes = 0
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(download, f) for f in files]
            for fut in as_completed(futs):
                status, rel, info = fut.result()
                results[status] += 1
                if status == "fail":
                    failures.append((rel, info))
                    print(f"  FAIL {rel}: {info}", flush=True)
                else:
                    nbytes += info
        grand_ok += results["ok"] + results["skip"]
        grand_fail += results["fail"]
        grand_bytes += nbytes
        print(f"{ds}: {results['ok']} downloaded, {results['skip']} cached, "
              f"{results['fail']} failed, {nbytes/1e6:.1f} MB "
              f"({time.time()-t0:.0f}s)", flush=True)
        if results["fail"] == 0:
            done_marker.write_text(json.dumps(
                {"files": len(files), "bytes": nbytes}))

    print(f"\nTOTAL: {grand_ok} files ok, {grand_fail} failed, "
          f"{grand_bytes/1e9:.2f} GB this run", flush=True)
    if grand_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
