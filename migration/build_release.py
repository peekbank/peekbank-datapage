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
    # read with pandas type inference, exactly like populate.py: this
    # deliberately REPLICATES the legacy pipeline's string mangling (e.g.
    # lab_subject_id "01" -> int 1 -> stored "1"), which is baked into the
    # released databases. Faithful-string reading is a candidate behavior
    # change for future releases -- decide explicitly, don't drift.
    df = pd.read_csv(path, low_memory=False)
    # NOTE: .where(cond, None) does NOT insert None (None = default NaN);
    # replace() is what populate.py itself uses
    df = df.replace({np.nan: None})

    have, need = set(df.columns), {f["name"] for f in spec["fields"]}
    if need - have:
        raise ValueError(f"{path}: missing fields {sorted(need - have)}")
    if have - need:
        raise ValueError(f"{path}: extra fields {sorted(have - need)}")

    out = {}
    for f in spec["fields"]:
        col = df[f["name"]]
        if f["cls"] in ("IntegerField", "ForeignKey"):
            num = pd.to_numeric(col, errors="raise")
            try:
                out[f["name"]] = num.astype("Int64")
            except TypeError:
                # fractional values in an integer column: Django's
                # IntegerField applies int() (truncation toward zero) --
                # e.g. gaze x/y coordinates in some eye-tracker datasets
                out[f["name"]] = pd.array(
                    [None if v is None or
                     (isinstance(v, float) and np.isnan(v)) else int(v)
                     for v in num], dtype="Int64")
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
        else:  # CharField, TextField: Django stringifies whatever pandas
            # inferred (int 1 -> "1", float 1.0 -> "1.0", bool -> "True")
            out[f["name"]] = pd.array(
                [None if v is None else str(v) for v in col], dtype="string")
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
    def changed(s):
        return s.ne(s.shift()).fillna(True).to_numpy(dtype=bool)

    key_change = pd.Series(
        changed(df["administration_id"]) | changed(df["trial_id"]) |
        changed(df["aoi"]), index=df.index)
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


def ref_slice(ref_dir, table, columns=None, filt=None):
    ds = pads.dataset(sorted((Path(ref_dir) / table).glob("part-*.parquet")))
    t = ds.to_table(columns=columns, filter=filt)
    return t.to_pandas()


def compare_frames(name, built, ref, float_cols):
    """Compare two frames (same columns) after sorting; return list of diffs."""
    problems = []
    if len(built) != len(ref):
        return [f"{name}: rows {len(built)} built vs {len(ref)} reference"]
    a = built.reset_index(drop=True)
    b = ref[built.columns].reset_index(drop=True)
    for col in built.columns:
        av = a[col]
        bv = b[col]
        if col in float_cols:
            neq = ~np.isclose(pd.to_numeric(av, errors="coerce"),
                              pd.to_numeric(bv, errors="coerce"),
                              rtol=0, atol=1e-9, equal_nan=True)
        else:
            ao = av.astype(object).where(pd.notna(av), None)
            bo = bv.astype(object).where(pd.notna(bv), None)
            neq = ~(ao.eq(bo) | (ao.isna() & bo.isna()))
        n = int(pd.Series(neq).sum())
        if n:
            i = int(pd.Series(neq).idxmax())
            problems.append(
                f"{name}.{col}: {n} mismatches; first at row {i}: "
                f"built={a[col].iloc[i]!r} ref={b[col].iloc[i]!r}")
    return problems


