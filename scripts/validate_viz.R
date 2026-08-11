#!/usr/bin/env Rscript
# Independent reference for the datapage viz numbers, computed from the
# staged *expanded* aoi_timepoints parquet (bypassing the RLE slices
# entirely) with R's own cut(), qbeta(), and the actual shiny rt_helper.R.
# Compares against the Node output (scripts/validate_viz.mjs).

suppressMessages({
  library(arrow)
  library(dplyr)
  library(tidyr)
  library(purrr)
  library(tibble)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
ds_name <- if (length(args) >= 1) args[1] else "pomper_saffran_2016"
version <- "2026.1"
root <- normalizePath(file.path(dirname(sub("--file=", "", grep("--file=",
  commandArgs(), value = TRUE))), ".."))
staging <- file.path(root, "migration", "staging", version)

read_tbl <- function(name) {
  open_dataset(Sys.glob(file.path(staging, name, "part-*.parquet"))) %>%
    collect()
}

datasets <- read_tbl("datasets") %>% filter(dataset_name == ds_name)
admins <- read_tbl("administrations") %>%
  filter(dataset_id == datasets$dataset_id, !is.na(age), age >= 0, age <= 84)
tt <- read_tbl("trial_types") %>% filter(dataset_id == datasets$dataset_id)
trials <- read_tbl("trials") %>% filter(trial_type_id %in% tt$trial_type_id)
aoi <- open_dataset(Sys.glob(file.path(staging, "aoi_timepoints", "part-*.parquet"))) %>%
  filter(administration_id %in% admins$administration_id,
         trial_id %in% trials$trial_id) %>%
  select(administration_id, trial_id, t_norm, aoi) %>%
  collect()

# age bins exactly as R's cut(x, 2)
joined <- aoi %>%
  inner_join(admins %>% select(administration_id, age), by = "administration_id") %>%
  mutate(age_binned = cut(age, 2))

profile <- joined %>%
  filter(t_norm > -500, t_norm < 4000, aoi %in% c("target", "distractor")) %>%
  group_by(t_norm, age_binned) %>%
  summarise(n = n(), p = sum(aoi == "target"), .groups = "drop") %>%
  mutate(prop = p / n,
         ci_lower = qbeta(0.025, p + 0.5, n - p + 0.5),
         ci_upper = qbeta(0.975, p + 0.5, n - p + 0.5))

accuracy <- joined %>%
  filter(t_norm >= 250, t_norm <= 2250, aoi %in% c("target", "distractor")) %>%
  group_by(administration_id, trial_id, age_binned) %>%
  summarise(prop = mean(aoi == "target"), .groups = "drop") %>%
  group_by(age_binned) %>%
  summarise(n_trials = n(), mean = mean(prop),
            sem = sd(prop) / sqrt(n()), .groups = "drop")

# RT via the actual shiny helper
source(file.path(root, "repos", "peekbank-shiny", "helpers", "rt_helper.R"))
rt_data <- joined %>%
  group_by(administration_id, trial_id, age_binned) %>%
  filter(any(t_norm == 0), t_norm >= 0) %>%
  arrange(t_norm, .by_group = TRUE) %>%
  reframe(lengths = rle(aoi)$lengths, values = rle(aoi)$values) %>%
  group_by(administration_id, trial_id, age_binned) %>%
  nest() %>%
  mutate(data = lapply(data, get_rt)) %>%
  unnest(cols = c(data)) %>%
  ungroup()

rt_means <- rt_data %>%
  filter(shift_type == "D-T") %>%
  group_by(age_binned) %>%
  summarise(n = n(), mean_rt = mean(rt), .groups = "drop")

# ---- compare with the Node run ----
js <- fromJSON(file.path(root, "migration", "staging", "logs", "validate_js.json"))

cat("== bins ==\n")
cat("R:  ", levels(joined$age_binned), "\n")
cat("JS: ", js$binLabels, "\n")

r_prof <- profile %>%
  mutate(bin_idx = as.integer(age_binned)) %>%
  select(t = t_norm, bin_idx, n, p, prop, ci_lower, ci_upper)
js_prof <- as_tibble(js$profile) %>%
  mutate(bin_idx = match(bin, js$binLabels)) %>%
  select(t, bin_idx, n_js = n, p_js = p, prop_js = prop,
         ci_lower_js = ci_lower, ci_upper_js = ci_upper)
cmp <- inner_join(r_prof, js_prof, by = c("t", "bin_idx"))
cat(sprintf("\n== profile: %d R points, %d JS points, %d joined ==\n",
            nrow(r_prof), nrow(js_prof), nrow(cmp)))
cat(sprintf("count mismatches (n or p): %d\n",
            sum(cmp$n != cmp$n_js | cmp$p != cmp$p_js)))
cat(sprintf("max |prop diff|: %.2e   max |CI diff|: %.2e\n",
            max(abs(cmp$prop - cmp$prop_js)),
            max(abs(c(cmp$ci_lower - cmp$ci_lower_js,
                      cmp$ci_upper - cmp$ci_upper_js)))))

js_acc <- as_tibble(js$accuracy) %>% mutate(bin_idx = match(bin, js$binLabels))
r_acc <- accuracy %>% mutate(bin_idx = as.integer(age_binned))
acc_cmp <- inner_join(r_acc, js_acc, by = "bin_idx", suffix = c("", "_js"))
cat(sprintf("\n== accuracy ==\ntrial-count match: %s | max |mean diff|: %.2e | max |sem diff|: %.2e\n",
            all(acc_cmp$n_trials == acc_cmp$n_trials_js),
            max(abs(acc_cmp$mean - acc_cmp$mean_js)),
            max(abs(acc_cmp$sem - acc_cmp$sem_js))))

js_rt <- as_tibble(js$rtMeans) %>% mutate(bin_idx = match(bin, js$binLabels))
r_rt <- rt_means %>% mutate(bin_idx = as.integer(age_binned))
rt_cmp <- inner_join(r_rt, js_rt, by = "bin_idx", suffix = c("", "_js"))
cat(sprintf("\n== RT (D-T) ==\nR n: %s | JS n: %s | max |mean RT diff|: %.2e ms\n",
            paste(rt_cmp$n, collapse = ","), paste(rt_cmp$n_js, collapse = ","),
            max(abs(rt_cmp$mean_rt - rt_cmp$mean_rt_js))))

if (all(cmp$n == cmp$n_js & cmp$p == cmp$p_js) &&
    max(abs(cmp$prop - cmp$prop_js)) < 1e-9 &&
    max(abs(c(cmp$ci_lower - cmp$ci_lower_js,
              cmp$ci_upper - cmp$ci_upper_js))) < 1e-6 &&
    nrow(cmp) == nrow(r_prof) && nrow(cmp) == nrow(js_prof) &&
    all(rt_cmp$n == rt_cmp$n_js) &&
    max(abs(rt_cmp$mean_rt - rt_cmp$mean_rt_js)) < 1e-9) {
  cat("\nVALIDATION PASSED\n")
} else {
  cat("\nVALIDATION FAILED\n")
  quit(status = 1)
}
