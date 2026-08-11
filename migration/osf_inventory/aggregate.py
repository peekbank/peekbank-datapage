#!/usr/bin/env python3
"""Aggregate per-dataset OSF inventory JSONs into report tables."""
import json, glob, os, collections

OUTDIR = "/private/tmp/claude-502/-Users-mcfrank-Projects-peekbank-datapage/1c58b8e6-691b-4956-85b7-82604ec026dd/scratchpad/osf_inventory"

def ext_of(name):
    base = name.lower()
    if "." not in base.strip("."):
        return "(none)"
    return "." + base.rsplit(".", 1)[1]

def human(n):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024

datasets = []
grand_ext = collections.Counter()
grand_ext_bytes = collections.Counter()
grand_top = collections.Counter()  # bytes by top-level subfolder name (raw_data etc.)
grand_top_files = collections.Counter()

for path in sorted(glob.glob(f"{OUTDIR}/*.json")):
    base = os.path.basename(path)
    if base.startswith("_"):
        continue
    d = json.load(open(path))
    name = d["dataset"]
    files = [r for r in d["entries"] if r["kind"] == "file"]
    folders = [r for r in d["entries"] if r["kind"] == "folder"]
    # immediate children: materialized path = /<dataset>/<child>[/]
    prefix = f"/{name}/"
    imm = sorted({r["name"] + ("/" if r["kind"] == "folder" else "")
                  for r in d["entries"]
                  if r["path"].rstrip("/") == prefix + r["name"]})
    # per top-level subfolder rollup
    sub = collections.defaultdict(lambda: [0, 0])  # name -> [files, bytes]
    for f in files:
        rel = f["path"][len(prefix):]
        top = rel.split("/", 1)[0] if "/" in rel else "(root files)"
        sub[top][0] += 1
        sub[top][1] += f["size"] or 0
        grand_top[top if top in ("raw_data", "processed_data") else "(other)"] += f["size"] or 0
        grand_top_files[top if top in ("raw_data", "processed_data") else "(other)"] += 1
        e = ext_of(f["name"])
        grand_ext[e] += 1
        grand_ext_bytes[e] += f["size"] or 0
    datasets.append({
        "name": name, "files": len(files), "folders": len(folders),
        "bytes": d["total_bytes"], "immediate": imm,
        "sub": {k: v for k, v in sorted(sub.items())},
    })

datasets.sort(key=lambda x: -x["bytes"])
total_bytes = sum(x["bytes"] for x in datasets)
total_files = sum(x["files"] for x in datasets)

print(f"DATASETS: {len(datasets)}  FILES: {total_files}  TOTAL: {human(total_bytes)} ({total_bytes} bytes)\n")

print("PER-DATASET (sorted by size):")
print(f"{'dataset':38} {'files':>6} {'size':>10}  subfolder breakdown")
for x in datasets:
    subtxt = "; ".join(f"{k}: {v[0]}f/{human(v[1])}" for k, v in x["sub"].items())
    print(f"{x['name']:38} {x['files']:>6} {human(x['bytes']):>10}  {subtxt}")

print("\nIMMEDIATE CHILDREN PATTERNS:")
pat = collections.Counter(tuple(x["immediate"]) for x in datasets)
for p, c in pat.most_common():
    names = [x["name"] for x in datasets if tuple(x["immediate"]) == p]
    print(f"  {c:>2}x {list(p)}  e.g. {names[:4]}")

print("\nRAW vs PROCESSED (grand totals over inventoried datasets):")
for k in grand_top:
    print(f"  {k:16} {grand_top_files[k]:>6} files  {human(grand_top[k])}")

print("\nTOP EXTENSIONS BY BYTES:")
for e, b in grand_ext_bytes.most_common(25):
    print(f"  {e:12} {grand_ext[e]:>6} files  {human(b)}")

print("\nTOP EXTENSIONS BY COUNT:")
for e, c in grand_ext.most_common(25):
    print(f"  {e:12} {c:>6} files  {human(grand_ext_bytes[e])}")

json.dump({"total_bytes": total_bytes, "total_files": total_files,
           "datasets": datasets},
          open(f"{OUTDIR}/_summary.json", "w"), indent=1)
