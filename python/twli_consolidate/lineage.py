"""Build Stable Analysis Units (SAU) by chaining consolidation events.

A SAU is a connected component over the graph whose nodes are V_IDs and
whose edges connect every source-V_ID to every target-V_ID of every event
within the requested year range. Each SAU represents one continuous physical
area through time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .crosswalk import Event, filter_by_year_range


@dataclass(frozen=True)
class Lineage:
    """Mapping between V_IDs and their Stable Analysis Unit ID."""
    vid_to_sau: dict[str, str]
    sau_to_vids: dict[str, frozenset[str]]
    year_range: tuple[int, int]
    events_used: tuple[Event, ...]
    include_boundary_adjust: bool

    def sau_of(self, v_id: str) -> str:
        """Return the SAU id for a given V_ID. Falls back to ``SAU_<v_id>`` for V_IDs
        that were never involved in a consolidation event in this year range."""
        return self.vid_to_sau.get(v_id, f"SAU_{v_id}")

    def members(self, sau_id: str) -> frozenset[str]:
        return self.sau_to_vids.get(sau_id, frozenset())


def build_lineage(
    events: Iterable[Event],
    year_range: tuple[int, int],
    include_boundary_adjust: bool = False,
) -> Lineage:
    """Build a Lineage from a list of events, restricted to year_range.

    Parameters
    ----------
    events : iterable of Event
    year_range : (start_year, end_year)
        Both Gregorian. Events with start < effective_year <= end are applied.
    include_boundary_adjust : bool, default False
        If True, ``boundary_adjust`` events also create SAU groupings (i.e.
        V_IDs that exchanged area within a town are merged into one analysis
        unit). Default ``False`` keeps them separate because the V_ID itself
        does not change in the user's panel.
    """
    relevant = filter_by_year_range(events, year_range)

    # Union-Find over V_IDs
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    used: list[Event] = []
    for ev in relevant:
        if ev.type == "boundary_adjust" and not include_boundary_adjust:
            continue
        used.append(ev)
        nodes = list(ev.sources) + list(ev.targets)
        if not nodes:
            continue
        anchor = nodes[0]
        for n in nodes[1:]:
            union(anchor, n)

    # Collect components
    comps: dict[str, set[str]] = {}
    for v in parent:
        r = find(v)
        comps.setdefault(r, set()).add(v)

    # Stable SAU id = SAU_<lex-smallest-V_ID-in-component>
    vid_to_sau: dict[str, str] = {}
    sau_to_vids: dict[str, frozenset[str]] = {}
    for members in comps.values():
        sau_id = f"SAU_{min(members)}"
        sau_to_vids[sau_id] = frozenset(members)
        for v in members:
            vid_to_sau[v] = sau_id

    return Lineage(
        vid_to_sau=vid_to_sau,
        sau_to_vids=sau_to_vids,
        year_range=year_range,
        events_used=tuple(used),
        include_boundary_adjust=include_boundary_adjust,
    )
