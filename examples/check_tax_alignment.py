"""系統性檢查財政部資料與行政部、教育部的對齊狀況.

檢查維度：
A. 時間覆蓋：年度範圍差異
B. V_ID 集合差異（每年逐年比對）
C. SAU 集合差異（整併後）
D. 寬表 NaN 來源分析（NaN 是因為「年度沒資料」、「V_ID 在財政部缺漏」、
   還是「整併但分位數欄位 keep_if_unique」？）
E. V_ID 重複狀況（財政部已知有 2022/2023 重複）
F. 鹿港頂厝里 SAU 跨年觀察

執行：
    python examples/check_tax_alignment.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))

import pandas as pd  # noqa: E402

import twli_consolidate as tc  # noqa: E402

from scripts.ingest_segis import ingest_topic, list_topics  # noqa: E402
from scripts.vars_spec import INGEST_SPECS, topic_key  # noqa: E402


def main() -> None:
    topics = list_topics()

    # ---- 載入三來源 raw + panel ----
    pop_raw = ingest_topic(topics["行政部"]["行政區人口統計"])
    edu_raw = ingest_topic(topics["教育部"]["行政區15歲以上人口教育程度統計"])
    tax_raw = ingest_topic(topics["財政部"]["綜合所得稅所得總額申報統計"])

    yrs_pop = sorted(pop_raw["year"].unique())
    yrs_edu = sorted(edu_raw["year"].unique())
    yrs_tax = sorted(tax_raw["year"].unique())

    cw = tc.load_crosswalk(ROOT / "crosswalk" / "village_changes.yaml")
    # 用人口統計年份建 lineage（最寬範圍）
    lineage = tc.build_lineage(cw, year_range=(min(yrs_pop), max(yrs_pop)))

    pop_panel = tc.consolidate_panel(
        pop_raw, vid_col="V_ID", year_col="year",
        vars_spec=INGEST_SPECS[topic_key("行政部", "行政區人口統計")],
        lineage=lineage, keep_member_list=True,
    )
    tax_panel = tc.consolidate_panel(
        tax_raw, vid_col="V_ID", year_col="year",
        vars_spec=INGEST_SPECS[topic_key("財政部", "綜合所得稅所得總額申報統計")],
        lineage=lineage, keep_member_list=True,
    )

    # ============================================================
    # A. 時間覆蓋
    # ============================================================
    print("=" * 72)
    print("A. 時間覆蓋（年度範圍）")
    print("=" * 72)
    print(f"  行政部・人口統計:  {yrs_pop[0]}–{yrs_pop[-1]}  ({len(yrs_pop)} 年)  "
          f"{[int(y) for y in yrs_pop]}")
    print(f"  教育部・教育程度:  {yrs_edu[0]}–{yrs_edu[-1]}  ({len(yrs_edu)} 年)  "
          f"{[int(y) for y in yrs_edu]}")
    print(f"  財政部・所得稅:    {yrs_tax[0]}–{yrs_tax[-1]}  ({len(yrs_tax)} 年)  "
          f"{[int(y) for y in yrs_tax]}")

    only_pop = sorted(set(yrs_pop) - set(yrs_tax))
    only_tax = sorted(set(yrs_tax) - set(yrs_pop))
    common = sorted(set(yrs_pop) & set(yrs_tax))
    print(f"\n  ✗ 行政部有、財政部沒: {only_pop}")
    print(f"  ✗ 財政部有、行政部沒: {only_tax}")
    print(f"  ✓ 兩者共同年度: {common}  ({len(common)} 年)")

    # ============================================================
    # B. V_ID 集合差異（每年）
    # ============================================================
    print()
    print("=" * 72)
    print("B. V_ID 集合差異（財政部 vs 行政部・人口統計）")
    print("=" * 72)
    print(f"{'year':>6}  {'pop_VID':>8}  {'tax_VID':>8}  "
          f"{'only_pop':>9}  {'only_tax':>9}  {'common':>8}")
    for y in common:
        pop_v = set(pop_raw.loc[pop_raw["year"] == y, "V_ID"])
        tax_v = set(tax_raw.loc[tax_raw["year"] == y, "V_ID"])
        only_p = pop_v - tax_v
        only_t = tax_v - pop_v
        com = pop_v & tax_v
        print(f"{y:>6}  {len(pop_v):>8}  {len(tax_v):>8}  "
              f"{len(only_p):>9}  {len(only_t):>9}  {len(com):>8}")

    # 取一年看詳細 V_ID 差
    print("\n  範例：2020 年只在行政部、只在財政部的 V_ID（各取前 5）")
    pop_v_2020 = set(pop_raw.loc[pop_raw["year"] == 2020, "V_ID"])
    tax_v_2020 = set(tax_raw.loc[tax_raw["year"] == 2020, "V_ID"])
    only_p_2020 = sorted(pop_v_2020 - tax_v_2020)[:5]
    only_t_2020 = sorted(tax_v_2020 - pop_v_2020)[:5]
    print(f"    only 行政部: {only_p_2020}")
    print(f"    only 財政部: {only_t_2020}")

    # ============================================================
    # C. SAU 集合差異（整併後）
    # ============================================================
    print()
    print("=" * 72)
    print("C. SAU 集合差異（整併後 panel）")
    print("=" * 72)
    print(f"{'year':>6}  {'pop_SAU':>8}  {'tax_SAU':>8}  "
          f"{'only_pop':>9}  {'only_tax':>9}")
    for y in common:
        pop_s = set(pop_panel.loc[pop_panel["year"] == y, "sau_id"])
        tax_s = set(tax_panel.loc[tax_panel["year"] == y, "sau_id"])
        print(f"{y:>6}  {len(pop_s):>8}  {len(tax_s):>8}  "
              f"{len(pop_s - tax_s):>9}  {len(tax_s - pop_s):>9}")

    # ============================================================
    # D. 寬表 NaN 來源分析
    # ============================================================
    print()
    print("=" * 72)
    print("D. 寬表 NaN 來源分析（以 FLD01 為例，非 keep_if_unique 欄位）")
    print("=" * 72)

    # 模擬跨來源寬表
    pop_keys = pop_panel[["sau_id", "year"]].copy()
    tax_sub = tax_panel[["sau_id", "year", "FLD01"]]
    wide = pop_keys.merge(tax_sub, on=["sau_id", "year"], how="left")

    print(f"{'year':>6}  {'pop_SAU':>8}  {'NaN_FLD01':>10}  原因分類")
    for y in yrs_pop:
        wide_y = wide[wide["year"] == y]
        nan_count = int(wide_y["FLD01"].isna().sum())
        if y not in yrs_tax:
            cause = f"財政部該年無資料（{nan_count} 個 SAU 全 NaN）"
        else:
            cause = f"財政部該年有 csv 但部分 SAU 缺資料"
        print(f"{y:>6}  {len(wide_y):>8}  {nan_count:>10}  {cause}")

    # ============================================================
    # E. V_ID 重複狀況（財政部）
    # ============================================================
    print()
    print("=" * 72)
    print("E. 財政部 V_ID 重複狀況")
    print("=" * 72)
    print(f"{'year':>6}  {'rows':>6}  {'unique_VID':>10}  {'重複數':>6}  範例")
    for y in yrs_tax:
        yr = tax_raw[tax_raw["year"] == y]
        rows = len(yr)
        uniq = yr["V_ID"].nunique()
        dups = rows - uniq
        sample = []
        if dups > 0:
            dup_vids = yr.groupby("V_ID").size()
            sample = sorted(dup_vids[dup_vids > 1].index)[:2]
        flag = "✓" if dups == 0 else f"範例 {sample}"
        print(f"{y:>6}  {rows:>6}  {uniq:>10}  {dups:>6}  {flag}")

    # ============================================================
    # E2. Raw csv 內非標準 V_ID 與彙整列檢查
    # ============================================================
    import re
    print()
    print("=" * 72)
    print("E2. 財政部 raw csv 非標準 V_ID 與彙整列")
    print("=" * 72)
    pattern = re.compile(r"^\d{8}-\d{3}$")
    for y in yrs_tax:
        yr = tax_raw[tax_raw["year"] == y]
        bad_vid = yr[~yr["V_ID"].str.match(pattern)]
        agg_village = yr[yr["VILLAGE"].isin(["其他", "合計", "小計", "總計"])]
        if len(bad_vid) > 0 or len(agg_village) > 0:
            print(f"\n  {y}:")
            if len(bad_vid):
                samples = bad_vid[["V_ID", "VILLAGE"]].head(3).to_dict("records")
                print(f"    非標準 V_ID: {len(bad_vid)} 列，範例 {samples}")
            if len(agg_village):
                print(f"    VILLAGE 為其他/合計: {len(agg_village)} 列")

    # ============================================================
    # G. V_ID 不對齊集中縣市分析（已知大量不對齊年度）
    # ============================================================
    print()
    print("=" * 72)
    print("G. V_ID 不對齊集中縣市（大差異年度深入）")
    print("=" * 72)
    suspect_years = [2014, 2017, 2019, 2021, 2023]
    for y in suspect_years:
        if y not in common: continue
        pop_v = set(pop_raw.loc[pop_raw["year"] == y, "V_ID"])
        tax_v = set(tax_raw.loc[tax_raw["year"] == y, "V_ID"])
        only_p = pop_v - tax_v
        only_t = tax_v - pop_v
        if not only_p and not only_t: continue
        print(f"\n  [{y}] only 行政部 {len(only_p)}, only 財政部 {len(only_t)}")
        if only_p:
            cty = pop_raw[pop_raw["V_ID"].isin(only_p) & (pop_raw["year"] == y)]["COUNTY"].value_counts().head(3)
            print(f"    only 行政部 集中縣市: {dict(cty)}")
        if only_t:
            cty = tax_raw[tax_raw["V_ID"].isin(only_t) & (tax_raw["year"] == y)]["COUNTY"].value_counts().head(3)
            print(f"    only 財政部 集中縣市: {dict(cty)}")

    # ============================================================
    # F. 鹿港頂厝里 SAU 跨年觀察（跨來源）
    # ============================================================
    print()
    print("=" * 72)
    print("F. 鹿港頂厝里 SAU 跨年（pop vs tax）")
    print("=" * 72)
    members = {"10007020-005", "10007020-030", "10007020-031"}
    lukang_sau = lineage.sau_of("10007020-005")
    pop_lk = pop_panel[pop_panel["sau_id"] == lukang_sau][["year", "P_CNT", "members"]]
    tax_lk = tax_panel[tax_panel["sau_id"] == lukang_sau][["year", "FLD01", "FLD02", "FLD04", "members"]]

    merged = pop_lk.merge(
        tax_lk, on="year", how="outer", suffixes=("_pop", "_tax")
    ).sort_values("year")
    print(merged.to_string(index=False))


if __name__ == "__main__":
    main()
