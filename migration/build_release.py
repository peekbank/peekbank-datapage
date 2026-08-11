#!/usr/bin/env python3
"""Build a peekbank release from per-dataset processed_data CSVs -- the
Django/MySQL-free replacement for `manage.py populate` + rle_custom_migration.

Replicates the populate.py semantics exactly:
- datasets are processed in a specified order; per-table primary-key offsets
  are the running row counts (ids contiguous from 0 across datasets)
- global id = local csv id + table offset; local ids must be 0..n-1
- FKs remap through the same dataset's tables (target_id/distractor_id via
  the stimulus offset); aoi_region_set_id becomes NULL when the dataset has
  no aoi_region_sets.csv
- *_aux_data JSON strings are parsed and re-serialized like Django's
  JSONField (python json.dumps defaults), and validated like populate.py
- aoi_timepoints_rle is derived exactly like rle_custom_migration.py

--diff-against STAGING_DIR compares the rebuild to a staged export of a
released version (sorted by primary key, column by column) and classifies
mismatches by dataset. Datasets present in the reference but not yet
mirrored locally are skipped IF they form a suffix of the order (prefix
verification while the mirror is still running).

Usage:
  python3 migration/build_release.py --out migration/rebuild_2026.1 \
      --order-from migration/staging/2026.1 \
      --diff-against migration/staging/2026.1 [--limit N]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as pads
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
MIRROR = ROOT / "osf_mirror"
SCHEMA_FILE = ROOT.parent / "repos" / "peekbank" / "static" / "peekbank-schema.json"

TABLE_ORDER = [
    "aoi_region_sets", "datasets", "subjects", "administrations", "stimuli",
    "trial_types", "trials", "aoi_timepoints", "xy_timepoints",
]
OPTIONAL_TABLES = {"aoi_region_sets", "xy_timepoints"}

ALLOWED_AUX_KEYS = {
    "cdi_responses", "lang_measures", "lang_exposures",
    "full_phrase_language_non_iso", "native_language_non_iso",
    "lab_visit_num",
}


def load_schema():
    schema = json.load(open(SCHEMA_FILE))
    tables = {}
    for model in schema:
        if model["table"] in ("admin",):
            continue
        fields = []
        for f in model["fields"]:
            fields.append({
                "name": f["field_name"],
                "cls": f["field_class"],
                "pk": bool(f["options"].get("primary_key")),
                "to": f["options"].get("to"),
            })
        tables[model["table"]] = {
            "model_class": model["model_class"],
            "fields": fields,
            "pk": next(f["name"] for f in fields if f["pk"]),
        }
    class_to_table = {v["model_class"]: k for k, v in tables.items()}
    return tables, class_to_table


def validate_aux(obj, where):
    extra = set(obj.keys()) - ALLOWED_AUX_KEYS
    if extra:
        raise ValueError(f"{where}: unexpected aux keys {sorted(extra)}")
    for r in obj.get("cdi_responses", []):
        missing = {"instrument_type", "age", "rawscore", "language"} - set(r)
        if missing:
            raise ValueError(f"{where}: cdi_responses missing {sorted(missing)}")
        assert r["instrument_type"] in ("wg", "ws", "wsshort", "wgshort")
        assert isinstance(r["age"], (int, float))
        assert isinstance(r["rawscore"], int)
        assert isinstance(r["language"], str)


def coerce_bool(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    s = str(v).strip().upper()
    if s in ("TRUE", "T", "1"):
        return 1
    if s in ("FALSE", "F", "0"):
        return 0
    raise ValueError(f"unparseable boolean: {v!r}")


def read_table(folder, table, spec, aux_validate):
    path = folder / f"{table}.csv"
    if not path.exists():
        if table in OPTIONAL_TABLES:
            return None
        raise ValueError(f"{path} is missing")
    df = pd.read_csv(path, dtype=str, keep_default_na=True,
                     na_values=[""], low_memory=False)
    df = df.where(pd.notna(df), None)

    have, need = set(df.columns), {f["name"] for f in spec["fields"]}
    if need - have:
        raise ValueError(f"{path}: missing fields {sorted(need - have)}")
    if have - need:
        raise ValueError(f"{path}: extra fields {sorted(have - need)}")

    out = {}
    for f in spec["fields"]:
        col = df[f["name"]]
        if f["cls"] in ("IntegerField", "ForeignKey"):
            out[f["name"]] = pd.to_numeric(col, errors="raise").astype("Int64")
        elif f["cls"] == "FloatField":
            out[f["name"]] = pd.to_numeric(col, errors="raise").astype(float)
        elif f["cls"] == "BooleanField":
            out[f["name"]] = pd.array([coerce_bool(v) for v in col],
                                      dtype="Int64")
        elif f["cls"] == "JSONField":
            vals = []
            for v in col:
                if v is None:
                    vals.append(None)
                else:
                    obj = json.loads(v)
                    if aux_validate and table in ("administrations", "subjects"):
                        validate_aux(obj, f"{path}:{f['name']}")
                    vals.append(json.dumps(obj))
            out[f["name"]] = pd.array(vals, dtype="string")
        else:  # CharField, TextField, DateField (none dated in these tables)
            out[f["name"]] = col.astype("string")
    return pd.DataFrame(out)


def arrow_schema_for(spec):
    fields = []
    for f in spec["fields"]:
        if f["cls"] in ("IntegerField", "ForeignKey", "BooleanField"):
            t = pa.int64()
        elif f["cls"] == "FloatField":
            t = pa.float64()
        else:
            t = pa.string()
        fields.append(pa.field(f["name"], t))
    return pa.schema(fields)


def build_rle(aoi_df):
    """Derive aoi_timepoints_rle exactly like rle_custom_migration.py."""
    df = aoi_df.sort_values(
        ["administration_id", "trial_id", "t_norm"], kind="mergesort")
    key_change = (
        (df["administration_id"] != df["administration_id"].shift()) |
        (df["trial_id"] != df["trial_id"].shift()) |
        (df["aoi"] != df["aoi"].shift())
    )
    grp = key_change.cumsum()
    runs = df.groupby(grp, sort=False).agg(
        administration_id=("administration_id", "first"),
        trial_id=("trial_id", "first"),
        t_norm=("t_norm", "min"),
        aoi=("aoi", "first"),
        length=("aoi", "size"),
    ).reset_index(drop=True)
    runs["length"] = runs["length"].astype("Int64")
    return runs.sort_values(["administration_id", "trial_id", "t_norm"],
                            kind="mergesort").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--order-from", required=True,
                    help="staged export dir whose datasets table defines order")
    ap.add_argument("--diff-against", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--source", default=str(MIRROR))
    args = ap.parse_args()

    source = Path(args.source)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tables, class_to_table = load_schema()

    ref_datasets = pads.dataset(
        sorted((Path(args.order_from) / "datasets").glob("part-*.parquet"))
    ).to_table(columns=["dataset_id", "dataset_name"]).to_pylist()
    ref_datasets.sort(key=lambda r: r["dataset_id"])
    order = [r["dataset_name"] for r in ref_datasets]
    if args.limit:
        order = order[: args.limit]

    available = []
    for name in order:
        pd_dir = source / name / "processed_data"
        if pd_dir.is_dir() and (source / name / ".mirror_done").exists():
            available.append(name)
        else:
            break  # prefix only: stopping keeps offsets exact
    if not available:
        sys.exit("no complete prefix of the dataset order is mirrored yet")
    print(f"building prefix of {len(available)}/{len(order)} datasets: "
          f"{available}")

    offsets = {t: 0 for t in TABLE_ORDER}
    accum = {t: [] for t in TABLE_ORDER}
    for name in available:
        folder = source / name / "processed_data"
        local = {}
        for table in TABLE_ORDER:
            spec = tables[table]
            df = read_table(folder, table, spec, aux_validate=True)
            local[table] = df
            if df is None:
                continue
            pk = spec["pk"]
            ids = df[pk].to_numpy()
            if not np.array_equal(np.sort(ids), np.arange(len(ids))):
                raise ValueError(f"{name}/{table}: local {pk} not 0..n-1")
            # remap FKs through this dataset's own tables
            for f in spec["fields"]:
                if f["cls"] != "ForeignKey":
                    continue
                fk_table = class_to_table[f["to"]]
                if local.get(fk_table) is None:
                    df[f["name"]] = pd.array([None] * len(df), dtype="Int64")
                    continue
                fk_local = df[f["name"]]
                n_target = len(local[fk_table])
                bad = fk_local.dropna()[(fk_local.dropna() < 0) |
                                        (fk_local.dropna() >= n_target)]
                if len(bad):
                    raise ValueError(
                        f"{name}/{table}.{f['name']}: {len(bad)} FKs outside "
                        f"0..{n_target - 1}")
                df[f["name"]] = fk_local + offsets[fk_table]
            df[pk] = df[pk] + offsets[table]
            accum[table].append(df)
        for table in TABLE_ORDER:
            if local.get(table) is not None:
                offsets[table] += len(local[table])
        print(f"  {name}: " + ", ".join(
            f"{t}={len(local[t])}" for t in TABLE_ORDER
            if local.get(t) is not None))

    built = {}
    for table in TABLE_ORDER:
        if not accum[table]:
            continue
        df = pd.concat(accum[table], ignore_index=True)
        built[table] = df
        pq.write_table(
            pa.Table.from_pandas(df, schema=arrow_schema_for(tables[table]),
                                 preserve_index=False),
            out / f"{table}.parquet", compression="zstd")
    rle = build_rle(built["aoi_timepoints"])
    rle_schema = pa.schema([
        pa.field("administration_id", pa.int64()),
        pa.field("trial_id", pa.int64()),
        pa.field("t_norm", pa.int64()),
        pa.field("aoi", pa.string()),
        pa.field("length", pa.int64()),
    ])
    pq.write_table(pa.Table.from_pandas(rle, schema=rle_schema,
                                        preserve_index=False),
                   out / "aoi_timepoints_rle.parquet", compression="zstd")
    built["aoi_timepoints_rle"] = rle
    print("built tables:", {t: len(d) for t, d in built.items()})

    if not args.diff_against:
        return

    print(f"\n=== diff vs {args.diff_against} (prefix of "
          f"{len(available)} datasets) ===")
    ds_ranges = []  # (name, table -> (lo, hi)) for classification
    ok_all = True
    for table, df in built.items():
        ref_dir = Path(args.diff_against) / table
        ref = pads.dataset(sorted(ref_dir.glob("part-*.parquet"))).to_table()
        ref_df = ref.to_pandas(types_mapper=None)
        spec_pk = (tables[table]["pk"] if table in tables
                   else ["administration_id", "trial_id", "t_norm"])
        if table == "aoi_timepoints_rle":
            sort_cols = ["administration_id", "trial_id", "t_norm"]
            # restrict reference to the built administration prefix
            max_admin = df["administration_id"].max()
            ref_df = ref_df[ref_df["administration_id"] <= max_admin]
        else:
            sort_cols = [spec_pk]
            ref_df = ref_df[ref_df[spec_pk] < len(df)]
        a = df.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
        b = ref_df.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
        if len(a) != len(b):
            print(f"  {table}: ROW COUNT {len(a)} rebuilt vs {len(b)} reference")
            ok_all = False
            continue
        diffs = {}
        for col in b.columns:
            av = a[col].astype(object).where(pd.notna(a[col]), None)
            bv = b[col].astype(object).where(pd.notna(b[col]), None)
            neq = ~(av.eq(bv) | (av.isna() & bv.isna()))
            # float tolerance
            if b[col].dtype.kind == "f":
                af = pd.to_numeric(a[col], errors="coerce")
                bf = pd.to_numeric(b[col], errors="coerce")
                neq = ~(np.isclose(af, bf, rtol=0, atol=1e-9, equal_nan=True))
            n = int(pd.Series(neq).sum())
            if n:
                diffs[col] = n
        if diffs:
            ok_all = False
            print(f"  {table}: MISMATCHES {diffs}")
            col = next(iter(diffs))
            idx = pd.Series(
                ~(a[col].astype(object).where(pd.notna(a[col]), None)
                  .eq(b[col].astype(object).where(pd.notna(b[col]), None)) |
                  (a[col].isna() & b[col].isna()))).idxmax()
            print(f"    first diff [{col}] row {idx}: "
                  f"rebuilt={a[col].iloc[idx]!r} ref={b[col].iloc[idx]!r}")
        else:
            print(f"  {table}: OK ({len(a):,} rows)")
    print("PREFIX DIFF:", "PASS" if ok_all else "FAIL")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
