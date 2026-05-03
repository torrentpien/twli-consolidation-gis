"""Load and represent village consolidation events from the YAML crosswalk."""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Iterable

import yaml


VALID_TYPES = {"rename", "merge", "split", "redistribute", "boundary_adjust"}


def bundled_crosswalk_path() -> Path:
    """Return the file path of the crosswalk YAML shipped with the package."""
    with resources.as_file(resources.files(__package__) / "data" / "village_changes.yaml") as p:
        return Path(p)


@dataclass(frozen=True)
class Event:
    """One administrative-boundary change event between two annual snapshots."""
    id: str
    effective_year: int          # Gregorian year from which the new boundary applies
    type: str                    # one of VALID_TYPES
    sources: tuple[str, ...]     # V_IDs in the prior snapshot
    targets: tuple[str, ...]     # V_IDs in the new snapshot
    raw: dict = field(repr=False, default_factory=dict)

    def affected_vids(self) -> set[str]:
        return set(self.sources) | set(self.targets)


def load_crosswalk(path: str | Path) -> list[Event]:
    """Load the crosswalk YAML file and return a list of Event objects."""
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    raw_events = doc.get("events", [])
    out: list[Event] = []
    for ev in raw_events:
        etype = ev["type"]
        if etype not in VALID_TYPES:
            raise ValueError(f"Unknown event type {etype!r} in event {ev.get('id')}")
        srcs = tuple(item["v_id"] for item in ev.get("sources", []))
        tgts = tuple(item["v_id"] for item in ev.get("targets", []))
        out.append(Event(
            id=ev["id"],
            effective_year=int(ev["effective_year"]),
            type=etype,
            sources=srcs,
            targets=tgts,
            raw=ev,
        ))
    return out


def filter_by_year_range(events: Iterable[Event], year_range: tuple[int, int]) -> list[Event]:
    """Keep only events whose effective_year falls inside (start_year, end_year].

    An event with effective_year = Y means: starting from year Y the new boundary
    is in effect. If the user's panel covers years [start, end], only events
    with start < Y <= end actually cause a boundary change inside the panel.
    """
    start, end = year_range
    return [e for e in events if start < e.effective_year <= end]
