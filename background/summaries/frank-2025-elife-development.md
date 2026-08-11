# Peekbank Analysis Paper (Frank et al., 2025/2026, eLife) — Structured Summary

**Source PDF:** `background/elife-109636-v1.pdf` (37 pp.)

## 1. Citation and role

**Frank, M. C., Marchman, V. A., Bergey, C. A., Boyce, V., Braginsky, M., Kachergis, G., Mankewitz, J., Meylan, S. C., Prystawski, B., Ram, N., Sparks, R. Z., Steffan, A., Tan, A. W. M., & Zettersten, M. (2025). Continuous developmental changes in word recognition and language learning across early childhood. *eLife*, 14:RP109636.** (Reviewed Preprint v1 Dec 2025; VOR July 2026.)

**Role: the DATA ANALYSIS paper** — substantive developmental analyses of Peekbank release **2026.1** via peekbankr. Reproducible code: github.com/peekbank/peekbank-development.

## 2. Goals

1. **Skill-learning signatures**: if language learning is skill learning, (a) accuracy ~ linear in **log(age)**; (b) **log(RT)** ~ linear in **log(age)** ("power law of practice"); (c) trial-to-trial **variability** decreases with age.
2. **Word recognition ↔ vocabulary**: factor structure of speed/accuracy/vocabulary (CDI); does early processing speed predict later vocabulary growth (Fernald & Marchman 2012 replication); "virtuous cycle" (speed improvements couple with vocabulary growth)?

## 3. Data and methods

- **26 datasets, 2,555 unique children, 4,124 administrations**, monolingual English, ages ~6–60 months (mean 25.4). Avg 14.88 accuracy trials, 5.51 RT trials per administration. 14 datasets have CDI; **5 longitudinal** (adams_marchman_2018, fernald_marchman_2012, fernald_totlot, fmw_2013, weaver_zettersten_2024).
- **"Standard" trial criteria (10)**: familiar target; target word first/only disambiguation, appears once; grammatical carrier; no informative prenominal language; no nonsense words; no language/speaker/accent switching; no background noise/filtering; familiar distractor; no novel visuals; single focal object.
- **Exclusions**: trials >50% missing dropped; RTs <367 ms removed; RTs need ≥50% valid samples in 200–2000 ms; participants need ≥4 accuracy + ≥2 RT measurements.
- **Measures**: accuracy = prop target/(target+distractor) in window (short 200–2000, long 200–4000 ms — long preferred); RT on distractor-initial trials = time to first target fixation (Fernald et al. 2008); variability = per-administration SDs; CDI production/comprehension.
- **Models**: lmer (`~ log_age_s + (log_age_s | dataset) + (1 | subject)`); CFA/FIML 3-factor (speed, accuracy, vocabulary; CFI .98, RMSEA .06); brms logistic vocab growth; lavaan longitudinal SEM (intercept+slope per construct; CFI .89).

## 4. Key findings

1. **Log RT decreases with log age** (β = −0.13 [−0.16, −0.11]); **accuracy increases with log age** (β = 0.07 [0.06, 0.08]) — consistent with power law of practice.
2. **Variability decreases with age**: SD log RT β = −0.05; SD accuracy β = −0.04.
3. **Three-factor structure** (age-partialled): speed↔accuracy −0.89; speed↔vocab −0.35; accuracy↔vocab 0.45.
4. **Initial RT predicts vocabulary growth** (replication at scale): t0 RT β = −0.14; shifts logistic growth midpoint (3.19 [1.97, 4.37]) not scale; robust to age-residualized RT.
5. **No "virtuous cycle"**: speed intercepts couple with vocab slopes (β = −0.18, p=.001), but speed *growth* does not couple with vocab *growth* (β = 0.00).
6. **Psychometrics**: test–retest ρ ≈ 0.41–0.50; log RT × long acc r = −0.46; production × long acc 0.51; RT distributions ex-Gaussian/log-normal; looking-RT validates against pointing-RT (r = .85, Creel 2024 reanalysis).

## 5. Figures — recreation specs

- **⭐ Fig 1 — Time course by age bin** (THE flagship interactive): x = −1000..4000 ms, y = prop target looking; one line per age bin (<12, 12–15, …, >36 mo), SEM ribbons, dashed 0.5, shaded short/long windows. Filters: ≥5 obs/participant, ≥50 participants per time×age bin. *Interactive: pick datasets, age binning, words; render live.*
- **⭐ Fig 2 — Accuracy & RT ~ age**: two panels, x = age (log scale), y = accuracy / RT (log); one point per administration; **longitudinal children connected by thin lines**; pooled fit + per-dataset fits (datasets spanning ≥6 mo). *Interactive: hover, toggle datasets, lin/log axes, window choice.*
- **⭐ Fig 3 — Variability ~ age**: same layout, y = SDs. Third tab of same interactive.
- **Fig 4 — Cross-sectional SEM path diagram** (static).
- **⭐ Fig 5 — Logistic vocab growth by initial RT**: predicted CDI production curves at t0 RT −1/0/+1 SD with credible ribbons + observed spaghetti. *Interactive: slider over t0 RT.*
- **Fig 6 — Longitudinal SEM path diagram** (static).
- **⭐ App 1 Fig 1 — Age distributions per dataset** (26 histograms) — dataset browser/coverage map + picker.
- App figs: retest intervals; RT validity scatter (r=.85); RT/accuracy distribution comparisons by age bin; scree plot; age-residualized growth curves.
- **Table 1** per-dataset N/admins/ages/trials/CDI/longitudinal flags — natural live database summary table. App 1 Table 1: per-dataset inclusion rates — data-quality dashboard.

## 6. Schema implications

- 40 Hz AOI series aligned to noun onset, −1000..+4000 ms, target/distractor/other/missing distinction (RT logic needs off-screen vs target shifts).
- Trial/stimulus metadata sufficient to identify "standard" trials (the 10 criteria).
- Administrations first-class with fractional age; subject_id constant across admins (longitudinal).
- CDI linkage: instrument type (WG/WS), production + comprehension, joinable to administrations.
- Derived measures recomputable: per-trial RT (with definitions/floors), windowed accuracies, missingness fraction, t=0 fixation location, per-admin SDs.

## 7. Limitations

Observational/exploratory; causal direction indeterminate; sparse longitudinal data (5 datasets); convenience samples; English-only; modest test–retest (0.41–0.50); no explicit choice response (mitigated by Creel reanalysis); CDI ceiling; MAR missingness.
