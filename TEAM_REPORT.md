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
  faithfully (v1.0 and v1.1). *See the provenance investigation below —
  the CogSci-era 15-dataset state was never a named release.*

## The missing 2021.1 (CogSci) release — provenance and recovery (Sept 2026)

Adrian's finding (Sept 2026): the hosted "2021.1" carries the same 20
datasets as 2022.1, so the 15-dataset version behind Zettersten et al.
(2021, CogSci) is not on Redivis. Investigation results:

**What happened (his option B, now with receipts).** peekbankr through at
least mid-2021 defaulted to `dbname = "peekbank"` — an *unversioned*
schema on the same host. The CogSci analysis (finalized May 2021) predates
release versioning (introduced June 2021) entirely; it read the live
unversioned database via `connect_to_peekbank()`. When the "2021.1" schema
was created on 2021-10-07, the import repo already carried 20 datasets, so
the retroactive label captured the then-current data, not the paper-era
state. Our byte-identical id checksums between 2021.1 and 2022.1 fit two
deterministic populate runs over unchanged inputs. Nothing was
overwritten; a named 15-dataset release never existed. The recovery target
is the pre-versioning `peekbank` schema as of ~May 2021.

**The paper's exact data survives in git.** peekbank-paper commit
`f527238` (2021-05-07) contains the analysis cache, pulled from that
unversioned database days before submission:

- `cogsci2021/data/dataset_info.Rds` — 1,521 administrations, 1,320
  subjects, and the definitive 15 datasets *with their original database
  ids*: casillas_tseltal_2015 (0), perry_cowpig (1), pomper_saffran_2016
  (2), adams_marchman_2018 (3), pomper_salientme (4), swingley_aslin_2002
  (5), reflook_v4 (6), reflook_socword (7), potter_remix (8),
  potter_canine (9), attword_processed (10), garrison_bergelson_2020 (11),
  mahr_coartic (12), byers-heinlein_2017 (13), frank_tablet_2016 (14).
- `cogsci2021/data/aoi_data_joined.Rds` — 5,419,501 aoi timepoints × 38
  columns (t_norm −975..2975), carrying original ids for aoi_timepoints,
  trials, trial_types, administrations, subjects, stimuli, and datasets.
  (Both files are `save()`-written RData despite the .Rds extension.)
- Derived-stats CSVs (`participant_means_prop_looking.csv`, time-window
  results, etc.) — verification targets for "reproduces the paper's
  stats".

**Recovery plan (no SQL backup required).** Seven of the nine tables can
be re-derived *exactly* (original ids preserved) by normalizing the joined
fixture. The two absent pieces — `xy_timepoints` and `aoi_region_sets` —
come from the era's ingest inputs: that pipeline pushed each dataset's
`processed_data/` to OSF, and OSF retains file version history, so the
≤May-2021 versions are recoverable via the OSF API (4 datasets also have
processed CSVs committed in peekbank-data-import at the freeze-era commit
`22a9bce` as cross-checks). Verify the reconstruction against the paper's
derived-stats CSVs, then stage to Redivis as a new version whose
`release_info` names it (e.g. "2021.0 (CogSci)"); note Redivis versions
are append-only, so it will sit after v1.4 in tag order with the naming
carried by `release_info`, which is what peekbankr resolves.

**A real backup would still add value** (independent validation; xy data
as-ingested): candidates are EBS snapshots/AMIs of the pre-2025 server,
S3-side mysqldump crons, and the old MySQL data directory if it survived
the April-2025 Docker/MariaDB migration on disk. **Do not terminate the
EC2 instance or delete its volumes until that disk has been checked.**
Mike's Google Drive has no dumps (searched Sept 2026); the box itself has
been unreachable since Aug 2026.
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

- **One file is corrupted on OSF itself**:
  `pomper_saffran_2016/raw_data/README.md` (3,306 bytes per OSF metadata)
  returns a persistent HTTP 400 from OSF's own download endpoint
  (https://osf.io/download/q8x4k/), including in a browser. Its content
  could not be mirrored and appears unrecoverable without OSF support; an
  older (2020, 437-byte) local variant exists in the team's archives but is
  not the same file. The dataset's top-level README is intact. Consider
  reporting to support@osf.io or re-authoring the raw-data README.

- **8 datasets have no processed_data on OSF at all** (bergelson_swingley,
  ferguson_eyetrackingr, fmw_2013, nih_babytoolbox_2025 (raw data is in a
  private repo; OSF holds a 0-byte pointer), ronfard_2021,
  sander-montant_2022, xsectional_2007, yoon_simpimp_2015). Releases were
  built from local pipeline runs; OSF was never the complete intermediate
  store. These need one pipeline run to backfill into the Redivis files
  dataset.
- **OSF processed_data has drifted past the 2026.1 release for 20 of the
  36 datasets with processed_data on OSF** (full rebuild-vs-release sweep;
  the other 16 rebuild byte-exactly). Every difference classifies as
  post-release pipeline evolution, in five signatures: (1) recomputed AOI
  time courses and added/changed aoi_region_sets across the eye-tracking
  datasets (the 2026-08 unified AOI computation + the 2026-06 t_norm
  resampling fix; 16 datasets); (2) aux-data CDI corrections
  (adams_marchman_2018 — where 2026.1 contains each CDI response twice —
  baumgartner_2014, newman_sinewave_2015); (3) trial-type re-annotation
  (adams_marchman_2018: condition, target/distractor assignment,
  vanilla_trial flags); (4) stimulus re-annotation (garrison_bergelson_2020:
  labels, image descriptions, paths); (5) added data
  (reflook_socword: +2 subjects, +40 trials). No rebuild-engine
  discrepancies remain: the next release will absorb all of this
  intentionally.

- **Aux JSON ages lose precision on re-import under current defaults**: the
  pipeline currently serializes CDI ages in `*_aux_data` at 4 significant
  digits (jsonlite default; e.g. 15.377 where the released data has
  15.3770491803279). Verified in the end-to-end rerun of
  swingley_aslin_2002, where this was the ONLY difference from the released
  2026.1. Recommend `digits = NA` in the peekds writer before the next
  release.

- **The 7 regenerable missing-processed_data datasets have been backfilled**
  (2026-08-11): xsectional_2007, ronfard_2021, ferguson_eyetrackingr,
  fmw_2013, bergelson_swingley_2012, sander-montant_2022, and
  yoon_simpimp_2015 were re-imported through the new pipeline (raw data
  from Redivis), passed all validators, and are staged in the
  peekbank_files draft for the next files release. nih_babytoolbox_2025
  remains blocked on its private raw data.
- **The legacy MySQL server became unreachable during the migration day**
  (connection timeout from 2026-08-11 afternoon; it served normally that
  morning). All releases, fixtures, and files had already been captured.
  Anyone still on peekbankr ≤0.3 has no working backend — upgrading to
  0.4.0 (now on master) is the fix.

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

## End-to-end verification of the new release path

The full Django-free pipeline was exercised on swingley_aslin_2002:
raw data downloaded from the released `peekbank_files` dataset → the
unmodified `import.R` → all peekds validators pass → processed CSVs
byte-identical to the OSF-era copies (except the aux-digits wrinkle above)
→ staged into the files draft (same-named files replace idempotently) →
release tables built and matching the released 2026.1 (same wrinkle only).

*(Living document — updated as the migration proceeds.)*
