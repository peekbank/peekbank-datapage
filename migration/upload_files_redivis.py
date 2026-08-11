#!/usr/bin/env python3
"""Upload the mirrored OSF files (migration/osf_mirror/) to the
datapages.peekbank_files Redivis dataset as a single file-index table whose
file names are the OSF-relative paths (<dataset>/raw_data/..., etc.).

Two-phase like the tabular staging: this stages the draft only; release
happens with --release after verification + sign-off. Resumable: files whose
name is already present in the draft are skipped; only datasets with a
.mirror_done marker are considered (mirror still running -> partial upload
is fine, rerun later).

Usage: python3 migration/upload_files_redivis.py [--release] [--md5-sample N]
"""

import argparse
import base64
import hashlib
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIRROR = ROOT / "osf_mirror"

for line in open(ROOT.parent / ".secrets"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

import redivis  # noqa: E402

DATASET_REF = "peekbank_files:frvk"
TABLE_REF = "files"


def local_files():
    out = []
    for ds_dir in sorted(MIRROR.iterdir()):
        if not ds_dir.is_dir():
            continue
        if not (ds_dir / ".mirror_done").exists():
            print(f"  (skipping {ds_dir.name}: mirror not done)")
            continue
        for p in sorted(ds_dir.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                out.append((str(p.relative_to(MIRROR)), p))
    return out


def md5_b64(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--md5-sample", type=int, default=200)
    args = ap.parse_args()

    files = local_files()
    print(f"{len(files)} mirrored files eligible")

    ds = redivis.organization("datapages").dataset(DATASET_REF)
    ds = ds.create_next_version(if_not_exists=True)
    tb = ds.table(TABLE_REF)

    existing = {}
    for f in tb.list_files():
        p = f.properties
        existing[p["file_name"]] = p
    print(f"{len(existing)} files already in draft")

    todo = [{"name": rel, "path": str(p)} for rel, p in files
            if rel not in existing]
    print(f"{len(todo)} to upload")
    if todo:
        tb.add_files(files=todo, max_parallelization=20)

    # verify: every local file present, sizes match; md5 spot-check
    existing = {}
    for f in tb.list_files():
        p = f.properties
        existing[p["file_name"]] = p
    missing, bad_size = [], []
    for rel, p in files:
        e = existing.get(rel)
        if e is None:
            missing.append(rel)
        elif e.get("size") != p.stat().st_size:
            bad_size.append(rel)
    sample = random.Random(1).sample(files, min(args.md5_sample, len(files)))
    bad_md5 = [rel for rel, p in sample
               if existing.get(rel, {}).get("md5_hash") not in
               (None, md5_b64(p))]
    print(f"verify: {len(files)} local, {len(existing)} remote; "
          f"{len(missing)} missing, {len(bad_size)} size mismatches, "
          f"{len(bad_md5)}/{len(sample)} md5 mismatches")
    if missing[:5]:
        print("  missing sample:", missing[:5])
    if missing or bad_size or bad_md5:
        sys.exit("VERIFICATION FAILED")

    if not args.release:
        print("draft staged (NOT released). Re-run with --release after "
              "sign-off.")
        return
    print("releasing peekbank_files...")
    ds.release(release_notes=(
        "Initial file migration from OSF (osf.io/pr6wu): all raw_data/ and "
        "processed_data/ files plus per-dataset READMEs, named by their "
        "OSF-relative paths. Complete census: see "
        "peekbank/peekbank-datapage migration/osf_inventory/."))
    released = redivis.organization("datapages").dataset(DATASET_REF)
    tag = released.get().properties.get("version", {}).get("tag")
    print(f"released as {tag}")


if __name__ == "__main__":
    main()
