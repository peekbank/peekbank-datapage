# Peekbank Infrastructure Paper (Zettersten et al., 2023) — Structured Summary

**Source PDF:** `background/nihms-1832419.pdf` (HHS/NIHMS author manuscript, 28 pp.)

## 1. Citation and role

**Zettersten, M., Yurovsky, D., Xu, T. L., Uner, S., Tsui, A. S. M., Schneider, R. M., Saleh, A. N., Meylan, S. C., Marchman, V. A., Mankewitz, J., MacDonald, K., Long, B., Lewis, M., Kachergis, G., Handa, K., deMayo, B., Carstensen, A., Braginsky, M., Boyce, V., Bhatt, N. S., Bergey, C. A., & Frank, M. C. (2023). Peekbank: An open, large-scale repository for developmental eye-tracking data of children's word recognition. *Behavior Research Methods*, 55(5), 2485–2500. doi:10.3758/s13428-022-01906-4**

- **Role: the INFRASTRUCTURE paper** — introduces the database, schema, ETL tooling, versioning model, `peekbankr` API, and Shiny app, with two brief demonstration analyses. Its schema description is the migration spec.
- Open practices: paper code at github.com/langcog/peekbank-paper; raw + standardized data at OSF (osf.io/pr6wu); API at github.com/langcog/peekbankr.

## 2. Goals

- Word recognition measured with the **looking-while-listening (LWL) paradigm**: child sees two images (target + distractor), hears a sentence ("Look at the dog!"), speed/accuracy of fixating the target after label onset indexes recognition.
- Individual LWL studies are small and idiosyncratic; mapping developmental trajectories of recognition speed/accuracy and item-level development requires aggregation.
- Three aims: (a) collect a large set of LWL datasets; (b) define a **standardized data format and processing tools** (analogized to BIDS); (c) provide an **access interface** (`peekbankr`, Shiny app).
- Secondary: replicability, data-driven design decisions (power/reliability simulations), open pipelines, pedagogy, comparing exclusion criteria.

## 3. Database design (migration spec)

### Architecture (Fig. 1) — four components

1. **Convert**: dataset-specific import scripts (`peekbank-data-import`) + the **`peekds` R package** (unified format; validator checks all tables for required fields/types).
2. **Store**: the **`peekbank` Django app** creates the relational schema, applies checks, populates **MySQL**.
3. **Retrieve**: **`peekbankr`** R package.
4. **Visualize**: **`peekbank-shiny`** (peekbank-shiny.com).

### Schema — 9 tables (Figs. 1–2)

**Metadata tables:**
- **`datasets`** — one row ≈ one study: lab, citations.
- **`subjects`** — invariant per-person info (native language, sex); de-identified (US Safe Harbor); one subject → multiple administrations (longitudinal support).
- **`administrations`** — one session: age (`lab_age`, `lab_age_units` as coded + standardized `age` in months), coding method (eye-tracking vs manual), monitor properties.
- **`stimuli`** — each row a **(word, image) pair**; handles synonyms, multiple languages, distractor-only images; `stimulus_novelty` (familiar vs novel pseudo-word).
- **`trial_types`** — a trial in the experimental design: target/distractor stimulus + location, **point of disambiguation**, condition, language; FKs to stimuli (target_id, distractor_id), aoi_region_sets.
- **`aoi_region_sets`** — AOI (x,y) coordinate regions for eye-tracking datasets.
- **`trials`** — a specific instance of a trial type for a participant; carries **trial order**; links time-course records to trial types.

**Time-course tables:**
- **`xy_timepoints`** — raw gaze coordinates (eye-tracker datasets only).
- **`aoi_timepoints`** — looks recoded into **{target, distractor, other, missing}** via `peekds::add_aois()`. Manually coded datasets have only aoi_timepoints.

### Time normalization and resampling

- Time re-centered so **t = 0 at target-word onset** in every trial (`rezero_times()`, `normalize_times()`).
- **All data resampled to 40 Hz (25-ms bins)** via `resample_times()` — compromise between densest (500 Hz) and sparsest (30 Hz) sources. Interpolation is **constant (last-observation-carried), not linear** — introduces no look locations absent from the original data.

### Import/ETL workflow

1. Custom per-dataset import script (from templates for manual/eye-tracker datasets).
2. `peekds` validation.
3. **Visual check**: recreate the original paper's time-course plot.
4. Django applies further checks, loads MySQL.

### Versioning model

- Named releases: **year.version (e.g., 2022.1)**; peekbankr can target any previous version; each version downloadable as compressed .sql dump.
- **Inclusive-import policy**: ALL provided data archived, *including participants excluded in original papers* — users apply their own exclusions. Minor numerical discrepancies vs original publications are expected; exact reproduction is a non-goal.

### peekbankr API

`connect_to_peekbank()` (compression option), `get_datasets()`, `get_subjects()`, `get_administrations()`, `get_stimuli()`, `get_trial_types()`, `get_trials()`, `get_aoi_region_sets()`, `get_xy_timepoints()`, `get_aoi_timepoints()` (**run-length-encoded transfer by default**, decompressed client-side).

