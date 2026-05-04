"""twli-style aggregation functions: li_sum / li_equ / li_shp.

These mirror the API of the original R package
`torrentpien/twli <https://github.com/torrentpien/twli>`_ but operate on the
Python crosswalk produced by :func:`build_ref`.
"""
from __future__ import annotations

import re
from typing import Iterable

import pandas as pd


def li_sum(
    df: pd.DataFrame,
    ref: pd.DataFrame,
    cols: Iterable[str] | str,
    finish: bool = False,
    vid_col: str = "V_ID",
) -> pd.DataFrame:
    """Sum specified columns within each consolidation group (對應 ``liSum``).

    The summed values are written onto the row whose ``merge_code == 1`` (the
    keeper). Other group-member rows are left untouched (so ``li_equ`` can be
    chained afterwards). When ``finish=True`` the non-keeper rows are dropped
    and an ``li_adjust`` column (1 = aggregated keeper, 0 = unchanged) is
    appended.
    """
    cols = [cols] if isinstance(cols, str) else list(cols)
    _validate(df, ref, cols, vid_col)

    out = df.copy()
    joined = out[[vid_col, *cols]].merge(
        ref, left_on=vid_col, right_on="v_id", how="inner"
    )
    sums = joined.groupby("group", as_index=False)[cols].sum(min_count=1)

    keepers = ref[ref["merge_code"] == 1][["v_id", "group"]]
    keeper_map = keepers.set_index("v_id")["group"].to_dict()
    sums_map = sums.set_index("group")

    keeper_rows = out[vid_col].isin(keeper_map.keys())
    for idx in out[keeper_rows].index:
        v = out.at[idx, vid_col]
        g = keeper_map[v]
        for c in cols:
            out.at[idx, c] = sums_map.at[g, c]

    return _maybe_finalise(out, ref, vid_col, finish)


def li_equ(
    df: pd.DataFrame,
    ref: pd.DataFrame,
    result: str,
    equ: str,
    finish: bool = False,
    vid_col: str = "V_ID",
) -> pd.DataFrame:
    """Recompute a column from a formula after group-summing the operands
    (對應 ``liEqu``).

    ``equ`` is a string expression such as ``"P_CNT / AREA"``. Column names
    referenced inside ``equ`` are auto-detected, summed within each group,
    then ``equ`` is evaluated on the summed values and written to the keeper
    row's ``result`` column.

    Convention
    ----------
    Call all ``li_equ`` invocations on the raw dataframe **before** running
    ``li_sum`` on the same operand columns. ``li_equ`` re-sums the operand
    columns each call, so feeding it a dataframe whose operand columns have
    already been replaced by ``li_sum`` will double-count the keeper row.
    """
    operand_cols = _extract_columns(equ, df.columns)
    _validate(df, ref, operand_cols, vid_col)

    out = df.copy()
    joined = out[[vid_col, *operand_cols]].merge(
        ref, left_on=vid_col, right_on="v_id", how="inner"
    )
    sums = joined.groupby("group", as_index=False)[operand_cols].sum(min_count=1)
    sums[result] = sums.eval(equ)

    keepers = ref[ref["merge_code"] == 1][["v_id", "group"]]
    keeper_map = keepers.set_index("v_id")["group"].to_dict()
    sums_map = sums.set_index("group")[result].to_dict()

    if result not in out.columns:
        out[result] = pd.NA

    keeper_rows = out[vid_col].isin(keeper_map.keys())
    for idx in out[keeper_rows].index:
        v = out.at[idx, vid_col]
        g = keeper_map[v]
        out.at[idx, result] = sums_map[g]

    return _maybe_finalise(out, ref, vid_col, finish)


def li_shp(
    gdf,
    ref: pd.DataFrame,
    vid_col: str = "V_ID",
):
    """Geometric union of polygons within each consolidation group
    (對應 ``liShp``).

    Replaces the keeper-row geometry with ``shapely.unary_union`` of all group
    members and drops the non-keeper rows. ``gdf`` should be a
    :class:`geopandas.GeoDataFrame`.
    """
    try:
        import geopandas as gpd  # type: ignore
        from shapely.ops import unary_union
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "li_shp requires geopandas + shapely. Install via "
            "`pip install geopandas shapely`."
        ) from e
    if not isinstance(gdf, gpd.GeoDataFrame):
        raise TypeError("li_shp expects a geopandas.GeoDataFrame")

    out = gdf.copy()
    keepers = ref[ref["merge_code"] == 1][["v_id", "group"]]
    keeper_v_to_g = keepers.set_index("v_id")["group"].to_dict()
    member_v_to_g = ref.set_index("v_id")["group"].to_dict()

    # Compute unioned geometry per group
    out["__group__"] = out[vid_col].map(member_v_to_g)
    grouped_geoms = (
        out[out["__group__"].notna()]
        .groupby("__group__")["geometry"]
        .apply(lambda s: unary_union(list(s.values)))
    )

    # Replace keeper-row geometry
    for v, g in keeper_v_to_g.items():
        mask = out[vid_col] == v
        if mask.any() and g in grouped_geoms.index:
            out.loc[mask, "geometry"] = grouped_geoms.loc[g]

    # Drop non-keeper rows
    non_keeper_v = ref[ref["merge_code"] != 1]["v_id"].tolist()
    out = out[~out[vid_col].isin(non_keeper_v)].copy()
    out["li_adjust"] = out[vid_col].map(
        lambda v: 1 if v in keeper_v_to_g else 0
    ).astype(int)
    out = out.drop(columns=["__group__"], errors="ignore").reset_index(drop=True)
    return out


# ---------- internals ----------

_NUM_RE = re.compile(r"^[0-9.]+$")


def _extract_columns(expr: str, available: Iterable[str]) -> list[str]:
    """Pull identifiers out of an arithmetic expression like ``"P_CNT / AREA"``."""
    tokens = re.split(r"[/+\-*^()\s,]+", expr)
    available = set(available)
    out: list[str] = []
    for t in tokens:
        if not t or _NUM_RE.match(t):
            continue
        if t in available and t not in out:
            out.append(t)
    if not out:
        raise ValueError(
            f"No known columns referenced in expression {expr!r}; "
            "make sure operand names match the dataframe."
        )
    return out


def _validate(df: pd.DataFrame, ref: pd.DataFrame, cols: list[str], vid_col: str) -> None:
    if vid_col not in df.columns:
        raise KeyError(f"vid_col {vid_col!r} not in dataframe")
    for c in ("v_id", "group", "merge_code"):
        if c not in ref.columns:
            raise KeyError(f"ref dataframe missing required column {c!r}")
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"columns missing in dataframe: {missing}")


def _maybe_finalise(out: pd.DataFrame, ref: pd.DataFrame,
                    vid_col: str, finish: bool) -> pd.DataFrame:
    if not finish:
        return out
    non_keeper_v = set(ref.loc[ref["merge_code"] != 1, "v_id"])
    keeper_v = set(ref.loc[ref["merge_code"] == 1, "v_id"])
    out = out[~out[vid_col].isin(non_keeper_v)].copy()
    out["li_adjust"] = out[vid_col].map(lambda v: 1 if v in keeper_v else 0).astype(int)
    return out.reset_index(drop=True)
