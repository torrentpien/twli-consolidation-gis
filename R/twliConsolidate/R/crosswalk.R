#' Valid event types in the village consolidation crosswalk.
#' @keywords internal
.VALID_EVENT_TYPES <- c("rename", "merge", "split", "redistribute",
                        "boundary_adjust")

#' Load the village consolidation crosswalk YAML.
#'
#' @param path Path to the YAML file (e.g. ``"crosswalk/village_changes.yaml"``).
#' @return A list of event records. Each event is a list with elements
#'   ``id``, ``effective_year`` (Gregorian integer), ``type``,
#'   ``sources`` (character vector of V_IDs in the prior snapshot),
#'   ``targets`` (character vector of V_IDs in the new snapshot), and
#'   ``raw`` (the original YAML record).
#' @export
load_crosswalk <- function(path) {
  doc <- yaml::read_yaml(path)
  raw_events <- doc$events %||% list()
  lapply(raw_events, function(ev) {
    if (!ev$type %in% .VALID_EVENT_TYPES) {
      stop(sprintf("Unknown event type %s in event %s", ev$type, ev$id))
    }
    list(
      id              = ev$id,
      effective_year  = as.integer(ev$effective_year),
      type            = ev$type,
      sources         = vapply(ev$sources %||% list(),
                               function(x) x$v_id, character(1)),
      targets         = vapply(ev$targets %||% list(),
                               function(x) x$v_id, character(1)),
      raw             = ev
    )
  })
}

#' Restrict an event list to those whose effective_year falls inside
#' a given panel range.
#'
#' Events with ``start_year < effective_year <= end_year`` are kept.
#'
#' @param events A list of events from [load_crosswalk()].
#' @param year_range Length-2 integer vector ``c(start, end)`` (Gregorian).
#' @export
filter_by_year_range <- function(events, year_range) {
  stopifnot(length(year_range) == 2L)
  start <- year_range[[1]]; end <- year_range[[2]]
  Filter(function(e) e$effective_year > start && e$effective_year <= end, events)
}

`%||%` <- function(a, b) if (is.null(a)) b else a
