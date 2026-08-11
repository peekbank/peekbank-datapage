#!/usr/bin/env python3
"""Recursively inventory OSF node pr6wu osfstorage via API v2 (unauthenticated)."""
import json, os, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

OUTDIR = "/private/tmp/claude-502/-Users-mcfrank-Projects-peekbank-datapage/1c58b8e6-691b-4956-85b7-82604ec026dd/scratchpad/osf_inventory"
BASE = "https://api.osf.io/v2/nodes/pr6wu/files/osfstorage/"
DEADLINE = time.time() + 12.5 * 60  # stop starting new datasets after this
SAMPLES = ["pomper_saffran_2016", "reflook_v4", "adams_marchman_2018",
           "fernald_totlot", "casillas_tseltal_2015", "swingley_aslin_2002"]

stats = {"requests": 0, "retries_429": 0, "retries_5xx": 0, "errors": []}
slock = Lock()

def fetch(url):
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "peekbank-inventory/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                with slock:
                    stats["requests"] += 1
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                with slock:
                    stats["retries_429"] += 1
                wait = int(e.headers.get("Retry-After", "30") or 30)
                time.sleep(min(wait, 120))
            elif e.code >= 500:
                with slock:
                    stats["retries_5xx"] += 1
                time.sleep(5 * (attempt + 1))
            else:
                raise
        except Exception:
            if attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"gave up on {url}")

def list_folder(files_url):
    """Yield all entries (paginated) of a folder listing endpoint."""
    sep = "&" if "?" in files_url else "?"
    url = f"{files_url}{sep}page%5Bsize%5D=100"
    out = []
    while url:
        d = fetch(url)
        out.extend(d["data"])
        url = d["links"].get("next")
    return out

def recurse_dataset(name, files_url):
    """BFS a dataset folder; return flat list of file/folder records."""
    records = []
    rlock = Lock()
    pool = ThreadPoolExecutor(max_workers=5)
    pending = []

    def visit(furl):
        entries = list_folder(furl)
        subfolders = []
        with rlock:
            for e in entries:
                a = e["attributes"]
                rec = {"kind": a["kind"], "name": a["name"],
                       "path": a["materialized_path"], "size": a.get("size")}
                records.append(rec)
                if a["kind"] == "folder":
                    subfolders.append(e["relationships"]["files"]["links"]["related"]["href"])
        return subfolders

    futures = [pool.submit(visit, files_url)]
    while futures:
        f = futures.pop()
        try:
            subs = f.result()
        except Exception as ex:
            with slock:
                stats["errors"].append(f"{name}: {ex}")
            continue
        for s in subs:
            futures.append(pool.submit(visit, s))
    pool.shutdown(wait=True)
    return records

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    top = list_folder(BASE)
    with open(f"{OUTDIR}/_top_level.json", "w") as fh:
        json.dump([{"name": e["attributes"]["name"], "kind": e["attributes"]["kind"],
                    "files_url": e["relationships"]["files"]["links"]["related"]["href"]}
                   for e in top], fh, indent=1)

    by_name = {e["attributes"]["name"]: e for e in top}
    order = [n for n in SAMPLES if n in by_name] + \
            sorted(n for n in by_name if n not in SAMPLES)

    done, skipped = [], []
    for name in order:
        outfile = f"{OUTDIR}/{name}.json"
        if os.path.exists(outfile):
            done.append(name)
            continue
        if time.time() > DEADLINE:
            skipped.append(name)
            continue
        t0 = time.time()
        e = by_name[name]
        furl = e["relationships"]["files"]["links"]["related"]["href"]
        recs = recurse_dataset(name, furl)
        nfiles = sum(1 for r in recs if r["kind"] == "file")
        nbytes = sum(r["size"] or 0 for r in recs if r["kind"] == "file")
        with open(outfile, "w") as fh:
            json.dump({"dataset": name, "file_count": nfiles, "total_bytes": nbytes,
                       "entries": recs}, fh)
        done.append(name)
        print(f"[{time.strftime('%H:%M:%S')}] {name}: {nfiles} files, "
              f"{nbytes/1e6:.1f} MB, {len(recs)-nfiles} folders "
              f"({time.time()-t0:.0f}s, reqs so far {stats['requests']})", flush=True)

    with open(f"{OUTDIR}/_run_stats.json", "w") as fh:
        json.dump({"done": done, "skipped": skipped, **stats}, fh, indent=1)
    print("DONE" if not skipped else f"PARTIAL, skipped: {skipped}")
    print(json.dumps(stats)[:2000])

if __name__ == "__main__":
    main()
