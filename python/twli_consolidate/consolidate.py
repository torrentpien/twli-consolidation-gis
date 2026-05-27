"""Aggregate panel data to Stable Analysis Units."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from .lineage import Lineage


SUPPORTED_AGGS = {"sum", "mean", "first", "last", "min", "max",
                  "weighted_mean", "recompute", "keep_if_unique"}


def _keep_if_unique(s: pd.Series):
    """Return the single value if the group has exactly one V_ID member,
    otherwise NaN.

    Use case: 衍生統計量（中位數、分位數、標準差、變異係數等）無法從區級彙總
    重算。對 SAU 內單一 V_ID（未整併）保留原值；對多 V_ID SAU（整併過）標 NaN。
    """
    s = s.dropna()
    return s.iloc[0] if len(s) == 1 else float("nan")


def consolidate_panel(
    df: pd.DataFrame,
    *,
    vid_col: str,
    year_col: str,
    vars_spec: Mapping[str, Mapping[str, Any] | str],
    lineage: Lineage,
    extra_group_cols: list[str] | None = None,
    keep_member_list: bool = True,
) -> pd.DataFrame:
    """Recompute a panel dataset over Stable Analysis Units.

    Parameters
    ----------
    df : DataFrame
        Long-format panel. Must contain ``vid_col`` and ``year_col`` plus any
        variable columns referenced in ``vars_spec``.
    vid_col : str
        Name of the village-code column (matches V_IDs in the crosswalk).
    year_col : str
        Name of the year column (Gregorian integer).
    vars_spec : mapping
        Per-variable aggregation rule. Either a string shorthand
        (``"sum" | "mean" | "first" | "last" | "min" | "max" | "keep_if_unique"``)
        or a dict::

            {"agg": "sum"}
            {"agg": "weighted_mean", "weight": "P_CNT"}
            {"agg": "recompute", "expr": "P_CNT / AREA"}
            {"agg": "keep_if_unique"}  # 對 SAU 內單一 V_ID 保留原值，多 V_ID 標 NaN

        ``recompute`` rules run **after** all other aggregations. The
        expression is evaluated with :py:meth:`pandas.DataFrame.eval` and may
        reference any already-aggregated column.
    lineage : Lineage
        Built from :func:`twli_consolidate.build_lineage`.
    extra_group_cols : list[str], optional
        Additional columns to keep in grouping (e.g. ``["COUNTY", "TOWN"]``).
        Within an SAU these may differ across members; the value of the first
        member encountered is used.
    keep_member_list : bool, default True
        If True, include a ``members`` column listing all original V_IDs that
        were aggregated for that (sau_id, year) row.

    Returns
    -------
    DataFrame with one row per (sau_id, year), columns:
    ``[sau_id, year, *extra_group_cols, *aggregated vars, members?]``
    """
    if vid_col not in df.columns:
        raise KeyError(f"vid_col {vid_col!r} not in dataframe")
    if year_col not in df.columns:
        raise KeyError(f"year_col {year_col!r} not in dataframe")

    spec = _normalize_spec(vars_spec)
    _validate_columns(df, spec)

    work = df.copy()
    work["__sau__"] = work[vid_col].map(lineage.sau_of)

    # Phase 1: per-row pre-multiplication for weighted_mean
    aux_cols: dict[str, str] = {}
    for col, rule in spec.items():
        if rule["agg"] == "weighted_mean":
            wcol = rule["weight"]
            num = f"__num__{col}"
            den = f"__den__{col}"
            work[num] = work[col] * work[wcol]
            work[den] = work[wcol]
            aux_cols[col] = (num, den)

    # Phase 2: build groupby aggregation map
    agg_map: dict[str, Any] = {}
    for col, rule in spec.items():
        a = rule["agg"]
        if a in {"sum", "mean", "first", "last", "min", "max"}:
            agg_map[col] = a
        elif a == "keep_if_unique":
            agg_map[col] = _keep_if_unique
        elif a == "weighted_mean":
            num, den = aux_cols[col]
            agg_map[num] = "sum"
            agg_map[den] = "sum"
        elif a == "recompute":
            pass  # handled in phase 3
    if extra_group_cols:
        for c in extra_group_cols:
            if c in df.columns:
                agg_map.setdefault(c, "first")

    grouped = work.groupby(["__sau__", year_col], as_index=False, dropna=False).agg(agg_map)

    # Phase 3: finalize weighted_mean and recompute
    for col, rule in spec.items():
        if rule["agg"] == "weighted_mean":
            num, den = aux_cols[col]
            grouped[col] = grouped[num] / grouped[den].where(grouped[den] != 0)
            grouped = grouped.drop(columns=[num, den])

    for col, rule in spec.items():
        if rule["agg"] == "recompute":
            grouped[col] = grouped.eval(rule["expr"])

    grouped = grouped.rename(columns={"__sau__": "sau_id"})

    if keep_member_list:
        members = (
            work.groupby(["__sau__", year_col], dropna=False)[vid_col]
            .agg(lambda s: sorted(set(s)))
            .reset_index()
            .rename(columns={"__sau__": "sau_id", vid_col: "members"})
        )
        grouped = grouped.merge(members, on=["sau_id", year_col], how="left")

    # Order: sau_id, year, extras, vars, members
    var_order = list(spec.keys())
    front = ["sau_id", year_col]
    if extra_group_cols:
        front += [c for c in extra_group_cols if c in grouped.columns]
    tail = ["members"] if keep_member_list else []
    cols_final = front + [c for c in var_order if c in grouped.columns] + tail
    return grouped[cols_final].sort_values(["sau_id", year_col]).reset_index(drop=True)


def _normalize_spec(vars_spec) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for col, rule in vars_spec.items():
        if isinstance(rule, str):
            rule = {"agg": rule}
        if "agg" not in rule:
            raise ValueError(f"vars_spec[{col!r}] missing 'agg' key")
        if rule["agg"] not in SUPPORTED_AGGS:
            raise ValueError(
                f"vars_spec[{col!r}].agg = {rule['agg']!r}; "
                f"must be one of {sorted(SUPPORTED_AGGS)}"
            )
        if rule["agg"] == "weighted_mean" and "weight" not in rule:
            raise ValueError(f"vars_spec[{col!r}] weighted_mean needs 'weight'")
        if rule["agg"] == "recompute" and "expr" not in rule:
            raise ValueError(f"vars_spec[{col!r}] recompute needs 'expr'")
        out[col] = dict(rule)
    return out


def _validate_columns(df: pd.DataFrame, spec: dict) -> None:
    for col, rule in spec.items():
        if rule["agg"] == "recompute":
            continue
        if col not in df.columns:
            raise KeyError(f"variable {col!r} not in dataframe")
        if rule["agg"] == "weighted_mean" and rule["weight"] not in df.columns:
            raise KeyError(f"weight column {rule['weight']!r} (for {col}) not in dataframe")
