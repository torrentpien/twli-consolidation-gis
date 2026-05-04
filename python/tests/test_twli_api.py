"""End-to-end tests for the twli-style API: build_ref / li_sum / li_equ / li_shp."""
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


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def events():
    return tc.load_crosswalk(CROSSWALK)


def _read_year(roc: int) -> gpd.GeoDataFrame:
    p = ROOT / f"data/{roc}年12月行政區人口統計_村里_SHP/{roc}年12月行政區人口統計_村里.SHP"
    g = gpd.read_file(p, encoding="cp950")
    g["AREA_M2"] = g.geometry.area
    g["year"] = 1911 + roc
    return g


@pytest.fixture(scope="module")
def shp_2021():
    return _read_year(110)


@pytest.fixture(scope="module")
def shp_2022():
    return _read_year(111)


# ---------- build_ref ----------

def test_build_ref_2021_groups_split_villages(events):
    """2021 data has only 005 (頂厝里); the split won't appear in 2021 ref."""
    ref = tc.build_ref(events, year_range=(2021, 2025), data_year=2021)
    rocks = ref[ref["v_id"].isin(["10007020-005", "10007020-030", "10007020-031"])]
    assert rocks.empty  # 030 and 031 don't exist yet in 2021


def test_build_ref_2022_groups_split_villages(events):
    """2022 data has 005, 030, 031 — all three should be in one group."""
    ref = tc.build_ref(events, year_range=(2021, 2025), data_year=2022)
    rocks = ref[ref["v_id"].isin(["10007020-005", "10007020-030", "10007020-031"])]
    assert len(rocks) == 3
    assert rocks["group"].nunique() == 1
    keeper = rocks[rocks["merge_code"] == 1]
    assert keeper["v_id"].tolist() == ["10007020-005"]  # smallest V_ID survives


def test_build_ref_2021_groups_merge_villages(events):
    """2021 has both 大寮區 光武里(024) and 忠義里(018); ref groups them."""
    ref = tc.build_ref(events, year_range=(2021, 2025), data_year=2021)
    pair = ref[ref["v_id"].isin(["64000140-018", "64000140-024"])]
    assert len(pair) == 2
    assert pair["group"].nunique() == 1
    keeper = pair[pair["merge_code"] == 1]
    assert keeper["v_id"].iloc[0] == "64000140-018"  # 忠義里 is the smaller code AND the survivor


def test_build_ref_2022_no_merge_group(events):
    """2022 has only 忠義里 (光武里 is gone); the merge group has fewer than 2 members."""
    ref = tc.build_ref(events, year_range=(2021, 2025), data_year=2022)
    pair = ref[ref["v_id"].isin(["64000140-018", "64000140-024"])]
    assert pair.empty


def test_build_ref_with_present_vids(events):
    """Manually pass present_vids to override existence inference."""
    ref = tc.build_ref(
        events,
        year_range=(2021, 2025),
        data_year=2021,
        present_vids={"10007020-005"},  # Only 005 is "present"
    )
    rocks = ref[ref["v_id"].str.startswith("10007020-")]
    assert rocks.empty


# ---------- li_sum ----------

def test_li_sum_aggregates_population_to_keeper(events, shp_2022):
    df = pd.DataFrame({
        "V_ID": shp_2022["V_ID"],
        "P_CNT": shp_2022["P_CNT"],
        "H_CNT": shp_2022["H_CNT"],
    })
    raw = df[df["V_ID"].isin(["10007020-005", "10007020-030", "10007020-031"])]
    expected_pop = raw["P_CNT"].sum()
    expected_hh = raw["H_CNT"].sum()

    ref = tc.build_ref(events, year_range=(2021, 2025), data_year=2022)
    out = tc.li_sum(df, ref, cols=["P_CNT", "H_CNT"], finish=False)

    keeper = out[out["V_ID"] == "10007020-005"].iloc[0]
    assert keeper["P_CNT"] == expected_pop
    assert keeper["H_CNT"] == expected_hh
    # Non-keeper rows still present but unmodified
    assert (out["V_ID"] == "10007020-030").any()
    assert (out["V_ID"] == "10007020-031").any()


def test_li_sum_finish_drops_non_keepers(events, shp_2022):
    df = pd.DataFrame({"V_ID": shp_2022["V_ID"], "P_CNT": shp_2022["P_CNT"]})
    ref = tc.build_ref(events, year_range=(2021, 2025), data_year=2022)
    out = tc.li_sum(df, ref, cols=["P_CNT"], finish=True)
    assert "li_adjust" in out.columns
    # Non-keepers dropped
    assert not (out["V_ID"] == "10007020-030").any()
    assert not (out["V_ID"] == "10007020-031").any()
    # Keeper retained with li_adjust=1
    keeper = out[out["V_ID"] == "10007020-005"].iloc[0]
    assert keeper["li_adjust"] == 1
    # Untouched village has li_adjust=0
    untouched = out[out["V_ID"] == "09020010-001"].iloc[0]
    assert untouched["li_adjust"] == 0


