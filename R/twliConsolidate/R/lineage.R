#' Build a Lineage object: V_ID <-> Stable Analysis Unit (SAU) mapping.
#'
#' A SAU is a connected component on the graph whose nodes are V_IDs and
#' whose edges connect every source V_ID to every target V_ID of every
#' relevant event. Each SAU represents one continuous physical area through
#' time.
#'
#' @param events A list of events from [load_crosswalk()].
#' @param year_range Length-2 integer vector ``c(start, end)`` (Gregorian).
#' @param include_boundary_adjust Logical; if ``TRUE``, ``boundary_adjust``
#'   events also union V_IDs into the same SAU. Defaults to ``FALSE``.
#' @return A list with class ``"twliLineage"`` containing
#'   ``vid_to_sau`` (named character vector),
#'   ``sau_to_vids`` (named list of character vectors),
#'   ``year_range``, ``events_used``, ``include_boundary_adjust``.
#' @export
build_lineage <- function(events, year_range, include_boundary_adjust = FALSE) {
  relevant <- filter_by_year_range(events, year_range)

  # Union-Find
  parent <- new.env(hash = TRUE, parent = emptyenv())
  find <- function(x) {
    if (is.null(parent[[x]])) {
      parent[[x]] <- x
      return(x)
    }
    while (parent[[x]] != x) {
      parent[[x]] <- parent[[parent[[x]]]]
      x <- parent[[x]]
    }
    x
  }
  union2 <- function(a, b) {
    ra <- find(a); rb <- find(b)
    if (ra != rb) parent[[rb]] <- ra
  }

  used <- list()
  for (ev in relevant) {
    if (ev$type == "boundary_adjust" && !include_boundary_adjust) next
    used[[length(used) + 1L]] <- ev
    nodes <- c(ev$sources, ev$targets)
    if (!length(nodes)) next
    anchor <- nodes[[1]]
    for (n in nodes[-1]) union2(anchor, n)
  }

  # Collect components
  all_v <- ls(parent)
  roots <- vapply(all_v, find, character(1))
  comps <- split(all_v, roots)

  vid_to_sau <- character(0)
  sau_to_vids <- list()
  for (members in comps) {
    sau_id <- paste0("SAU_", min(members))
    sau_to_vids[[sau_id]] <- sort(members)
    for (v in members) vid_to_sau[[v]] <- sau_id
  }

  structure(
    list(
      vid_to_sau              = vid_to_sau,
      sau_to_vids             = sau_to_vids,
      year_range              = year_range,
      events_used             = used,
      include_boundary_adjust = include_boundary_adjust
    ),
    class = "twliLineage"
  )
}

#' Look up the SAU id for a given V_ID.
#'
#' V_IDs not appearing in any consolidation event get their own SAU
#' ``"SAU_<v_id>"``.
#' @param lineage A ``twliLineage`` object from [build_lineage()].
#' @param v_id Character vector of village codes.
#' @return Character vector of SAU ids.
#' @export
sau_of <- function(lineage, v_id) {
  out <- lineage$vid_to_sau[v_id]
  fallback <- paste0("SAU_", v_id)
  ifelse(is.na(out), fallback, unname(out))
}

#' List the V_IDs that belong to a given SAU.
#' @param lineage A ``twliLineage`` object.
#' @param sau_id A single SAU id.
#' @export
sau_members <- function(lineage, sau_id) {
  if (sau_id %in% names(lineage$sau_to_vids)) {
    lineage$sau_to_vids[[sau_id]]
  } else {
    sub("^SAU_", "", sau_id)
  }
}
