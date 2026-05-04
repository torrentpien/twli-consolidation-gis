#' Sum specified columns within each consolidation group (對應 ``liSum``).
#'
#' Summed values are written onto the keeper row (``merge_code == 1``); other
#' rows are left untouched. When ``finish=TRUE`` the non-keeper rows are
#' dropped and an ``li_adjust`` column (1 = aggregated keeper, 0 = unchanged)
#' is appended.
#'
#' @param x A data.frame with at least ``vid_col`` and the columns named in
#'   ``cols``.
#' @param ref Reference table from [liRef()].
#' @param cols Character vector of columns to sum.
#' @param finish Logical; if TRUE, drop non-keeper rows and add
#'   ``li_adjust``.
#' @param vid_col Name of the village-code column. Default ``"V_ID"``.
#' @export
liSum <- function(x, ref, cols, finish = FALSE, vid_col = "V_ID") {
  .validate(x, ref, cols, vid_col)
  out <- x

  joined <- merge(out[, c(vid_col, cols), drop = FALSE], ref,
                  by.x = vid_col, by.y = "v_id")
  sums <- stats::aggregate(joined[, cols, drop = FALSE],
                           by = list(group = joined$group),
                           FUN = function(v) sum(v, na.rm = TRUE))
  keepers <- ref[ref$merge_code == 1L, c("v_id", "group")]
  rownames(sums) <- as.character(sums$group)
  for (i in seq_len(nrow(keepers))) {
    v <- keepers$v_id[i]; g <- as.character(keepers$group[i])
    rowi <- which(out[[vid_col]] == v)
    if (length(rowi)) for (c in cols) out[rowi, c] <- sums[g, c]
  }
  .maybe_finalise(out, ref, vid_col, finish)
}


#' Recompute a column from a formula after group-summing the operands
#' (對應 ``liEqu``).
#'
#' @param x A data.frame.
#' @param ref Reference table from [liRef()].
#' @param result Name of the column to write the recomputed value to.
#' @param equ Character expression, e.g. ``"P_CNT / AREA"``. Operand columns
#'   are auto-detected, summed, then ``equ`` is evaluated on the sums.
#' @param finish Logical; same as in [liSum()].
#' @param vid_col Name of the village-code column.
#' @section Convention:
#'   Run all ``liEqu`` calls first on the raw data **before** running
#'   ``liSum`` on the same operand columns; otherwise the operands will be
#'   double-counted.
#' @export
liEqu <- function(x, ref, result, equ, finish = FALSE, vid_col = "V_ID") {
  operand_cols <- .extract_columns(equ, names(x))
  .validate(x, ref, operand_cols, vid_col)
  out <- x

  joined <- merge(out[, c(vid_col, operand_cols), drop = FALSE], ref,
                  by.x = vid_col, by.y = "v_id")
  sums <- stats::aggregate(joined[, operand_cols, drop = FALSE],
                           by = list(group = joined$group),
                           FUN = function(v) sum(v, na.rm = TRUE))
  sums[[result]] <- eval(parse(text = equ), envir = sums)

  if (!result %in% names(out)) out[[result]] <- NA_real_

  keepers <- ref[ref$merge_code == 1L, c("v_id", "group")]
  rownames(sums) <- as.character(sums$group)
  for (i in seq_len(nrow(keepers))) {
    v <- keepers$v_id[i]; g <- as.character(keepers$group[i])
    rowi <- which(out[[vid_col]] == v)
    if (length(rowi)) out[rowi, result] <- sums[g, result]
  }
  .maybe_finalise(out, ref, vid_col, finish)
}


#' Geometric union of polygons within each consolidation group
#' (對應 ``liShp``).
#'
#' Uses ``sf::st_union`` to combine geometries within each group, replaces the
#' keeper row's geometry with the union, then drops the non-keeper rows. An
#' ``li_adjust`` column is added.
#'
#' @param x An ``sf`` object with ``vid_col``.
#' @param ref Reference table from [liRef()].
#' @param vid_col Name of the village-code column.
#' @export
liShp <- function(x, ref, vid_col = "V_ID") {
  if (!requireNamespace("sf", quietly = TRUE))
    stop("liShp requires the 'sf' package")
  if (!inherits(x, "sf"))
    stop("liShp expects an 'sf' object")

  out <- x
  out$`__group__` <- ref$group[match(out[[vid_col]], ref$v_id)]

  # Compute union per group
  in_groups <- out[!is.na(out$`__group__`), ]
  if (nrow(in_groups) > 0) {
    union_per_group <- list()
    for (g in unique(in_groups$`__group__`)) {
      union_per_group[[as.character(g)]] <-
        sf::st_union(sf::st_geometry(in_groups[in_groups$`__group__` == g, ]))
    }
    keepers <- ref[ref$merge_code == 1L, ]
    for (i in seq_len(nrow(keepers))) {
      v <- keepers$v_id[i]; g <- as.character(keepers$group[i])
      idx <- which(out[[vid_col]] == v)
      if (length(idx) && !is.null(union_per_group[[g]])) {
        sf::st_geometry(out)[[idx[1]]] <- union_per_group[[g]][[1]]
      }
    }
  }

  non_keeper_v <- ref$v_id[ref$merge_code != 1L]
  out <- out[!out[[vid_col]] %in% non_keeper_v, ]
  out$li_adjust <- ifelse(out[[vid_col]] %in% ref$v_id[ref$merge_code == 1L], 1L, 0L)
  out$`__group__` <- NULL
  out
}


# ---------- internals ----------

.NUM_RE <- "^[0-9.]+$"

.extract_columns <- function(equ, available) {
  toks <- strsplit(gsub("\\s+", " ", equ), "[\\s/+\\-*^()(),]+", perl = TRUE)[[1]]
  toks <- toks[nchar(toks) > 0 & !grepl(.NUM_RE, toks)]
  out <- intersect(unique(toks), available)
  if (!length(out))
    stop(sprintf("No known columns referenced in expression %s", equ))
  out
}

.validate <- function(x, ref, cols, vid_col) {
  if (!vid_col %in% names(x)) stop(sprintf("vid_col '%s' not in data", vid_col))
  for (c in c("v_id", "group", "merge_code")) {
    if (!c %in% names(ref)) stop(sprintf("ref missing column '%s'", c))
  }
  miss <- setdiff(cols, names(x))
  if (length(miss)) stop(sprintf("columns missing in data: %s",
                                 paste(miss, collapse = ", ")))
}

.maybe_finalise <- function(out, ref, vid_col, finish) {
  if (!finish) return(out)
  non_keeper_v <- ref$v_id[ref$merge_code != 1L]
  keeper_v <- ref$v_id[ref$merge_code == 1L]
  out <- out[!out[[vid_col]] %in% non_keeper_v, ]
  out$li_adjust <- ifelse(out[[vid_col]] %in% keeper_v, 1L, 0L)
  rownames(out) <- NULL
  out
}
