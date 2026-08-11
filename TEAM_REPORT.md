# Peekbank migration: findings report (living draft)

*For the Peekbank team; assembled during the Redivis/datapage migration,
August 2026. This documents everything surprising we found while moving the
stack — data issues, legacy bugs, and decisions that changed behavior.*

## Infrastructure state we inherited

- **The Shiny visualization had been down for ~2.5 months** (since
  2026-05-27): the TLS certificate on peekbank-connect.com expired, so the
  `/shiny` iframe on the website rendered blank in all browsers. We did not
  renew it; the new in-browser visualizations replace it.
- `peekbank.stanford.edu` is an nginx redirector to the GitHub Pages site
  (`peekbank.github.io/peekbank-website`), so the eventual DNS cutover is a
  one-line change.
- The served `peekbank.json` declared `"current": "2022.1"` even though
  2025.1/2025.2/2026.1 existed; the docs "Releases" page listed only three
  of five releases; the contributors table was dated 1/9/2024 (20 datasets
  vs 44 in 2026.1); the SQL docs page said port 3306 while the README and
  peekbank.json say 3307.

## Database findings

- **2021.1 and 2022.1 are content-identical** on the hosted server: same
  dataset list, same row counts, identical id checksums on the 11.8M-row
  timepoints table. Presumably 2022.1 was minted as the citable version for
  the BRM paper from an unchanged database. Both were staged to Redivis
  faithfully (v1.0 and v1.1).
- Row counts of every staged version were verified exactly (MySQL
  `COUNT(*)` == export == Redivis) after fixing an export bug our own
  verification caught: peekbank ids start at 0 and a `WHERE id > 0` keyset
  cursor silently dropped one row per table.
- The `aoi_timepoints_indexed` table (4 GB in 2026.1) is a pure rebuild
  intermediate of the RLE migration and was not staged; `aoi_timepoints_rle`
  (the transfer-efficient form peekbankr uses) was kept.

## Legacy pipeline bugs (now baked into released data)

Replicated exactly by the new release builder for historical parity;
recommended to FIX in the next release with release-notes callouts:

1. **Leading zeros stripped from string ids.** `populate.py` reads the
   processed CSVs with pandas type inference, so string columns that look
   numeric (e.g. `lab_subject_id` "01") become integers and are stored as
   "1". Affects lab ids across datasets.
2. **Fractional gaze coordinates truncated.** The schema declares
   `xy_timepoints.x/y` as integers, but some eye-tracker datasets provide
   fractional coordinates (e.g. 732.19); Django silently `int()`-truncates
   them.
3. **`get_aoi_timepoints()` disconnected user-supplied connections**
   (peekbankr ≤0.3): any query after it on the same connection failed.
   Moot with the Redivis backend (no connections).
4. **`unpack_aux_data()` required dplyr attached** (bare `pull`/`ungroup`
   calls) — failed under `Rscript` without `library(dplyr)`. Fixed in
   peekbankr 0.4.0.

## OSF ≠ release state

- **8 datasets have no processed_data on OSF at all** (bergelson_swingley,
  ferguson_eyetrackingr, fmw_2013, nih_babytoolbox_2025 (raw data is in a
  private repo; OSF holds a 0-byte pointer), ronfard_2021,
  sander-montant_2022, xsectional_2007, yoon_simpimp_2015). Releases were
  built from local pipeline runs; OSF was never the complete intermediate
  store. These need one pipeline run to backfill into the Redivis files
  dataset.
- **OSF processed_data has drifted past the 2026.1 release** for ~5
  datasets, consistent with post-release pipeline fixes: CDI response
  de-duplication (adams_marchman_2018 aux data in 2026.1 contains each CDI
  response twice), the unified AOI computation (borovsky_2019,
  byers-heinlein_2017; peekbankr 2026-08-05), the t_norm resampling drift
  fix (nordmeyer_negtracker_2014; peekbankr 2026-06-03), and
  aoi_region_sets added after the release (byers-heinlein_2017,
  casillas_tseltal_2015). These changes will land in the next release.

## Deliberate behavior changes in the new stack

- peekbankr 0.4 returns local tibbles in all cases (previously lazy remote
  tbls when a connection was supplied); `collect()` remains a no-op.
- `get_sql_query()` now speaks BigQuery Standard SQL (case-sensitive string
  comparison; MySQL's default collation was case-insensitive).
- Version resolution is discovered from Redivis itself (each version
  carries a `release_info` table naming its source release); "current"
  means the latest release at call time and prints which release that is.
- Unpacked aux-data column order can differ from the MySQL era (it derives
  from row order, which BigQuery does not guarantee); values are identical.
- The datapage visualizations recompute everything from raw AOI data in
  the browser; unlike the Shiny app there is no "Re-load Data" button, and
  lab-excluded trials can be toggled (included by default, matching the
  Shiny behavior and the archive-everything philosophy).

## Verification methodology (for the methods-minded)

- Every Redivis version's row counts verified against exact source counts.
- peekbankr 0.4 verified against 58 characterization fixtures captured
  from the live MySQL package across three releases (225 tests green).
- The in-browser visualization pipeline verified to machine precision
  against an independent R implementation (R's `cut()`/`qbeta`/the actual
  shiny `rt_helper.R`) on three datasets spanning coding methods.
- The new release builder verified engine-exact per dataset against
  released 2026.1 wherever OSF processed_data still matches the release
  (including the 8.1M-row fernald_marchman_2012).

*(Living document — updated as the migration proceeds.)*
