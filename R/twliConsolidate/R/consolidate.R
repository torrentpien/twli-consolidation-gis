.SUPPORTED_AGGS <- c("sum", "mean", "first", "last", "min", "max",
                     "weighted_mean", "recompute")

#' Aggregate a panel dataset to Stable Analysis Units (SAU).
#'
#' Mirrors the algorithm of the Python ``twli_consolidate.consolidate_panel``.
#'
#' @param df A long-format panel data.frame with one row per (V_ID, year).
#' @param vid_col Name of the village-code column.
#' @param year_col Name of the year column.
#' @param vars_spec Named list of per-variable aggregation rules. Each value
#'   may be a single character (``"sum"``, ``"mean"``, etc.) or a list with
#'   element ``agg`` and (for ``weighted_mean``) ``weight`` or
#'   (for ``recompute``) ``expr``.
#' @param lineage A ``twliLineage`` object from [build_lineage()].
#' @param extra_group_cols Optional character vector of extra columns to keep
#'   (first value within each SAU).
#' @param keep_member_list Logical; if TRUE, append a ``members`` column with
#'   the original V_IDs aggregated for each (SAU, year) row.
#' @return A data.frame with columns
#'   ``sau_id, <year_col>, <extra cols>, <vars>, members?``.
#' @export
consolidate_panel <- function(df,
                              vid_col,
                              year_col,
                              vars_spec,
                              lineage,
                              extra_group_cols = NULL,
                              keep_member_list = TRUE) {
  if (!vid_col %in% names(df))  stop(sprintf("vid_col '%s' not in dataframe", vid_col))
  if (!year_col %in% names(df)) stop(sprintf("year_col '%s' not in dataframe", year_col))
  spec <- .normalize_spec(vars_spec)
  .validate_columns(df, spec)

  work <- df
  work$`__sau__` <- sau_of(lineage, work[[vid_col]])

  # Phase 1: per-row pre-multiplication for weighted_mean
  aux <- list()
  for (col in names(spec)) {
    rule <- spec[[col]]
    if (rule$agg == "weighted_mean") {
      num <- paste0("__num__", col)
      den <- paste0("__den__", col)
      work[[num]] <- work[[col]] * work[[rule$weight]]
      work[[den]] <- work[[rule$weight]]
      aux[[col]] <- list(num = num, den = den)
    }
  }

  # Phase 2: group + summarise
  group_keys <- c("__sau__", year_col)
  agg_exprs <- list()
  for (col in names(spec)) {
    a <- spec[[col]]$agg
    if (a == "sum")          agg_exprs[[col]] <- rlang::expr(sum(!!rlang::sym(col), na.rm = TRUE))
    else if (a == "mean")    agg_exprs[[col]] <- rlang::expr(mean(!!rlang::sym(col), na.rm = TRUE))
    else if (a == "first")   agg_exprs[[col]] <- rlang::expr(dplyr::first(!!rlang::sym(col)))
    else if (a == "last")    agg_exprs[[col]] <- rlang::expr(dplyr::last(!!rlang::sym(col)))
    else if (a == "min")     agg_exprs[[col]] <- rlang::expr(min(!!rlang::sym(col), na.rm = TRUE))
    else if (a == "max")     agg_exprs[[col]] <- rlang::expr(max(!!rlang::sym(col), na.rm = TRUE))
    else if (a == "weighted_mean") {
      num <- aux[[col]]$num; den <- aux[[col]]$den
      agg_exprs[[num]] <- rlang::expr(sum(!!rlang::sym(num), na.rm = TRUE))
      agg_exprs[[den]] <- rlang::expr(sum(!!rlang::sym(den), na.rm = TRUE))
    }
    # recompute: handled in phase 3
  }
  if (length(extra_group_cols)) {
    for (c in extra_group_cols) {
      if (c %in% names(df) && !c %in% names(agg_exprs)) {
        agg_exprs[[c]] <- rlang::expr(dplyr::first(!!rlang::sym(c)))
      }
    }
  }

  grouped <- work %>%
    dplyr::group_by(dplyr::across(dplyr::all_of(group_keys))) %>%
    dplyr::summarise(!!!agg_exprs, .groups = "drop")

  # Phase 3: finalise weighted_mean and recompute
  for (col in names(spec)) {
    rule <- spec[[col]]
    if (rule$agg == "weighted_mean") {
      num <- aux[[col]]$num; den <- aux[[col]]$den
      grouped[[col]] <- ifelse(grouped[[den]] == 0, NA_real_,
                               grouped[[num]] / grouped[[den]])
      grouped[[num]] <- NULL; grouped[[den]] <- NULL
    }
  }
  for (col in names(spec)) {
    rule <- spec[[col]]
    if (rule$agg == "recompute") {
      e <- rlang::parse_expr(rule$expr)
      grouped[[col]] <- rlang::eval_tidy(e, data = grouped)
    }
  }

  grouped <- dplyr::rename(grouped, sau_id = `__sau__`)

  if (keep_member_list) {
    members_df <- work %>%
      dplyr::group_by(dplyr::across(dplyr::all_of(group_keys))) %>%
      dplyr::summarise(members = list(sort(unique(.data[[vid_col]]))),
                       .groups = "drop") %>%
      dplyr::rename(sau_id = `__sau__`)
    grouped <- dplyr::left_join(grouped, members_df, by = c("sau_id", year_col))
  }

  var_order <- names(spec)
  front <- c("sau_id", year_col)
  if (length(extra_group_cols)) {
    front <- c(front, intersect(extra_group_cols, names(grouped)))
  }
  tail <- if (keep_member_list) "members" else character(0)
  cols_final <- c(front, intersect(var_order, names(grouped)), tail)
  grouped <- grouped[, cols_final, drop = FALSE]
  dplyr::arrange(grouped, sau_id, .data[[year_col]])
}

.normalize_spec <- function(vars_spec) {
  out <- list()
  for (col in names(vars_spec)) {
    rule <- vars_spec[[col]]
    if (is.character(rule) && length(rule) == 1L) rule <- list(agg = rule)
    if (is.null(rule$agg)) stop(sprintf("vars_spec['%s'] missing 'agg'", col))
    if (!rule$agg %in% .SUPPORTED_AGGS) {
      stop(sprintf("vars_spec['%s'].agg = '%s' must be one of: %s",
                   col, rule$agg, paste(.SUPPORTED_AGGS, collapse = ", ")))
    }
    if (rule$agg == "weighted_mean" && is.null(rule$weight)) {
      stop(sprintf("vars_spec['%s'] weighted_mean needs 'weight'", col))
    }
    if (rule$agg == "recompute" && is.null(rule$expr)) {
      stop(sprintf("vars_spec['%s'] recompute needs 'expr'", col))
    }
    out[[col]] <- rule
  }
  out
}

.validate_columns <- function(df, spec) {
  for (col in names(spec)) {
    rule <- spec[[col]]
    if (rule$agg == "recompute") next
    if (!col %in% names(df)) stop(sprintf("variable '%s' not in dataframe", col))
    if (rule$agg == "weighted_mean" && !rule$weight %in% names(df)) {
      stop(sprintf("weight column '%s' (for %s) not in dataframe",
                   rule$weight, col))
    }
  }
}