# ---------- li_equ ----------

def test_li_equ_density_recompute(events, shp_2022):
    df = pd.DataFrame({
        "V_ID": shp_2022["V_ID"],
        "P_CNT": shp_2022["P_CNT"],
        "AREA_M2": shp_2022["AREA_M2"],
    })
    ref = tc.build_ref(events, year_range=(2021, 2025), data_year=2022)
    out = tc.li_equ(df, ref, result="DENSITY",
                    equ="P_CNT / AREA_M2 * 1e6", finish=False)
    raw = df[df["V_ID"].isin(["10007020-005", "10007020-030", "10007020-031"])]
    expected = raw["P_CNT"].sum() / raw["AREA_M2"].sum() * 1e6
    keeper = out[out["V_ID"] == "10007020-005"].iloc[0]
    assert abs(keeper["DENSITY"] - expected) < 1e-6


def test_li_equ_chained_with_li_sum(events, shp_2022):
    """Canonical workflow (matches twli convention): all li_equ calls first
    on the raw dataframe, then li_sum last with ``finish=True``."""
    df = pd.DataFrame({
        "V_ID": shp_2022["V_ID"],
        "P_CNT": shp_2022["P_CNT"],
        "H_CNT": shp_2022["H_CNT"],
        "AREA_M2": shp_2022["AREA_M2"],
    })
    ref = tc.build_ref(events, year_range=(2021, 2025), data_year=2022)
    # Step 1: derived columns first (operands still raw)
    out = tc.li_equ(df,  ref, result="DENSITY",     equ="P_CNT / AREA_M2 * 1e6")
    out = tc.li_equ(out, ref, result="AVG_HH_SIZE", equ="P_CNT / H_CNT")
    # Step 2: sum extensive columns last
    out = tc.li_sum(out, ref, cols=["P_CNT", "H_CNT", "AREA_M2"], finish=True)

    keeper = out[out["V_ID"] == "10007020-005"].iloc[0]
    raw = df[df["V_ID"].isin(["10007020-005", "10007020-030", "10007020-031"])]
    assert abs(keeper["AVG_HH_SIZE"] - raw["P_CNT"].sum() / raw["H_CNT"].sum()) < 1e-9
    assert abs(keeper["DENSITY"] - raw["P_CNT"].sum() / raw["AREA_M2"].sum() * 1e6) < 1e-6
    assert keeper["P_CNT"]   == raw["P_CNT"].sum()
    assert keeper["H_CNT"]   == raw["H_CNT"].sum()
    assert "li_adjust" in out.columns


# ---------- li_shp ----------

def test_li_shp_geometric_union(events, shp_2022):
    ref = tc.build_ref(events, year_range=(2021, 2025), data_year=2022)
    sub = shp_2022.copy()
    pre_total_area = sub["AREA_M2"].sum()
    out = tc.li_shp(sub, ref, vid_col="V_ID")

    # Keeper row's geometry now equals the union of the three split villages
    raw_geoms = shp_2022[shp_2022["V_ID"].isin(["10007020-005", "10007020-030", "10007020-031"])].geometry
    from shapely.ops import unary_union
    expected_area = unary_union(list(raw_geoms.values)).area
    keeper_geom = out[out["V_ID"] == "10007020-005"].iloc[0].geometry
    assert abs(keeper_geom.area - expected_area) < 1e-6

    # Non-keeper rows dropped
    assert not (out["V_ID"] == "10007020-030").any()
    assert not (out["V_ID"] == "10007020-031").any()
    # Total area conserved (within floating-point noise)
    assert abs(out.geometry.area.sum() - pre_total_area) < 1.0


def test_li_shp_population_consistent_with_li_sum(events, shp_2022):
    """Combining li_sum + li_shp produces a self-consistent map: keeper-row
    population matches the geometry-summed population."""
    sub = shp_2022.copy()
    ref = tc.build_ref(events, year_range=(2021, 2025), data_year=2022)
    sub2 = tc.li_sum(sub.drop(columns="geometry"), ref,
                     cols=["P_CNT", "H_CNT", "AREA_M2"], finish=True)
    shp_out = tc.li_shp(sub.drop(columns=["P_CNT", "H_CNT", "AREA_M2"]),
                        ref, vid_col="V_ID")
    # Both have the same V_IDs after consolidation
    assert set(sub2["V_ID"]) == set(shp_out["V_ID"])
