"""Recompute panel data over Taiwan village consolidation history.

Typical usage:

    import twli_consolidate as tc

    cw = tc.load_crosswalk("crosswalk/village_changes.yaml")
    lineage = tc.build_lineage(cw, year_range=(2020, 2024))

    out = tc.consolidate_panel(
        df,
        vid_col="V_ID",
        year_col="year",
        vars_spec={
            "P_CNT": {"agg": "sum"},
            "AREA":  {"agg": "sum"},
            "DENSITY": {"agg": "recompute", "expr": "P_CNT / AREA"},
        },
        lineage=lineage,
    )

"""
from .crosswalk import Event, bundled_crosswalk_path, load_crosswalk
from .lineage import Lineage, build_lineage
from .consolidate import consolidate_panel
from .ref import build_ref, existence_intervals
from .twli import li_sum, li_equ, li_shp

__all__ = [
    "Event",
    "bundled_crosswalk_path",
    "load_crosswalk",
    "Lineage",
    "build_lineage",
    "consolidate_panel",
    "build_ref",
    "existence_intervals",
    "li_sum",
    "li_equ",
    "li_shp",
]
__version__ = "0.1.0"
