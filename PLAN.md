# Peekbank → Redivis datapage migration plan

*Drafted 2026-08-11; updated end of day 1 (stages 1, 2, 4 complete; 3, 5, 6 near-complete). Follows the wordbank / childes-db playbook
(`~/Projects/shiny-to-observable-advice.md`).*

## Current architecture (as surveyed)

- **Hosted DB**: MariaDB on AWS EC2 (34.210.173.143:3307), public read creds,
  one schema per release: `2021.1` (1.8 GB), `2022.1` (1.8 GB), `2025.1`
  (5.6 GB), `2025.2` (6.4 GB), `2026.1` (7.2 GB) + three dev schemas
  (`peekbank_dev`, `workshop_2024_dev`, `grant_2024_dev`).
  2026.1: 44 datasets, 5,590 administrations, 131,824 trials, 35.1M
  `aoi_timepoints` rows, 9.2M `xy_timepoints` rows.
  Version config JSON: `peekbank.github.io/peekbank-website/peekbank.json`
  (note: `current` field says 2022.1 — appears stale).
- **Schema** (9 canonical tables): `datasets`, `subjects`, `administrations`,
  `trials`, `trial_types`, `stimuli`, `aoi_region_sets`, `aoi_timepoints`
  (40 Hz, `t_norm` centered on target-word onset, `aoi` ∈
  target/distractor/other/missing), `xy_timepoints`. Plus derived MySQL
  transfer optimizations (`aoi_timepoints_rle`, `aoi_timepoints_indexed`) and
  Django bookkeeping (`admin`, `django_migrations`). `*_aux_data` JSON string
  columns carry CDI scores etc.