### Web tools

- Shiny app: four viz types — (1) time-course **profile plot**; (2) **overall accuracy** in a user-set window; (3) **reaction time** (latency to shift distractor→target on distractor-initial trials); (4) **onset-contingent plot**. Controls: dataset multi-select, age range, # age bins, plotting window, analysis window, age-as-color vs facet.
- OSF (osf.io/pr6wu): raw time-series + metadata + original stimuli (image/audio) where available.

## 4. Data content at publication (2022.1 era)

- **20 LWL datasets, N = 1,594, ages 9–70 months**; 47.3% F / 50.4% M / 2.3% unreported.
- 14/20 monolingual English; Spanish (hurtado_2008, xsectional_2007, weisleder_stl), Tseltal (casillas_tseltal_2015), English/French (byers-heinlein_2017), Spanish/English (potter_remix).
- 12 manual coding / 8 automatic eye-tracking. All test familiar items; 5 also novel pseudo-words.

**Table 1 roster** (dataset | N | mean age | range | method | language): adams_marchman_2018 69/17.1/13–20/manual/Eng • byers-heinlein_2017 48/20.1/19–21/ET/Eng+Fr • casillas_tseltal_2015 23/31.3/9–48/manual/Tseltal • fmw_2013 80/20.0/17–26/manual/Eng • frank_tablet_2016 69/35.5/12–60/ET/Eng • garrison_bergelson_2020 35/14.5/12–18/ET/Eng • xsectional_2007 49/23.8/15–37/manual/Spa • hurtado_2008 76/21.0/17–27/manual/Spa • mahr_coartic 29/20.8/18–24/ET/Eng • perry_cowpig 45/20.5/19–22/manual/Eng • pomper_saffran_2016 60/44.3/41–47/manual/Eng • pomper_salientme 44/40.1/38–43/manual/Eng • potter_canine 36/23.8/21–27/manual/Eng • potter_remix 44/22.6/18–29/manual/Spa+Eng • ronfard_2021 40/20.0/18–24/manual/Eng • swingley_aslin_2002 50/15.1/14–16/manual/Eng • weisleder_stl 29/21.6/18–27/manual/Spa • attword_processed 288/25.5/13–59/ET/Eng • reflook_socword 435/33.6/12–70/ET/Eng • reflook_v4 45/34.2/11–60/ET/Eng

## 5. Key findings / demonstration analyses

1. Every dataset shows above-chance target looking in the 367–2000 ms window. **Familiar words: M = 0.66, 95% CI [0.65, 0.67], n = 1,543; novel words: M = 0.59 [0.58, 0.61], n = 822.** Per-dataset accuracies range 0.55–0.77; unique target labels 6–87 per dataset.
2. **Item variability (Fig. 4)**: all 20 datasets rise above chance after onset; item counts and item-level accuracy vary widely.
3. **Swingley & Aslin (2002) reanalysis (Fig. 5)**: ~10 lines of peekbankr code reproduce the classic mispronunciation effect (correct pronunciations = faster + more accurate looking).
4. **Item-level development (Fig. 6)**: for apple, book, dog, frog (>100 children/word), target looking increases with age (bins 12–24, 24–36, 36–48 mo). Caveat: naïve averaging confounds study-level design.

## 6. Figures — recreation specs

- **Fig. 1** flowchart: raw datasets → import scripts → peekds → common format → Django → MySQL → peekbankr → shiny. *Redraw with Redivis replacing MySQL/Django.*
- **Fig. 2** ER diagram: 9 tables grouped metadata vs time series, FK arrows. *Could be a clickable schema explorer.*
- **Fig. 3** Shiny app screenshot ⭐ — the blueprint for the Observable rebuild (profile/accuracy/RT/onset explorer).
- **Fig. 4** ⭐ 20 facets (one per dataset), thin colored lines = per-item time courses, thick black GAM smooth; x −500..3000 ms, y prop target 0–1, dashed 0.5. *Compelling interactive: hover to identify words, click through datasets.*
- **Fig. 5** ⭐ Swingley-Aslin correct vs mispronounced curves with 95% CI every 25 ms. *"Replicate a classic study" demo; generalizable to a condition-comparison widget.*
- **Fig. 6** ⭐ 4 word facets × 3 age-bin lines with CIs. *Prime interactive: pick ANY word with sufficient data, see developmental trajectory; compute eligibility dynamically.*
- **Table 1** ⭐ dataset browser (citation, name, N, ages, method, language) — natural landing table.
- **Table 2** per-dataset accuracy (367–2000 ms window) — merge into interactive Table 1 with live-computed accuracy.

## 7. Limitations, plans, governance

- 20 datasets; design idiosyncrasies confound naïve aggregation; mixed-effects modeling "a critical next step"; WEIRD/monolingual-English homogeneity.
- Plans: grow datasets/languages; model-based analyses; generalize beyond word recognition.
- Contribution: open invitation; import templates; team does most imports. Privacy: Safe Harbor de-identification; GDPR note for EU labs.
