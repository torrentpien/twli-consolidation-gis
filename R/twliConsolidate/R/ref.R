#' Compute the year interval each V_ID exists in, derived from events.
#'
#' @param events A list of events from [load_crosswalk()].
#' @return A list with two named integer vectors, ``first_year`` and
#'   ``last_year``. V_IDs absent from these vectors are assumed to exist
#'   throughout the analysis range.
#' @export
existence_intervals <- function(events) {
  first_year <- integer(0)
  last_year  <- integer(0)
  for (e in events) {
    srcs <- e$sources; tgts <- e$targets
    appearing    <- setdiff(tgts, srcs)
    disappearing <- setdiff(srcs, tgts)
    for (v in appearing) {
      prev <- first_year[v]
      first_year[v] <- if (is.na(prev)) e$effective_year
                       else max(prev, e$effective_year)
    }
    for (v in disappearing) {
      cand <- e$effective_year - 1L
      prev <- last_year[v]
      last_year[v] <- if (is.na(prev)) cand else min(prev, cand)
    }
  }
  list(first_year = first_year, last_year = last_year)
}

.exists_in_year <- function(v, year, fy, ly) {
  fyv <- fy[v]; lyv <- ly[v]
  if (!is.na(fyv) && year < fyv) return(FALSE)
  if (!is.na(lyv) && year > lyv) return(FALSE)
  TRUE
}

#' Build a per-data-year reference table for village consolidation
#' (對應原 twli 套件的 ``liRef``).
#'
#' @param events A list of events from [load_crosswalk()].
#' @param year_range Length-2 integer vector ``c(start, end)`` (Gregorian).
#' @param data_year Integer (Gregorian) of the panel-data slice.
#' @param include_boundary_adjust Logical.
#' @param present_vids Optional character vector restricting the reference to
#'   V_IDs actually present in the data for ``data_year``.
#' @return data.frame with columns ``v_id``, ``group``, ``merge_code``.
#'   Only SAUs with 2+ members co-existing in ``data_year`` produce rows.
#' @export
liRef <- function(events,
                  year_range,
                  data_year,
                  include_boundary_adjust = TRUE,
                  present_vids = NULL) {
  lineage <- build_lineage(events, year_range, include_boundary_adjust)
  rel <- lineage$events_used

  if (is.null(present_vids)) {
    iv <- existence_intervals(rel)
    is_present <- function(v) .exists_in_year(v, data_year, iv$first_year, iv$last_year)
  } else {
    pset <- as.character(present_vids)
    is_present <- function(v) v %in% pset
  }

  rows <- list()
  group_id <- 0L
  sau_ids <- sort(names(lineage$sau_to_vids))
  for (sau in sau_ids) {
    members <- lineage$sau_to_vids[[sau]]
    in_year <- sort(members[vapply(members, is_present, logical(1))])
    if (length(in_year) < 2L) next
    group_id <- group_id + 1L
    keeper <- in_year[1]
    mc <- 2L
    for (v in in_year) {
      if (v == keeper) {
        rows[[length(rows) + 1L]] <- data.frame(
          v_id = v, group = group_id, merge_code = 1L,
          stringsAsFactors = FALSE)
      } else {
        rows[[length(rows) + 1L]] <- data.frame(
          v_id = v, group = group_id, merge_code = mc,
          stringsAsFactors = FALSE)
        mc <- mc + 1L
      }
    }
  }
  if (!length(rows))
    return(data.frame(v_id = character(0), group = integer(0),
                      merge_code = integer(0), stringsAsFactors = FALSE))
  do.call(rbind, rows)
}
