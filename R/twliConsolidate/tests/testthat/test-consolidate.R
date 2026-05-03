context("consolidate_panel")

# These tests mirror the Python end-to-end tests; they need an R environment
# with `yaml`, `dplyr`, `tidyr`, `rlang` and `sf` installed.
# The data files referenced are expected at the repository root:
#   crosswalk/village_changes.yaml
#   data/<roc>年12月行政區人口統計_村里_SHP/...

REPO <- normalizePath(file.path(dirname(rprojroot::find_root(rprojroot::has_file("DESCRIPTION"))), ".."))
CROSSWALK <- file.path(REPO, "crosswalk", "village_changes.yaml")

skip_if_no_data <- function() {
  if (!file.exists(CROSSWALK))
    testthat::skip("crosswalk YAML not present in this environment")
}

build_panel <- function() {
  rocs <- 110:114
  rows <- list()
  for (roc in rocs) {
    p <- file.path(REPO, "data",
                   sprintf("%d年12月行政區人口統計_村里_SHP", roc),
                   sprintf("%d年12月行政區人口統計_村里.SHP", roc))
    g <- sf::st_read(p, options = "ENCODING=CP950", quiet = TRUE)
    g$AREA_M2 <- as.numeric(sf::st_area(g))
    df <- as.data.frame(sf::st_drop_geometry(g)[, c("V_ID", "COUNTY", "TOWN",
                                                    "VILLAGE", "P_CNT", "H_CNT")])
    df$year <- 1911L + roc
    df$AREA_M2 <- as.numeric(sf::st_area(g))
    rows[[as.character(roc)]] <- df
  }
  do.call(rbind, rows)
}

test_that("load_crosswalk returns events", {
  skip_if_no_data()
  ev <- twliConsolidate::load_crosswalk(CROSSWALK)
  expect_true(length(ev) > 0)
  expect_true(all(vapply(ev, function(e) e$type, character(1)) %in%
                  c("rename", "merge", "split", "redistribute", "boundary_adjust")))
})

test_that("Lukang split groups 005/030/031 into one SAU", {
  skip_if_no_data()
  ev <- twliConsolidate::load_crosswalk(CROSSWALK)
  lin <- twliConsolidate::build_lineage(ev, year_range = c(2021L, 2025L))
  sau <- twliConsolidate::sau_of(lin, "10007020-005")
  members <- twliConsolidate::sau_members(lin, sau)
  expect_true(all(c("10007020-005", "10007020-030", "10007020-031") %in% members))
})

test_that("Da-liao merge groups 018/024 into one SAU", {
  skip_if_no_data()
  ev <- twliConsolidate::load_crosswalk(CROSSWALK)
  lin <- twliConsolidate::build_lineage(ev, year_range = c(2021L, 2025L))
  expect_equal(twliConsolidate::sau_of(lin, "64000140-018"),
               twliConsolidate::sau_of(lin, "64000140-024"))
})

test_that("Total population invariant after consolidation", {
  skip_if_no_data()
  if (!requireNamespace("sf", quietly = TRUE)) testthat::skip("sf not installed")
  panel <- build_panel()
  ev <- twliConsolidate::load_crosswalk(CROSSWALK)
  lin <- twliConsolidate::build_lineage(ev, year_range = c(2021L, 2025L))
  out <- twliConsolidate::consolidate_panel(
    panel,
    vid_col = "V_ID", year_col = "year",
    vars_spec = list(P_CNT = "sum"),
    lineage = lin
  )
  raw_total <- tapply(panel$P_CNT, panel$year, sum, na.rm = TRUE)
  out_total <- tapply(out$P_CNT,   out$year,   sum, na.rm = TRUE)
  expect_equal(unname(raw_total), unname(out_total))
})

test_that("Year range outside V_ID-change events leaves SAUs equal to V_IDs", {
  skip_if_no_data()
  ev <- twliConsolidate::load_crosswalk(CROSSWALK)
  lin <- twliConsolidate::build_lineage(ev, year_range = c(2023L, 2025L))
  expect_equal(twliConsolidate::sau_of(lin, "10007020-030"),
               "SAU_10007020-030")
})
