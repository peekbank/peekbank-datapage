#!/usr/bin/env python3
"""Upload one staged peekbank release to the datapages.peekbank Redivis
dataset as the next version. Adapted from langcog/childes-db
redivis/upload_2026.py.

Stage releases OLDEST -> NEWEST (2021.1, 2022.1, 2025.1, 2025.2, 2026.1) so
Redivis version tags map cleanly onto source releases. Two-phase: run
without --release to stage the draft (idempotent/resumable), verify counts,
then re-run with --release after sign-off.

A synthetic one-row `release_info` table (release_name, staged_date) is
added so clients can report which source release a Redivis version holds
without hardcoding a mapping.

Usage: python3 migration/upload_redivis.py --version 2021.1 [--release]
Reads REDIVIS_API_TOKEN from .secrets at the repo root.
"""

import argparse
import datetime
import os
import re
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGING = REPO_ROOT / "migration" / "staging"

with open(REPO_ROOT / ".secrets") as f:
    for line in f:
        if "=" in line:
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)

import redivis  # noqa: E402

TABLES = [
    "datasets", "subjects", "administrations", "stimuli", "trial_types",
    "trials", "aoi_region_sets", "aoi_timepoints", "aoi_timepoints_rle",
    "xy_timepoints", "release_info",
]

TABLE_DESCRIPTIONS = {
    "datasets": "One row per contributed study: dataset_name, lab metadata, citation/shortcite, aux_data (JSON string).",
    "subjects": "One row per (de-identified) child: native language, sex, anonymized id; links longitudinal administrations. aux_data (JSON string) may hold CDI and other measures.",
    "administrations": "One row per test session: age in months (plus lab_age/lab_age_units as originally coded), coding method, monitor properties; FK to datasets and subjects.",
    "stimuli": "One row per (label, image) stimulus pairing: english_stimulus_label, original label/language, novelty (familiar vs novel), image path; FK to datasets.",
    "trial_types": "One row per designed trial: target/distractor stimulus ids and sides, point of disambiguation, condition, full phrase and language; FK to datasets, stimuli, aoi_region_sets.",
    "trials": "One row per trial instance a participant completed: trial order, excluded flag/reason; FK to trial_types.",
    "aoi_region_sets": "AOI screen-coordinate boxes (left/right target regions) for eye-tracker datasets.",
    "aoi_timepoints": "Gaze coded as AOI (target/distractor/other/missing) at 40 Hz; t_norm in ms centered on target-word onset; FK to administrations and trials.",
    "aoi_timepoints_rle": "Run-length-encoded form of aoi_timepoints (one row per run of a constant AOI: administration_id, trial_id, t_norm of run start, aoi, length in 25 ms samples). Transfer-efficient; deterministically derived from aoi_timepoints.",
    "xy_timepoints": "Raw gaze (x, y) screen coordinates at 40 Hz for eye-tracker datasets; t_norm as in aoi_timepoints.",
    "release_info": "Synthetic staging metadata (not in the source MySQL): the source release name this Redivis version holds, and when it was staged.",
}


def table_files(version, name):
    d = STAGING / version / name
    return sorted(d.glob("part-*.parquet")) if d.is_dir() else []


def make_release_info(version):
    d = STAGING / version / "release_info"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "part-00000.parquet"
    schema = pa.schema([
        pa.field("release_name", pa.string()),
        pa.field("staged_date", pa.date32()),
    ])
    pq.write_table(pa.Table.from_pylist(
        [{"release_name": version, "staged_date": datetime.date.today()}],
        schema=schema), path, compression="zstd")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--notes", default=None)
    args = ap.parse_args()

    version = args.version
    if not table_files(version, "release_info"):
        make_release_info(version)

    expected = {}
    for t in TABLES:
        files = table_files(version, t)
        if not files:
            sys.exit(f"no parquet found for table {t} (staging incomplete?)")
        done_marker = STAGING / version / t / ".done"
        if t != "release_info" and not done_marker.exists():
            sys.exit(f"table {t} has no .done marker (export incomplete?)")
        expected[t] = sum(pq.read_metadata(f).num_rows for f in files)
        print(f"{t}: {expected[t]:,} rows in {len(files)} file(s)")

    org = redivis.organization("datapages")
    ds = org.dataset("peekbank")
    if not ds.exists():
        print("creating dataset datapages.peekbank (public)")
        ds.create(public_access_level="data")
    else:
        props = ds.get().properties
        cur = (props.get("version") or {}).get("tag")
        print(f"dataset exists; current released version tag: {cur}")
    ds = ds.create_next_version(if_not_exists=True)

    norm = lambda s: re.sub(r"[^A-Za-z0-9]", "", s)
    for t in TABLES:
        tb = ds.table(t)
        if not tb.exists():
            tb.create(description=TABLE_DESCRIPTIONS.get(t))
        tb.update(upload_merge_strategy="replace")
        done_uploads = set()
        for u in tb.list_uploads():
            props = getattr(u, "properties", {}) or {}
            if props.get("status") in ("completed", "succeeded"):
                done_uploads.add(norm(props.get("name", "")))
        files = table_files(version, t)
        print(f"uploading {t}: {expected[t]:,} rows, {len(files)} file(s) "
              f"({len(done_uploads)} already up)")
        for p in files:
            upload_name = f"{t}-{p.name}"
            if norm(upload_name) in done_uploads:
                continue
            for attempt in range(4):
                try:
                    tb.upload(upload_name).create(
                        content=str(p), type="parquet",
                        replace_on_conflict=True)
                    break
                except Exception as e:
                    if attempt == 3:
                        raise
                    print(f"  {upload_name}: {type(e).__name__}: {e}; retry in "
                          f"{60 * (attempt + 1)}s", flush=True)
                    time.sleep(60 * (attempt + 1))

    if not args.release:
        print(f"\n{version} uploaded to draft next version (NOT released). "
              f"Verify, then re-run with --release.")
        return

    notes = args.notes or (
        f"Peekbank release {version}, staged verbatim from the hosted MariaDB "
        f"(peekbank.stanford.edu). Tables: the 9 canonical peekbank tables "
        f"plus aoi_timepoints_rle (run-length-encoded transfer form) and a "
        f"synthetic release_info table naming the source release. The "
        f"rebuildable aoi_timepoints_indexed intermediate and Django "
        f"bookkeeping tables were not staged."
    )
    print("releasing...")
    ds.release(release_notes=notes)
    # released metadata can lag for a few minutes; retry before declaring mismatch
    for attempt in range(6):
        released = redivis.organization("datapages").dataset("peekbank")
        tag = released.get().properties.get("version", {}).get("tag")
        ok = True
        report = []
        for t, n in expected.items():
            got = int(released.table(t).get().properties.get("numRows", -1))
            ok = ok and got == n
            report.append(f"  {t}: expected {n:,}, redivis has {got:,} "
                          f"[{'OK' if got == n else 'MISMATCH'}]")
        if ok:
            break
        if attempt < 5:
            print(f"verification not clean yet (attempt {attempt + 1}), "
                  f"waiting 60s for release to propagate...", flush=True)
            time.sleep(60)
    print(f"released {version} as {tag}")
    print("\n".join(report))
    if not ok:
        sys.exit("ROW COUNT MISMATCH — investigate before staging the next version")


if __name__ == "__main__":
    main()
