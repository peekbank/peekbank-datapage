#!/usr/bin/env Rscript
# Characterization-fixture capture for the peekbankr Redivis migration.
# Runs the CURRENT peekbankr (repos/peekbankr checkout) against the LIVE
# hosted MySQL across the supported argument matrix, saving every result as
# an RDS fixture plus a manifest of dims/hashes. The future Redivis backend
# must reproduce these exactly (modulo documented row-order differences —
# the comparison harness sorts by primary key).
#
# Output: migration/fixtures/<version>/<name>.rds + manifest.json

suppressMessages({
  library(dplyr)
  library(jsonlite)
  library(digest)
})

root <- normalizePath(file.path(dirname(sub("--file=", "", grep("--file=",
  commandArgs(), value = TRUE))), ".."))
pkgload::load_all(file.path(root, "repos", "peekbankr"), quiet = TRUE)

fix_root <- file.path(root, "migration", "fixtures")
dir.create(fix_root, showWarnings = FALSE, recursive = TRUE)

VERSIONS <- c("2021.1", "2025.1", "2026.1")

# canonicalize for hashing: plain data.frame, sorted by first column (PK),
# columns in name order — row order from MySQL is not part of the contract
canon <- function(df) {
  df <- as.data.frame(df)
  if (nrow(df) > 0) df <- df[do.call(order, df[, 1, drop = FALSE]), , drop = FALSE]
  rownames(df) <- NULL
  df
}

manifest <- list()

capture <- function(version, name, expr) {
  t0 <- Sys.time()
  # fresh connection per capture: get_aoi_timepoints() disconnects any
  # connection it is handed (current-peekbankr bug), so sharing one poisons
  # every subsequent call
  con <- connect_to_peekbank(db_version = version)
  on.exit(try(DBI::dbDisconnect(con), silent = TRUE), add = TRUE)
  result <- tryCatch(
    eval(substitute(expr), list(con = con), parent.frame()),
    error = function(e) e)
  dir.create(file.path(fix_root, version), showWarnings = FALSE)
  path <- file.path(fix_root, version, paste0(name, ".rds"))
  if (inherits(result, "error")) {
    entry <- list(name = name, version = version, error = conditionMessage(result))
    message(sprintf("[%s] %s: ERROR %s", version, name, entry$error))
  } else {
    saveRDS(result, path, compress = "xz")
    cc <- canon(result)
    entry <- list(
      name = name, version = version,
      nrow = nrow(result), ncol = ncol(result),
      cols = paste(sort(names(result)), collapse = ","),
      hash = digest(cc, algo = "md5"),
      secs = round(as.numeric(Sys.time() - t0, units = "secs"), 1))
    message(sprintf("[%s] %s: %d x %d (%.1fs)", version, name,
                    nrow(result), ncol(result), entry$secs))
  }
  manifest[[paste(version, name, sep = "/")]] <<- entry
}

for (v in VERSIONS) {
  capture(v, "datasets", get_datasets(connection = con) %>% collect())
  capture(v, "subjects", get_subjects(connection = con) %>% collect())
  capture(v, "administrations", get_administrations(connection = con) %>% collect())
  capture(v, "administrations_age",
          get_administrations(age = c(18, 24), connection = con) %>% collect())
  capture(v, "administrations_ds",
          get_administrations(dataset_name = "pomper_saffran_2016",
                              connection = con) %>% collect())
  capture(v, "trials", get_trials(connection = con) %>% collect())
  capture(v, "trials_ds",
          get_trials(dataset_name = "pomper_saffran_2016",
                     connection = con) %>% collect())
  capture(v, "trial_types", get_trial_types(connection = con) %>% collect())
  capture(v, "trial_types_ds",
          get_trial_types(dataset_name = "pomper_saffran_2016",
                          connection = con) %>% collect())
  capture(v, "stimuli", get_stimuli(connection = con) %>% collect())
  capture(v, "stimuli_ds",
          get_stimuli(dataset_name = "pomper_saffran_2016",
                      connection = con) %>% collect())
  capture(v, "aoi_region_sets", get_aoi_region_sets(connection = con) %>% collect())
  capture(v, "aoi_timepoints_ps_rle",
          get_aoi_timepoints(dataset_name = "pomper_saffran_2016",
                             connection = con))
  capture(v, "aoi_timepoints_ps_norle",
          get_aoi_timepoints(dataset_name = "pomper_saffran_2016", rle = FALSE,
                             connection = con) %>% collect())
  capture(v, "aoi_timepoints_ps_age",
          get_aoi_timepoints(dataset_name = "pomper_saffran_2016",
                             age = c(41, 44), connection = con))
  capture(v, "aoi_timepoints_sa",
          get_aoi_timepoints(dataset_name = "swingley_aslin_2002",
                             connection = con))
  capture(v, "xy_timepoints_rv4",
          get_xy_timepoints(dataset_name = "reflook_v4",
                            connection = con) %>% collect())
  capture(v, "sql_query",
          get_sql_query("SELECT dataset_id, dataset_name FROM datasets",
                        connection = con))
  capture(v, "list_tables",
          data.frame(table = sort(list_peekbank_tables(con))))

}

# aux-data unpacking on the newest version (CDI etc.)
capture("2026.1", "subjects_aux_unpacked",
        get_subjects(connection = con) %>% collect() %>% unpack_aux_data())

write_json(manifest, file.path(fix_root, "manifest.json"),
           auto_unbox = TRUE, pretty = TRUE)
message("fixture capture complete: ", length(manifest), " entries")
