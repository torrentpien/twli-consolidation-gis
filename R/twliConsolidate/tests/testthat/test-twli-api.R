context("liRef / liSum / liEqu / liShp (twli-style API)")

# These tests mirror the Python ones; they require an R environment with
# yaml, dplyr, sf and the project repo data files.

REPO <- normalizePath(file.path(dirname(rprojroot::find_root(rprojroot::has_file("DESCRIPTION"))), ".."))
CROSSWALK <- file.path(REPO, "crosswalk", "village_changes.yaml")

skip_if_no_data <- function() {
  if (!file.exists(CROSSWALK))
    testthat::skip("crosswalk YAML not present in this environment")
}

read_year <- function(roc) {
  p <- file.path(REPO, "data",
                 sprintf("%d年12月行政區人口統計_村里_SHP", roc),
                 sprintf("%d年12月行政區人口統計_村里.SHP", roc))
  g <- sf::st_read(p, options = "ENCODING=CP950", quiet = TRUE)
  g$AREA_M2 <- as.numeric(sf::st_area(g))
  g
}

test_that("liRef 2022 groups Lukang split (005/030/031)", {
  skip_if_no_data()
  ev <- twliConsolidate::load_crosswalk(CROSSWALK)
  ref <- twliConsolidate::liRef(ev, year_range = c(2021L, 2025L), data_year = 2022L)
  rocks <- ref[ref$v_id %in% c("10007020-005", "10007020-030", "10007020-031"), ]
  expect_equal(nrow(rocks), 3L)
  expect_equal(length(unique(rocks$group)), 1L)
  expect_equal(rocks$v_id[rocks$merge_code == 1L], "10007020-005")
})

test_that("liRef 2021 groups Da-liao merge (018/024)", {
  skip_if_no_data()
  ev <- twliConsolidate::load_crosswalk(CROSSWALK)
  ref <- twliConsolidate::liRef(ev, year_range = c(2021L, 2025L), data_year = 2021L)
  pair <- ref[ref$v_id %in% c("64000140-018", "64000140-024"), ]
  expect_equal(nrow(pair), 2L)
  expect_equal(pair$v_id[pair$merge_code == 1L], "64000140-018")
})

test_that("liSum aggregates population to keeper row", {
  skip_if_no_data()
  if (!requireNamespace("sf", quietly = TRUE)) testthat::skip("sf not installed")
  g <- read_year(111)
  df <- as.data.frame(sf::st_drop_geometry(g)[, c("V_ID", "P_CNT", "H_CNT")])
  ev <- twliConsolidate::load_crosswalk(CROSSWALK)
  ref <- twliConsolidate::liRef(ev, year_range = c(2021L, 2025L), data_year = 2022L)
  out <- twliConsolidate::liSum(df, ref, cols = c("P_CNT", "H_CNT"), finish = TRUE)
  raw <- df[df$V_ID %in% c("10007020-005", "10007020-030", "10007020-031"), ]
  keeper <- out[out$V_ID == "10007020-005", ]
  expect_equal(keeper$P_CNT, sum(raw$P_CNT))
  expect_equal(keeper$H_CNT, sum(raw$H_CNT))
  expect_true(!"10007020-030" %in% out$V_ID)
  expect_true(!"10007020-031" %in% out$V_ID)
  expect_equal(keeper$li_adjust, 1L)
})

test_that("liEqu recomputes density correctly after summing operands", {
  skip_if_no_data()
  if (!requireNamespace("sf", quietly = TRUE)) testthat::skip("sf not installed")
  g <- read_year(111)
  df <- as.data.frame(sf::st_drop_geometry(g)[, c("V_ID", "P_CNT")])
  df$AREA_M2 <- as.numeric(sf::st_area(g))
  ev <- twliConsolidate::load_crosswalk(CROSSWALK)
  ref <- twliConsolidate::liRef(ev, year_range = c(2021L, 2025L), data_year = 2022L)
  out <- twliConsolidate::liEqu(df, ref,
                                result = "DENSITY",
                                equ = "P_CNT / AREA_M2 * 1e6")
  raw <- df[df$V_ID %in% c("10007020-005", "10007020-030", "10007020-031"), ]
  expected <- sum(raw$P_CNT) / sum(raw$AREA_M2) * 1e6
  keeper <- out[out$V_ID == "10007020-005", ]
  expect_equal(keeper$DENSITY, expected, tolerance = 1e-6)
})
