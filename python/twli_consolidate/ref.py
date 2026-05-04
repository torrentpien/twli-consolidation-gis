"""Per-data-year reference table (對應 twli::liRef).

The reference table is the bridge between an analysis-range *lineage* (which
groups V_IDs across years) and one specific data-year file. For each Stable
Analysis Unit that has 2+ members co-existing in ``data_year``, the reference
records ``(v_id, group, merge_code)`` so that downstream functions can sum,
recompute, or geometrically union those rows together.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from .crosswalk import Event
from .lineage import build_lineage


def existence_intervals(events: Iterable[Event]) -> tuple[dict[str, int], dict[str, int]]:
    """Compute the year interval each V_ID exists in, derived purely from events.

    Returns
    -------
    (first_year, last_year) : two dicts mapping V_ID to the first / last
        Gregorian year it appears in. V_IDs not in the dicts are assumed to
        exist throughout the analysis range.
    """
    first_year: dict[str, int] = {}
    last_year: dict[str, int] = {}
    for e in events:
        srcs, tgts = set(e.sources), set(e.targets)
        appearing = tgts - srcs            # appeared at e.effective_year
        disappearing = srcs - tgts          # disappeared from e.effective_year
        for v in appearing:
            prev = first_year.get(v)
            first_year[v] = max(prev, e.effective_year) if prev is not None else e.effective_year
        for v in disappearing:
            prev = last_year.get(v)
            cand = e.effective_year - 1
            last_year[v] = min(prev, cand) if prev is not None else cand
    return first_year, last_year


def _exists_in_year(v_id: str, year: int,
                    first_year: dict[str, int],
                    last_year: dict[str, int]) -> bool:
    fy = first_year.get(v_id)
    ly = last_year.get(v_id)
    if fy is not None and year < fy:
        return False
    if ly is not None and year > ly:
        return False
    return True


def build_ref(
    events: Iterable[Event],
    year_range: tuple[int, int],
    data_year: int,
    include_boundary_adjust: bool = True,
    present_vids: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Build a per-data-year reference table for village consolidation.

    對應 R 套件 twli 的 ``liRef``。

    Parameters
    ----------
    events : iterable of Event
        From :func:`load_crosswalk`.
    year_range : (start_year, end_year)
        Gregorian. The full analysis range. Events with
        ``start < effective_year <= end`` are considered relevant.
    data_year : int
        The Gregorian year of the panel-data slice this reference is for.
    include_boundary_adjust : bool, default True
        If True, ``boundary_adjust`` events also create groups.
    present_vids : iterable of V_IDs, optional
        If provided, restricts the reference to V_IDs actually present in the
        user's data for ``data_year``. Otherwise existence is inferred from
        the events themselves.

    Returns
    -------
    DataFrame with columns ``[v_id, group, merge_code]`` where
    ``merge_code == 1`` marks the row that will absorb the aggregated values
    (``li_adjust = 1`` after a finalising call). Only SAUs with 2+ members
    co-existing in ``data_year`` produce rows.
    """
    lineage = build_lineage(events, year_range, include_boundary_adjust)
    rel_events = lineage.events_used

    if present_vids is None:
        first_y, last_y = existence_intervals(rel_events)

        def is_present(v: str) -> bool:
            return _exists_in_year(v, data_year, first_y, last_y)
    else:
        present_set = set(present_vids)

        def is_present(v: str) -> bool:
            return v in present_set

    rows = []
    group_id = 0
    for sau_id in sorted(lineage.sau_to_vids.keys()):
        members = lineage.sau_to_vids[sau_id]
        in_year = sorted(v for v in members if is_present(v))
        if len(in_year) < 2:
            continue
        group_id += 1
        keeper = in_year[0]  # lex-smallest among members present in data_year
        merge_code = 2
        for v in in_year:
            if v == keeper:
                rows.append({"v_id": v, "group": group_id, "merge_code": 1})
            else:
                rows.append({"v_id": v, "group": group_id, "merge_code": merge_code})
                merge_code += 1
    return pd.DataFrame(rows, columns=["v_id", "group", "merge_code"])
