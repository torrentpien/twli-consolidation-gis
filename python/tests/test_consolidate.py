"""End-to-end tests using the actual 110-114 SHP-derived panel."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import geopandas as gpd
import pandas as pd
import pytest

import twli_consolidate as tc


CROSSWALK = ROOT / "crosswalk" / "village_changes.yaml"


def _build_panel() -> pd.DataFrame:
    """Construct a long-format panel from 110-114 SHPs."""
    rows = []
    for roc in [110, 111, 112, 113, 114]:
        ce = roc + 1911
        path = ROOT / f"data/{roc}年12月行政區人口統計_村里_SHP/{roc}年12月行政區人口統計_村里.SHP"
        g = gpd.read_file(path, encoding="cp950")
        df = pd.DataFrame({
            "year": ce,
            "V_ID": g["V_ID"],
            "COUNTY": g["COUNTY"],
            "TOWN": g["TOWN"],
            "VILLAGE": g["VILLAGE"],
            "P_CNT": g["P_CNT"],
            "H_CNT": g["H_CNT"],
            "AREA_M2": g.geometry.area,
        })
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


# ---------- crosswalk + lineage ----------

def test_load_crosswalk_returns_events():
    events = tc.load_crosswalk(CROSSWALK)
    assert len(events) > 0
    types = {e.type for e in events}
    assert {"rename", "merge", "split", "redistribute", "boundary_adjust"} >= types


def test_lineage_year_range_filters_events():
    events = tc.load_crosswalk(CROSSWALK)
    # 110->111 is the only year-pair with V_ID changes; effective_year=2022
    in_range = tc.build_lineage(events, year_range=(2021, 2025))
    assert any(e.effective_year == 2022 and e.type != "boundary_adjust"
               for e in in_range.events_used)
    out_of_range = tc.build_lineage(events, year_range=(2024, 2025))
    assert all(e.effective_year > 2024 and e.effective_year <= 2025 or
               e.effective_year > 2024
               for e in out_of_range.events_used)
    # 113->114 transition has zero events
    assert len(out_of_range.events_used) == 0


def test_lineage_lukang_top_grouping():
    """頂厝里(005) -> 頂厝里(005) + 鹿和里(030) + 鹿東里(031)."""
    events = tc.load_crosswalk(CROSSWALK)
    lin = tc.build_lineage(events, year_range=(2021, 2025))
    sau = lin.sau_of("10007020-005")
    members = lin.members(sau)
    assert {"10007020-005", "10007020-030", "10007020-031"} <= members


def test_lineage_bade_redistribute_grouping():
    """八德區 興仁里(001) + 福興里(002) + 福元里(049) + 福德里(050) + 興中里(051)."""
    events = tc.load_crosswalk(CROSSWALK)
    lin = tc.build_lineage(events, year_range=(2021, 2025))
    sau = lin.sau_of("68000080-001")
    members = lin.members(sau)
    expected = {"68000080-001", "68000080-002", "68000080-049",
                "68000080-050", "68000080-051"}
    assert expected <= members


def test_lineage_dliao_merge_grouping():
    """大寮區 光武里(024) -> 忠義里(018)."""
    events = tc.load_crosswalk(CROSSWALK)
    lin = tc.build_lineage(events, year_range=(2021, 2025))
    sau_018 = lin.sau_of("64000140-018")
    sau_024 = lin.sau_of("64000140-024")
    assert sau_018 == sau_024
    assert {"64000140-018", "64000140-024"} <= lin.members(sau_018)


def test_lineage_unaffected_vid_passes_through():
    events = tc.load_crosswalk(CROSSWALK)
    lin = tc.build_lineage(events, year_range=(2021, 2025))
    # A village known to have no changes
    untouched = "09020010-001"  # 金門縣 金城鎮 first village
    assert lin.sau_of(untouched) == f"SAU_{untouched}"


# ---------- consolidate_panel ----------

@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return _build_panel()


@pytest.fixture(scope="module")
def lineage_full():
    events = tc.load_crosswalk(CROSSWALK)
    return tc.build_lineage(events, year_range=(2021, 2025))


def test_consolidate_lukang_split_population_continuous(panel, lineage_full):
    """After consolidation, the SAU containing 頂厝里 should have a smooth
    population time series across 2021 (one V_ID) and 2022+ (three V_IDs)."""
    out = tc.consolidate_panel(
        panel,
        vid_col="V_ID",
        year_col="year",
        vars_spec={
            "P_CNT":   "sum",
            "H_CNT":   "sum",
            "AREA_M2": "sum",
            "DENSITY": {"agg": "recompute", "expr": "P_CNT / (AREA_M2 / 1e6)"},
        },
        lineage=lineage_full,
        extra_group_cols=["COUNTY", "TOWN"],
    )
    sau = lineage_full.sau_of("10007020-005")
    rows = out[out["sau_id"] == sau].sort_values("year")
    assert len(rows) == 5  # one row per year

    # Pre-split year (2021): one source V_ID
    pre = rows[rows["year"] == 2021].iloc[0]
    assert pre["members"] == ["10007020-005"]

    # Post-split year (2022): three V_IDs aggregated
    post = rows[rows["year"] == 2022].iloc[0]
    assert set(post["members"]) == {"10007020-005", "10007020-030", "10007020-031"}

    # Area should be continuous (split conserves total area)
    areas = rows["AREA_M2"].tolist()
    assert max(areas) - min(areas) < 1.0  # equal up to floating-point noise


def test_consolidate_dliao_merge_population_continuous(panel, lineage_full):
    """光武里(024) and 忠義里(018) should aggregate to one SAU.
    2021 has both (separate rows); 2022+ has only 018 with absorbed area."""
    out = tc.consolidate_panel(
        panel,
        vid_col="V_ID",
        year_col="year",
        vars_spec={"P_CNT": "sum", "AREA_M2": "sum"},
        lineage=lineage_full,
    )
    sau = lineage_full.sau_of("64000140-018")
    rows = out[out["sau_id"] == sau].sort_values("year")
    assert len(rows) == 5
    pre = rows[rows["year"] == 2021].iloc[0]
    post = rows[rows["year"] == 2022].iloc[0]
    assert {"64000140-018", "64000140-024"} == set(pre["members"])
    assert ["64000140-018"] == post["members"]
    # Area conservation: pre and post total area are nearly equal
    assert abs(pre["AREA_M2"] - post["AREA_M2"]) < 1.0


def test_consolidate_weighted_mean(panel, lineage_full):
    """Weighted-mean aggregation: average household size weighted by households."""
    panel = panel.copy()
    panel["AVG_HH_SIZE"] = panel["P_CNT"] / panel["H_CNT"].replace(0, pd.NA)
    out = tc.consolidate_panel(
        panel,
        vid_col="V_ID",
        year_col="year",
        vars_spec={
            "P_CNT": "sum",
            "H_CNT": "sum",
            "AVG_HH_SIZE": {"agg": "weighted_mean", "weight": "H_CNT"},
        },
        lineage=lineage_full,
    )
    # For an unaffected single-village SAU, weighted mean equals the original value
    sau = lineage_full.sau_of("09020010-001")
    rows = out[out["sau_id"] == sau].sort_values("year")
    raw = panel[panel["V_ID"] == "09020010-001"].sort_values("year")
    for _, r in rows.iterrows():
        orig = raw[raw["year"] == r["year"]].iloc[0]
        assert abs(r["AVG_HH_SIZE"] - orig["AVG_HH_SIZE"]) < 1e-9


def test_consolidate_total_population_invariant(panel, lineage_full):
    """The grand total of P_CNT across all SAUs equals the raw total per year."""
    out = tc.consolidate_panel(
        panel,
        vid_col="V_ID",
        year_col="year",
        vars_spec={"P_CNT": "sum"},
        lineage=lineage_full,
    )
    raw_totals = panel.groupby("year")["P_CNT"].sum()
    sau_totals = out.groupby("year")["P_CNT"].sum()
    pd.testing.assert_series_equal(raw_totals, sau_totals, check_names=False)


def test_year_range_changes_lineage(panel):
    """Limiting year_range to 2023-2025 (no V_ID changes) leaves every village
    as its own SAU."""
    events = tc.load_crosswalk(CROSSWALK)
    narrow = tc.build_lineage(events, year_range=(2023, 2025))
    assert all(e.type == "boundary_adjust" for e in narrow.events_used) or len(narrow.events_used) == 0
    # Sample: 鹿和里(030) which only exists from 2022 onward; in narrow range
    # there are no V_ID-change events, so it gets its own SAU.
    assert narrow.sau_of("10007020-030") == "SAU_10007020-030"
    assert narrow.sau_of("10007020-005") == "SAU_10007020-005"


# ---------- keep_if_unique ----------

def test_consolidate_keep_if_unique(panel, lineage_full):
    """keep_if_unique: single-V_ID SAU preserves value, multi-V_ID SAU gets NaN.

    Use case: 衍生統計量（中位數、分位數等）無法從區級彙總重算。
    """
    panel = panel.copy()
    # 模擬「中位數」這類無法 sum 的指標：給每個 V_ID 一個固定的虛擬中位數值
    panel["MEDIAN_INCOME"] = (panel["P_CNT"] * 0.1).round()

    out = tc.consolidate_panel(
        panel,
        vid_col="V_ID",
        year_col="year",
        vars_spec={
            "P_CNT": "sum",
            "MEDIAN_INCOME": "keep_if_unique",
        },
        lineage=lineage_full,
        keep_member_list=True,
    )

    # 鹿港頂厝里在 2022 被 005+030+031 三個 V_ID 整併 → MEDIAN_INCOME 應為 NaN
    lukang_sau = lineage_full.sau_of("10007020-005")
    lukang_2022 = out[(out["sau_id"] == lukang_sau) & (out["year"] == 2022)].iloc[0]
    assert len(lukang_2022["members"]) == 3
    assert pd.isna(lukang_2022["MEDIAN_INCOME"])

    # 鹿港頂厝里在 2021（拆分前）僅 005 一個 V_ID → 保留原值
    lukang_2021 = out[(out["sau_id"] == lukang_sau) & (out["year"] == 2021)].iloc[0]
    assert len(lukang_2021["members"]) == 1
    assert not pd.isna(lukang_2021["MEDIAN_INCOME"])

    # 未受整併的村里：所有年都保留原值
    unaffected_sau = lineage_full.sau_of("09020010-001")  # 連江縣某村里
    unaffected_rows = out[out["sau_id"] == unaffected_sau]
    for _, r in unaffected_rows.iterrows():
        assert len(r["members"]) == 1
        assert not pd.isna(r["MEDIAN_INCOME"])