- **Raw + processed data**: OSF node `pr6wu`, one folder per dataset with
  `raw_data/` (incl. stimulus images/audio), `processed_data/` (peekds CSVs),
  `README.md`. OSF file storage is sunsetting → must move to Redivis files.
  Full census (2026-08-11, `migration/osf_inventory/`): **52 dataset folders,
  7,103 files, 15.36 GB** — raw_data 85.9% / processed_data 7.7% / other 6.4%
  (mostly reflook_v4's extra `full_dataset/`). Top 4 datasets hold ~53% of
  bytes; ~82% of bytes are tabular text (great compression ahead). No OSF
  component nodes. Wrinkle: `nih_babytoolbox_2025` raw data is a 0-byte
  pointer (lives in a private repo). 52 OSF folders vs 44 datasets in 2026.1:
  9 folders are unreleased/in-pipeline (steil_schild_2021,
  steil_friedrich_2025, ofallon_storybook_2020,
  dombroski_backgroundnoise_2014, newman_vocoded_2012, newman_vocoded_2020,
  newman_multitalker_2011, nih_babytoolbox_2025 pointer stub, plus
  newman_sinewave which the DB calls newman_sinewave_2015).
- **Pipeline**: `peekbank-data-import` (per-dataset `import.R` → peekds CSVs,
  validated by peekbankr's peekds validators, uploaded to OSF) → `peekbank`
  Django app (populate MySQL, assign global IDs, build RLE tables, promote
  dev → named release schema).
- **Access**: `peekbankr` (MySQL + RLE decode + OSF helpers), direct SQL,
  mysqldump for local copies.
- **Web**: `peekbank.stanford.edu` is just an nginx **307 redirector** to
  `peekbank.github.io/peekbank-website/<path>` — the live site is the
  Astro/Starlight docs+landing site (GH Pages, Feb 2026). It iframes the
  Shiny viz app at `peekbank-connect.com/viz` (Posit Connect on the EC2 box;
  561-line server.R: profile / accuracy / RT / onset-contingent / RT-hist /
  age-hist plots; selectors for dataset, age range+bins, word, plotting
  window, analysis window, color-vs-facet; no tables or downloads).
  **URGENT: the Shiny app has been dead in browsers since ~2026-05-27 — the
  peekbank-connect.com TLS cert expired**, so the /shiny iframe renders
  blank. The viz replacement is fixing something currently broken.
  Site content wrinkles for migration: the codebook + a dataset-preview
  table live in embedded public Google Sheets; the contributors table is a
  stale (1/9/2024, 20-dataset) DT-widget HTML; the SQL docs page says port
  3306 while peekbank.json/README say 3307; docs carry an "outdated
  content" banner.

## Target architecture

- **Redivis org `datapages`** (same as wordbank/childes-db):
  - dataset **`peekbank`**: the 9 canonical tables; one Redivis version per
    legacy release (staged oldest→newest so tags map 2021.1→v1.0 …
    2026.1→v1.4); future releases append as new versions.
  - dataset **`peekbank_files`** (name TBD): Redivis file-index tables for
    everything now on OSF (raw_data, processed_data intermediates, stimuli,
    per-dataset READMEs), with a metadata index table (dataset_name, relpath,
    kind, size, checksum, file_id).
- **Site**: Quarto + OJS datapage (this repo) with lazy-loading in-browser
  visualizations replacing the Shiny app; docs content either folded in or
  kept in Astro (open decision below).
- **peekbankr**: `redivis` backend branch (characterization-tested against
  the live MySQL first), version map served via extended `peekbank.json`.
- **Import pipeline**: raw data pulled from Redivis files; processed
  intermediates pushed to Redivis; release = build parquet + push new Redivis
  version (no Django/MySQL). Later experiment: run the whole reprocess as a
  Redivis workflow.
- **Retire**: EC2 MariaDB + Django, shiny server (peekbank-connect.com), OSF
  storage (leave pointer), legacy Jekyll site (already superseded).

## Stages

### Stage 0 — Scaffolding & sign-off (now)
- Plan review with Mike; record decisions here.
- Secrets: Redivis org token for `datapages` (see Auth below).
- Repo skeleton: `redivis/` (staging pipeline), `site/` or root Quarto
  project, `peekbankr` work happens in its own repo on a `redivis` branch.

### Stage 1 — Stage all legacy releases to Redivis
- Export the 5 released schemas from the hosted MariaDB to parquet:
  keyset pagination on primary keys, explicit information_schema → arrow type
  map, resumable part files with `.done` markers; compact to large row
  groups. (~52M rows/version worst case — small vs childes-db.)
- Drop `aoi_timepoints_rle` / `aoi_timepoints_indexed` / `admin` /
  `django_migrations` (derived/bookkeeping); keep the 9 canonical tables
  verbatim (aux_data JSON strings untouched).
- Upload oldest→newest as one Redivis version each;
  `upload_merge_strategy="replace"` set via `tb$update()` on EVERY run;
  explicit empty-schema parquet for any zero-row table; two-phase release
  (stage draft → verify row counts vs export manifest → release on sign-off).
- Maintain release↔Redivis-tag map; publish in the extended `peekbank.json`
  (never break existing fields).
- Validate: row counts per table per version; spot-check derived numbers
  (e.g., recompute a shiny cached RDS and the paper's Table-2 accuracies).

### Stage 2 — Datapage site with Shiny-parity visualizations
- One end-to-end lazy viz first (profile plot, per-dataset slice), then the
  rest: accuracy, RT (landing + shift-start RT via the rle logic in
  `peekbank-shiny/helpers/rt_helper.R`), onset-contingent, age histogram,
  dataset browser landing table (paper Table 1 style: N, ages, method,
  language, citation).
- Slice design: per-dataset JSON/parquet slices built at render/CI time from
  Redivis. Key trick: ship the RLE representation (1.27M rows total for all
  44 datasets vs 35M expanded) and expand/RT-compute in the browser — the
  shiny RT code already operates on rle runs. Per-dataset slices should be
  ~10–100 KB gzipped.
- Cross-dataset item pages (word → developmental trajectory across datasets)
  from precomputed per-word × age-bin × t_norm aggregates.
- Plot/Table tabsets everywhere; match branding (raccoon, colors from the
  Astro site); loading spinners; static pages ported per site-architecture
  decision.
- CI: fetch small tables from Redivis (read-only token secret), rebuild
  slices from committed compact artifacts, publish gh-pages;
  `LIBARROW_BINARY=true`.

### Stage 3 — peekbankr Redivis backend
- FIRST capture characterization fixtures from the live MySQL package across
  the full argument matrix (all `get_*` × dataset_name/dataset_id/age ×
  supported versions) — while the legacy backend is alive.
- Then `redivis` branch: lean backend reproducing fixtures exactly; RLE
  decode stays (client-side expand from stored aoi_timepoints or from a
  compact transfer table — decide by benchmark); `unpack_aux_data` unchanged;
  OSF download helpers repointed to Redivis files (Stage 4).
- CRAN safety per playbook (graceful failure, NOT_CRAN vignette gating,
  \dontrun examples, redivis in Suggests + Additional_repositories,
  binary-bake mitigation).
- Version resolution via extended peekbank.json + hardcoded fallback.

### Stage 4 — OSF → Redivis file migration
- Mirror OSF node `pr6wu` locally (resumable, verified by size/count;
  public node, no auth needed for reads).
- Upload to Redivis file-index tables; index table with checksums.
- Repoint `peekbankr::download_stimuli` / `get_readmes`; leave a pointer
  README on OSF; coordinate with OSF sunset timeline.

### Stage 5 — data-import repo re-target
- Swap `helper_functions/osf.R` for Redivis file download/upload
  (peekbank_files dataset; `table$download_files()` filtered by name prefix).
- New release path: pipeline output → global-ID assignment + parquet build +
  Redivis version push (replaces Django/MySQL entirely; port the ID
  assignment + RLE build from the Django populate/promote commands with a
  characterization diff against 2026.1). Document the new release runbook.
  Keep the Docker option.
- Design note: today's dev schemas (peekbank_dev, workshop_2024_dev,
  grant_2024_dev) are the team's pre-release QA surface; their Redivis
  analog is the *unreleased draft next version* (visible to org members
  only). The release-build script should support "stage draft, don't
  release" for exactly this.
- Site refresh path: `scripts/build_slices.py` currently reads the local
  staging parquet; add a --from-redivis mode (download release tables,
  rebuild slices, commit) so future releases regenerate the datapage
  without the MySQL export step.
- Later experiment (not blocking): Redivis workflow that reruns the full
  import for a release in-cloud.

**Stage 5 findings (2026-08-11):**
- `build_release.py` verified engine-exact against released 2026.1 on every
  dataset whose OSF processed_data still matches the release (incl. the
  8.1M-row fernald_marchman_2012); remaining per-dataset diffs are
  **upstream drift** — OSF processed_data moved past the release: CDI
  dedup (adams_marchman), unified AOI computation (borovsky,
  byers-heinlein_2017; peekbankr 2026-08-05), t_norm resampling fix
  (nordmeyer; peekbankr 2026-06-03), aoi_region_sets added post-release
  (byers-heinlein_2017, casillas_tseltal).
- **Legacy pipeline mangles now baked into released data** (replicated for
  parity, candidates to FIX in the next release, with release-notes
  callouts): (a) pandas type inference in populate.py strips leading zeros
  from string ids (lab_subject_id "01" → "1"); (b) fractional eye-tracker
  gaze coordinates are silently int()-truncated (xy xsd/y declared
  IntegerField).
- **8 datasets have no processed_data on OSF at all** (bergelson_swingley,
  ferguson_eyetrackingr, fmw_2013, nih_babytoolbox_2025, ronfard_2021,
  sander-montant_2022, xsectional_2007, yoon_simpimp_2015) — the 2026.1
  release was built from a local pipeline run, so OSF was never the
  complete intermediate store. Regenerate via the pipeline to complete
  peekbank_files processed coverage.

### Stage 6 — Paper-based visualizations (after infra)
- eLife: age-binned recognition curves (Fig 1), accuracy/RT ~ log-age with
  per-dataset fits and longitudinal spaghetti (Figs 2–3), item trajectories.
- Methods paper: window-choice reliability heatmap explorer (precomputed ICC
  grids from `peekbank-method`), RT-definition explorer, trials-needed
  planner (Fig 7), animacy time courses (Fig 8).
- Infrastructure paper: dataset/item variability browser (Fig 4).

### Stage 7 — QA and cutover
- Preview repo with real URL for team QA; written issue-triage list;
  installable peekbankr branch for external testers.
- Cutover: peekbank.stanford.edu DNS (currently → Astro GH Pages? confirm),
  swap the Astro "Shiny" iframe/nav to the datapage, deprecation notices in
  peekbank.json, retire EC2 (DB + shiny + peekbank-connect.com), archive
  `peekbank` Django repo, CRAN release of new peekbankr.

## Decisions (Mike, 2026-08-11)

1. **Keep the Astro site** — the Quarto datapage is the viz layer beside it
   (replaces the dead Shiny iframe/nav link).
2. **Redivis layout**: `datapages.peekbank` + separate files dataset; stage
   releases oldest→newest; **KEEP `aoi_timepoints_rle`** (the package uses
   it for transfer efficiency; it's small) — drop only
   `aoi_timepoints_indexed` + Django bookkeeping. Skip dev schemas.
3. **Version resolution matches wordbankr**: each call gets the Redivis
   *latest* unless a version argument is given; peekbankr messages which
   source release that is (via a synthetic one-row `release_info` table
   staged into every version — no hardcoded maps). `current` = 2026.1.
4. Nothing else on the EC2 box — retire quickly after cutover.
5. OSF node stays up, deprecated; everything we use moves to Redivis.
6. Timeline as proposed; no hard external deadline.
7. Don't fix the broken Shiny cert — prioritize the datapage.
8. Website content cleanup in scope: build a proper contributors/datasets
   table and render the site table from it (replaces stale DT widget +
   Google-Sheet embeds).

## Superseded open questions (kept for the record)

1. **Site architecture**: (a) single Quarto datapage replaces the Astro site
   entirely (wordbank pattern), or (b) keep the new Astro docs/landing site
   and add the Quarto viz site alongside (swap the Shiny iframe/nav link).
   Recommendation: (b) — the Astro site is 6 months old and good; the
   datapage replaces the actual moving part (Shiny + DB).
2. **Redivis layout**: names `datapages.peekbank` + `datapages.peekbank_files`?
   Skip dev schemas? Drop RLE/indexed tables? Stage 2021.1 → 2026.1 in order?
3. **peekbank.json `current: 2022.1`** — stale? What should current be
   (2026.1?) and should we fix it now or only in the new config?
4. **EC2 box inventory**: what else runs on it (shiny server,
   peekbank-connect.com, anything for other projects)? Retirement plan.
5. **OSF endgame**: pointer-only node vs full takedown; any sunset deadline
   driving urgency?
6. **CDI convenience table**: also publish a derived per-administration CDI
   table (unpacked from aux_data) as a Redivis table for easy viz/analysis?
7. **Broken Shiny stopgap**: the app has been unreachable since May (expired
   TLS cert on peekbank-connect.com). Renew the cert as a stopgap, or accept
   the outage and prioritize the datapage viz (Stage 2)? (Renewal is a
   server-side action on the EC2/Posit Connect box — Mike/admin task.)
8. **Website content cleanup in scope?** Snapshot the Google-Sheet codebook
   + dataset-preview into version-controlled content, refresh the stale
   contributors table (20 datasets, dated 1/9/2024, vs 44 in 2026.1), fix
   the 3306/3307 port inconsistency — natural to fold into Stage 2.

## Related follow-ups (not blocking this migration)

- **Release childesr (redivis backend) to CRAN** — the childes-db migration's
  companion package (langcog/childesr branch `redivis`) still needs a CRAN
  submission plan: merge the branch, run the `cran-safe-release` checklist
  (graceful network failure, NOT_CRAN gating, \dontrun examples, redivis in
  Suggests + Additional_repositories via r-universe, CRAN-simulation CI job),
  bump version + NEWS, submit. peekbankr will follow the same path at
  cutover (Stage 7), so doing childesr first is a dry run.

## Auth / secrets needed

- **Redivis**: org-scoped API token for `datapages` with data-edit +
  `organization.read` (release endpoint needs it) — mint from the
  organization settings page, set as `REDIVIS_API_TOKEN` locally. Later: a
  separate read-only token as a GitHub Actions secret for site CI.
- **GitHub**: push access to `peekbank` org repos (gh CLI already works).
- **MySQL / OSF**: nothing — DB read creds are public; OSF node is public
  for reads (an OSF write token exists in the old data-import checkout if we
  ever need to write a pointer README).
- **Stanford DNS** for peekbank.stanford.edu at cutover (manual step, Mike).

## Known traps to respect (from the playbook)

Replace-strategy on every upload; zero-row tables need explicit empty
parquet; org token or 403 at release; version tags auto-assigned (keep a
map); verbatim storage of aux_data/NA semantics; validate derived numbers
against the shiny app's own cached outputs; characterization fixtures before
touching peekbankr; preview repo for QA; LIBARROW_BINARY in CI; the
redivis-r binary-bake trap for external QA users.