def per_dataset_diff(source, ref_dir, tables, class_to_table, only=None):
    """Validate the build engine dataset-by-dataset: build each dataset
    standalone (zero offsets) and compare against the reference release's
    rows for that dataset with the reference's own id offsets subtracted.
    Immune to gaps in local processed_data coverage and to dataset order."""
    import pyarrow.compute as pc

    ref_datasets = ref_slice(ref_dir, "datasets")
    name_to_id = dict(zip(ref_datasets.dataset_name, ref_datasets.dataset_id))
    float_cols_by_table = {
        t: {f["name"] for f in spec["fields"] if f["cls"] == "FloatField"}
        for t, spec in tables.items()}

    candidates = []
    for name in sorted(name_to_id):
        src_name = name if name != "newman_sinewave_2015" else "newman_sinewave"
        folder = source / src_name / "processed_data"
        if folder.is_dir() and (source / src_name / ".mirror_done").exists():
            if only is None or name in only:
                candidates.append((name, folder))
    print(f"per-dataset diff: {len(candidates)} datasets with local "
          f"processed_data: {[c[0] for c in candidates]}")

    overall_ok = True
    for name, folder in candidates:
        ds_id = name_to_id[name]
        # build standalone (offsets all zero)
        local = {}
        try:
            for table in TABLE_ORDER:
                local[table] = read_table(folder, table, tables[table],
                                          aux_validate=False)
        except Exception as e:
            print(f"  {name}: BUILD ERROR {e}")
            overall_ok = False
            continue

        # reference rows for this dataset
        ref = {}
        ref["datasets"] = ref_slice(ref_dir, "datasets",
                                    filt=pc.field("dataset_id") == ds_id)
        ref["administrations"] = ref_slice(
            ref_dir, "administrations", filt=pc.field("dataset_id") == ds_id)
        admin_ids = ref["administrations"].administration_id.to_numpy()
        subj_ids = np.unique(ref["administrations"].subject_id.to_numpy())
        ref["subjects"] = ref_slice(
            ref_dir, "subjects", filt=pc.field("subject_id").isin(subj_ids))
        ref["stimuli"] = ref_slice(ref_dir, "stimuli",
                                   filt=pc.field("dataset_id") == ds_id)
        ref["trial_types"] = ref_slice(
            ref_dir, "trial_types", filt=pc.field("dataset_id") == ds_id)
        tt_ids = ref["trial_types"].trial_type_id.to_numpy()
        ref["trials"] = ref_slice(
            ref_dir, "trials", filt=pc.field("trial_type_id").isin(tt_ids))
        ars_ids = ref["trial_types"].aoi_region_set_id.dropna().unique()
        ref["aoi_region_sets"] = ref_slice(
            ref_dir, "aoi_region_sets",
            filt=pc.field("aoi_region_set_id").isin(ars_ids)) \
            if len(ars_ids) else None
        ref["aoi_timepoints"] = ref_slice(
            ref_dir, "aoi_timepoints",
            filt=pc.field("administration_id").isin(admin_ids))
        ref["xy_timepoints"] = ref_slice(
            ref_dir, "xy_timepoints",
            filt=pc.field("administration_id").isin(admin_ids))
        if len(ref["xy_timepoints"]) == 0:
            ref["xy_timepoints"] = None

        # per-table id bases from the reference (contiguity checked)
        bases = {}
        problems = []
        for table in TABLE_ORDER:
            r = ref.get(table)
            if r is None or len(r) == 0:
                bases[table] = None
                continue
            pk = tables[table]["pk"]
            ids = np.sort(r[pk].to_numpy())
            if not np.array_equal(ids, np.arange(ids[0], ids[0] + len(ids))):
                problems.append(f"{table}: reference ids not contiguous")
            bases[table] = int(ids[0])
        if problems:
            print(f"  {name}: {problems}")
            overall_ok = False
            continue

        # rebase reference ids to zero and compare
        for table in TABLE_ORDER:
            built, r = local.get(table), ref.get(table)
            if built is None and (r is None or len(r) == 0):
                continue
            if built is None or r is None:
                print(f"  {name}/{table}: presence mismatch "
                      f"(built={built is not None}, ref={r is not None})")
                overall_ok = False
                continue
            r = r.copy()
            spec = tables[table]
            r[spec["pk"]] -= bases[table]
            for f in spec["fields"]:
                if f["cls"] != "ForeignKey":
                    continue
                fk_table = class_to_table[f["to"]]
                if bases.get(fk_table) is not None:
                    r[f["name"]] -= bases[fk_table]
            sort_cols = [spec["pk"]]
            built_s = built.sort_values(sort_cols).reset_index(drop=True)
            r_s = r.sort_values(sort_cols).reset_index(drop=True)
            problems.extend(compare_frames(
                f"{table}", built_s, r_s, float_cols_by_table[table]))

        # RLE: derive from built aoi and compare to rebased reference rle
        rle_built = build_rle(local["aoi_timepoints"])
        rle_ref = ref_slice(
            ref_dir, "aoi_timepoints_rle",
            filt=pc.field("administration_id").isin(admin_ids)).copy()
        rle_ref["administration_id"] -= bases["administrations"]
        rle_ref["trial_id"] -= bases["trials"]
        key = ["administration_id", "trial_id", "t_norm"]
        problems.extend(compare_frames(
            "aoi_timepoints_rle",
            rle_built.sort_values(key).reset_index(drop=True),
            rle_ref.sort_values(key).reset_index(drop=True),
            set()))

        if problems:
            overall_ok = False
            print(f"  {name}: FAIL")
            for p in problems[:6]:
                print(f"    {p}")
        else:
            n = sum(len(v) for v in local.values() if v is not None)
            print(f"  {name}: OK ({n:,} rows across tables)")

    print("PER-DATASET DIFF:", "PASS" if overall_ok else "FAIL")
    return overall_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--order-from", required=True,
                    help="staged export dir whose datasets table defines order")
    ap.add_argument("--diff-against", default=None)
    ap.add_argument("--per-dataset-diff", action="store_true",
                    help="validate engine per dataset against --diff-against "
                         "(order/gap independent); skips the full build")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--source", default=str(MIRROR))
    args = ap.parse_args()

    if args.per_dataset_diff:
        tables_, class_to_table_ = load_schema()
        ok = per_dataset_diff(Path(args.source), args.diff_against or
                              args.order_from, tables_, class_to_table_,
                              only=set(args.only) if args.only else None)
        sys.exit(0 if ok else 1)

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
