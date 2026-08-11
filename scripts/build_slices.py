#!/usr/bin/env python3
"""Build per-dataset JSON slices for the datapage from staged parquet.

Reads migration/staging/<version>/ (local export of the release; later this
can point at Redivis-downloaded parquet) and writes:

  slices/manifest.json          selector + landing-table metadata
  slices/datasets/<name>.json   per-dataset slice for the interactive viz

Slice format (compact arrays; aoi coded 0=target 1=distractor 2=other 3=missing):
  admins:      [[administration_id, age_months(2dp), subject_id], ...]
  trials:      [[trial_id, trial_order, trial_type_id, excluded01], ...]
  trial_types: [[trial_type_id, target_label, distractor_label, condition,
                 vanilla01, novel01], ...]
  runs:        [[administration_id, trial_id, t0, [[aoi, len], ...]], ...]
               (runs are contiguous 25 ms samples from t0, matching
                peekbankr's RLE decode assumptions)

Usage: python3 scripts/build_slices.py [--version 2026.1]
"""

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

import pyarrow.dataset as pads

REPO_ROOT = Path(__file__).resolve().parent.parent
AOI_CODE = {"target": 0, "distractor": 1, "other": 2, "missing": 3}
REDIVIS_TAG = None  # set from --from-redivis


def read(version, table, columns=None):
    if REDIVIS_TAG:
        for line in open(REPO_ROOT / ".secrets"):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)
        import redivis
        tb = redivis.organization("datapages").dataset(
            "peekbank:a3v0", version=REDIVIS_TAG).table(table)
        t = tb.to_arrow_table()
        return t.select(columns) if columns else t
    d = REPO_ROOT / "migration" / "staging" / version / table
    return pads.dataset(sorted(d.glob("part-*.parquet"))).to_table(columns=columns)


def main():
    global REDIVIS_TAG
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="2026.1")
    ap.add_argument("--from-redivis", default=None, metavar="TAG",
                    help="read tables from datapages.peekbank at this "
                         "Redivis version tag (e.g. v1.4) instead of "
                         "migration/staging/<version>")
    args = ap.parse_args()
    v = args.version
    REDIVIS_TAG = args.from_redivis

    out_root = REPO_ROOT / "slices"
    (out_root / "datasets").mkdir(parents=True, exist_ok=True)

    datasets = read(v, "datasets").to_pylist()
    admins = read(v, "administrations",
                  ["administration_id", "age", "dataset_id", "subject_id",
                   "coding_method"]).to_pylist()
    subjects = {s["subject_id"]: s for s in read(
        v, "subjects", ["subject_id", "native_language"]).to_pylist()}
    stimuli = {s["stimulus_id"]: s for s in read(
        v, "stimuli", ["stimulus_id", "english_stimulus_label",
                       "stimulus_novelty", "dataset_id"]).to_pylist()}
    trial_types = read(v, "trial_types",
                       ["trial_type_id", "dataset_id", "target_id",
                        "distractor_id", "condition", "vanilla_trial",
                        "full_phrase_language"]).to_pylist()
    trials = read(v, "trials",
                  ["trial_id", "trial_order", "trial_type_id",
                   "excluded"]).to_pylist()

    tt_by_ds = defaultdict(list)
    tt_ds = {}
    for tt in trial_types:
        tt_by_ds[tt["dataset_id"]].append(tt)
        tt_ds[tt["trial_type_id"]] = tt["dataset_id"]
    trials_by_ds = defaultdict(list)
    trial_ds = {}
    for t in trials:
        ds_id = tt_ds[t["trial_type_id"]]
        trials_by_ds[ds_id].append(t)
        trial_ds[t["trial_id"]] = ds_id
    admins_by_ds = defaultdict(list)
    for a in admins:
        admins_by_ds[a["dataset_id"]].append(a)

    # RLE runs grouped per dataset -> (admin, trial)
    rle = read(v, "aoi_timepoints_rle")
    runs_by_ds = defaultdict(lambda: defaultdict(list))
    cols = [rle.column(c).to_pylist()
            for c in ["administration_id", "trial_id", "t_norm", "aoi", "length"]]
    for aid, tid, t_norm, aoi, length in zip(*cols):
        runs_by_ds[trial_ds[tid]][(aid, tid)].append(
            (t_norm, AOI_CODE[aoi], length))

    manifest = {"version": v, "datasets": []}
    for ds in sorted(datasets, key=lambda d: d["dataset_name"]):
        ds_id, name = ds["dataset_id"], ds["dataset_name"]
        da = admins_by_ds[ds_id]
        dt = trials_by_ds[ds_id]
        dtt = tt_by_ds[ds_id]
        ages = [a["age"] for a in da if a["age"] is not None]
        langs = sorted({tt["full_phrase_language"] for tt in dtt
                        if tt["full_phrase_language"]})
        methods = sorted({a["coding_method"] for a in da if a["coding_method"]})
        words = sorted({stimuli[tt["target_id"]]["english_stimulus_label"]
                        for tt in dtt if tt["target_id"] in stimuli})

        slice_obj = {
            "dataset": {"id": ds_id, "name": name,
                        "shortcite": ds["shortcite"], "cite": ds["cite"]},
            "admins": [[a["administration_id"],
                        round(a["age"], 2) if a["age"] is not None else None,
                        a["subject_id"]] for a in da],
            "trials": [[t["trial_id"], t["trial_order"], t["trial_type_id"],
                        1 if t["excluded"] else 0] for t in dt],
            "trial_types": [[tt["trial_type_id"],
                             stimuli.get(tt["target_id"], {}).get(
                                 "english_stimulus_label"),
                             stimuli.get(tt["distractor_id"], {}).get(
                                 "english_stimulus_label"),
                             tt["condition"],
                             1 if tt["vanilla_trial"] else 0,
                             0 if stimuli.get(tt["target_id"], {}).get(
                                 "stimulus_novelty") == "familiar" else 1]
                            for tt in dtt],
            "runs": [[aid, tid, runs[0][0],
                      [[aoi, ln] for (_, aoi, ln) in runs]]
                     for (aid, tid), runs in sorted(runs_by_ds[ds_id].items())
                     for runs in [sorted(runs)]],
        }
        out_path = out_root / "datasets" / f"{name}.json"
        out_path.write_text(json.dumps(slice_obj, separators=(",", ":")))

        manifest["datasets"].append({
            "name": name, "shortcite": ds["shortcite"], "cite": ds["cite"],
            "n_subjects": len({a["subject_id"] for a in da}),
            "n_admins": len(da), "n_trials": len(dt),
            "age_min": round(min(ages), 1) if ages else None,
            "age_max": round(max(ages), 1) if ages else None,
            "methods": methods, "languages": langs,
            "n_words": len(words),
            "native_languages": sorted({
                subjects[a["subject_id"]]["native_language"] or ""
                for a in da if a["subject_id"] in subjects} - {""}),
            "kb": out_path.stat().st_size // 1024,
        })
        print(f"{name}: {len(da)} admins, {len(dt)} trials, "
              f"{len(runs_by_ds[ds_id])} run-groups, "
              f"{out_path.stat().st_size / 1e6:.2f} MB")

    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=1))
    total = sum(d["kb"] for d in manifest["datasets"]) / 1024
    print(f"\n{len(manifest['datasets'])} datasets, {total:.1f} MB total slices")


if __name__ == "__main__":
    main()
