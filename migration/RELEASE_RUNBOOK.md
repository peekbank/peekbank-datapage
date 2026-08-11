# Peekbank release runbook (Redivis era)

How to cut a new Peekbank release (e.g. `2027.1`) without the Django/MySQL
stack. Everything here lives in this repo (`migration/`) and
`peekbank/peekbank-data-import` (branch `redivis` until merged).

## 0. Prereqs

- `REDIVIS_API_TOKEN` in `.secrets` at the repo root: an org token for
  `datapages` with data-edit + `organization.read` (the release endpoint
  needs the org scope).
- Python venv: `python3 -m venv .venv && .venv/bin/pip install pymysql
  pyarrow redivis` (pymysql only needed while the legacy MySQL exports
  remain relevant).

## 1. Import / process datasets (peekbank-data-import)

Per dataset, as today: `import.R` downloads raw data (now from the
`datapages.peekbank_files` Redivis dataset via
`helper_functions/redivis.R::get_raw_data_redivis`), processes to peekds
CSVs, validates (peekbankr validators), and stages outputs
(`upload_redivis`) into the **draft next version** of `peekbank_files`
(processed_data + README per dataset). The draft plays the role the dev
MySQL schemas used to play: org members can see it, the public cannot.

## 2. Build the release tables

```bash
.venv/bin/python migration/build_release.py \
    --source <dir with per-dataset processed_data/> \
    --order-from migration/staging/2026.1 \
    --out migration/rebuild_<release>
```

- Replaces `manage.py populate` + `rle_custom_migration`: assigns global
  ids (running per-table offsets over the dataset order), remaps FKs,
  re-serializes aux JSON, derives `aoi_timepoints_rle`, writes parquet.
- **Dataset order**: for reproducing an old release, take the order from
  its `datasets` table (`--order-from`). For a NEW release, keep the
  previous release's order for existing datasets and append new datasets
  at the end (stable ids for unchanged prefixes are NOT guaranteed by the
  legacy process either — ids are release-internal; `lab_*` ids are the
  stable keys).
- `--diff-against migration/staging/<old-release>` runs the
  characterization diff when rebuilding an existing release (engine
  verification; expect PASS before trusting the builder on new data).

## 3. Stage + release the tabular dataset

```bash
.venv/bin/python migration/upload_redivis.py --version <release>   # draft
# verify the printed row counts, then after sign-off:
.venv/bin/python migration/upload_redivis.py --version <release> --release
```

Note: `add_files()` on the files table REPLACES same-named files in the
draft (verified), so re-staging a dataset's processed_data is idempotent —
no delete step needed.

(Point it at the rebuild output by placing it under
`migration/staging/<release>/<table>/part-*.parquet`, or adapt the
`table_files` glob. Every version gets the synthetic one-row
`release_info` table — that is how peekbankr resolves version names, so DO
NOT skip it.)

Then release the `peekbank_files` draft (files dataset) the same two-phase
way: `migration/upload_files_redivis.py [--release]`.

## 4. Refresh the datapage

```bash
.venv/bin/python scripts/build_slices.py --version <release>
# (reads migration/staging/<release>; --from-redivis mode TODO)
node scripts/validate_viz.mjs <a dataset>   # JS side of the parity check
Rscript scripts/validate_viz.R <a dataset>  # R reference; expect PASS
git add slices && git commit && git push    # CI renders + deploys Pages
```

## 5. peekbankr

Nothing to do for a normal release: `connect_to_peekbank()` resolves
"current" to the new latest version at call time and announces the release
name from `release_info`. Update the pkgdown site / NEWS when the package
itself changes.

## Legacy notes

- The five MySQL-era releases (2021.1 → 2026.1 = Redivis v1.0 → v1.4) were
  staged verbatim by `migration/export_mysql.py` + `upload_redivis.py`;
  `migration/verify_export.py` holds the exact-count verification pattern.
- 2021.1 and 2022.1 are content-identical on the legacy server (verified
  by id-checksums); this is faithful to history.
- The EC2 MariaDB + Django stack can be retired once the team signs off on
  the new path (peekbank.json's successor fields + deprecation notice are
  the last step; see PLAN.md Stage 7).
