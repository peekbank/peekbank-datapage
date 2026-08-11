# Peekbank Methods Paper (Boyce et al., 2026 preprint) — Structured Summary

**Source PDF:** `background/peekbank-method-preprint-supplement.pdf` (42 pp. — main text pp. 1–21, references, then SI pp. 28–42 with Figures S1–S21).

## 1. Citation and role

**Boyce, V., Marchman, V. A., Baumgartner, H., Bergey, C. A., Braginsky, M., Giovannetti, F., Kachergis, G., Mankewitz, J., Meylan, S., Prystawski, B., Sparks, R. Z., Steffan, A., Tan, A. W. M., Frank, M. C., & Zettersten, M. (2026). Data-driven recommendations for increasing reliability and validity in measures of infant word recognition.** Preprint; based on Peekbank 2026.1. Code: github.com/peekbank/peekbank-method

**Role: the METHODOLOGICAL-INSIGHTS paper** — reliability/validity/design recommendations for the LWL paradigm.

## 2. Questions

1. Which accuracy-window start/end maximize signal? 2. Baseline-correct accuracy? 3. RT: launch vs landing, min/max cutoffs, log transform? 4. When to exclude trials/participants? 5. How many trials needed? 6. Target–distractor pairing effects (animacy)?

## 3. Data and methods

- Peekbank 2026.1: 44 datasets, 134,929 trials, 3,915 children (6 mo–5 yr), 5,596 sessions. **"Standard" trials analyzed: 75,636 trials, 3,171 children, 4,851 sessions, 36 datasets.** Mostly English (2,617) + Spanish (154), Eng+Fr (200), Norwegian (69), Dutch (54), Eng+Spa (54), Tseltal (23).
- **Reliability**: inter-item ICC (items as raters; mean-rating consistency two-way random; R `agreement` pkg); test–retest (5 datasets, 365 children, 788 session pairs, within a month).
- **Validity**: correlations with MB-CDI comprehension (632 children, 12 datasets) and production (1,143 children, 20 datasets), scores as proportion-of-items.
- **Aggregation**: lmer with random dataset intercepts, weighted by sessions; rerun by age bins <18, 18–23, 24–35, ≥36 mo.
- Full parameter sweeps: window start (−500..1000) × end (1500..4000); launch/landing × min (0..1000) × max (1600..4000) × raw/log; baseline windows; exclusion grids; subsampling simulations for trial counts.

## 4. Recommendations (with effect sizes)

1. **Long accuracy window (start ~400–600 ms, end 3000–4000 ms)**: 300–1800 → 600–4000 gives ICC +0.12 [0.08, 0.16], test–retest +0.07; validity unchanged. Peak-of-curve window selection *lowers* reliability — late-trial looking carries reliable individual-difference signal.
2. **Do NOT baseline-correct accuracy**: every baseline tested hurts (ICC −≥0.10, test–retest −≥0.19). Difference-score psychometrics.
3. **Landing RTs, ~400 ms minimum, high maximum (~4000 ms)**: vs raw launch 300–1800: ICC +0.11. Contradicts the Fernald et al. (2008) launch convention. Log transform optional/theory-dependent.
4. **Trial/session exclusions for low data are generally unnecessary**: ≥50% looking retains 85.6% of trials, ICC +0.03; session minima ≈ no change. No/minimal exclusion is psychometrically reasonable.
5. **Design for ≥10 target trials/child/condition**; accuracy test–retest keeps rising to 20 trials; only ~1/3 of trials yield a valid RT — ≥5 RT trials helps.
6. **Match target and distractor on animacy**: animate-target/inanimate-distractor inflates, inanimate-target/animate-distractor depresses (can look like chance under 18 mo); visible to age 3.

**Cumulative ("Norm vs Rex")**: recommended pipeline (600–4000, no baseline, no exclusions) vs defensible-but-unfortunate (300–1800, baseline, exclusions): **ICC +0.20 [0.13, 0.27], test–retest +0.21 [0.13, 0.29]**, validity +0.07.

**Order effects (SI §7)**: none reliable (~1% max).

## 5. Figures — recreation specs

- **⭐ Fig 1 — Accuracy-window ICC heat map**: x = window start, y = window end, fill = mean ICC (~0.15–0.48); black rect = best region, blue = literature standard. *Interactive gold: brush a window, see ICC update (precompute the grid).*
- **Fig 2** — per-dataset dumbbells short vs long window (ICC/retest/CDI-r); **Fig 3** — same by age bin. *Generalizable "compare two analysis specs" widget.*
- **Fig 4** — baseline-correction dumbbells.
- **⭐ Fig 5 — RT-parameter ICC heat maps** (landing | launch; x = min, y = max). *Interactive: pick definition + slider cutoffs (+ raw/log).*
- **Fig 6** — RT-spec dumbbells.
- **⭐ Fig 7 — Trial-count subsampling curves**: 2 rows (accuracy, RT) × 3 cols (retest, CDI comp, CDI prod); x = # subsampled trials; color = min-trials filter. *"How many trials do I need?" planner.*
- **⭐⭐ Fig 8 — Animacy time-course profiles**: prop target vs time by 4 animacy pairings (A/I, I/I, A/A, I/A), overall + by age bin. *Best live-database interactive (needs stimulus animacy coding).*
- **Fig 9** — recommended vs alternative pipeline dumbbells. ⭐ if generalized to user-composed pipelines.
- SI: age histograms (S1); per-dataset data-availability stacked areas (S2 ⭐ coverage viewer); age-faceted heatmaps (S3, S9); forest-plot sweeps (S4–S20); order effects (S21).

## 6. Implications for database/API derived measures

- **Windowed accuracy as parameterized derived measure** (user start/end; default long window), NOT hard-coded 300–1800.
- **Both RT definitions per trial** (launch + landing), configurable min/max, raw + log, valid-RT flag.
- **No baked-in exclusions**; ship metadata for user-side filtering: per-trial fraction on-screen looking, t=0 fixation location, per-session trial/RT counts, pre- vs post-exclusion contribution status.
- **"Standard/vanilla" trial flags** (SI §2.1 criteria) + **stimulus animacy coding** for target and distractor.
- AOI series spanning −2000..4000 ms where available; CDI scores normalized; session pairs for retest datasets.
- Precomputed ICC grids (Figs 1, 5) served for interactive use.

## 7. Limitations

Convenience sample (English/US-heavy, similarly trained labs); standard-trials restriction limits scope to familiar word recognition; graded not definitive improvements; scarce test–retest data; some datasets contributed post-exclusion; reliability gains > validity gains; CDI is related-but-distinct with own error.
