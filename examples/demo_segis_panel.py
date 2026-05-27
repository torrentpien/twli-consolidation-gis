"""Demo: 用 SEGIS 行政部・人口統計（村里級，109-113）跑 SAU panel。

這是 SEGIS 多來源整併的最小可動範例（Phase B1），驗證 ingest_segis →
twli_consolidate 的整套流程通暢。

執行：
    python examples/demo_segis_panel.py
輸出：
    examples/output/demo_segis_population_109_113.csv

驗證項目（執行時印出）：
1) 每年原始 V_ID 數 vs SAU 列數
2) 全國總人口 raw vs SAU 跨年 diff
3) 鹿港頂厝里 SAU 案例 (拆分前後 members 正確)
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


def main() -> None:
    topics = list_topics()
    pop_dir = topics["行政部"]["行政區人口統計"]

    df = ingest_topic(pop_dir)
    years = sorted(df["year"].unique().tolist())
    print(f"來源：行政部・人口統計，年度範圍 {years[0]}–{years[-1]}")
    print(f"原始 long 資料：{len(df):,} 列  ({len(df) / len(years):,.0f}/年)")

    # 整併
    cw = tc.load_crosswalk(ROOT / "crosswalk" / "village_changes.yaml")
    lineage = tc.build_lineage(cw, year_range=(years[0], years[-1]))

    out = tc.consolidate_panel(
        df,
        vid_col="V_ID",
        year_col="year",
        vars_spec={
            "H_CNT": "sum",
            "P_CNT": "sum",
            "M_CNT": "sum",
            "F_CNT": "sum",
        },
        lineage=lineage,
        extra_group_cols=["COUNTY", "TOWN", "VILLAGE"],
        keep_member_list=True,
    )
    print(f"整併後 panel：{len(out):,} 列  (每 SAU × year 一列)")

    out_path = ROOT / "examples" / "output" / "demo_segis_population_109_113.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, encoding="utf-8-sig", index=False)
    print(f"\n寫入 {out_path.relative_to(ROOT)}")

    # ---- 驗證 1: 每年原始 V_ID 數 vs SAU 列數 ----
    print("\n=== 每年村里數比對 ===")
    print(f"{'year':>6}  {'raw_VID':>8}  {'SAU_rows':>9}  "
          f"{'shrink':>7}  {'expected':>9}  ok")
    for y in years:
        raw = df[df["year"] == y]["V_ID"].nunique()
        sau_rows = (out["year"] == y).sum()
        raw_set = set(df[df["year"] == y]["V_ID"])
        expected = len({lineage.sau_of(v) for v in raw_set})
        ok = "✓" if sau_rows == expected else "✗"
        print(f"{y:>6}  {raw:>8}  {sau_rows:>9}  {raw - sau_rows:>7}  "
              f"{expected:>9}  {ok}")

    # ---- 驗證 2: 全國總人口 ----
    print("\n=== 全國總人口 raw vs SAU ===")
    for y in years:
        raw = df.loc[df["year"] == y, "P_CNT"].sum()
        sau = out.loc[out["year"] == y, "P_CNT"].sum()
        flag = "✓" if raw == sau else f"✗ diff={raw - sau}"
        print(f"  {y}: raw={raw:>12,}  sau={sau:>12,}  {flag}")

    # ---- 驗證 3: 鹿港頂厝里 SAU members ----
    print("\n=== 鹿港頂厝里 SAU 跨年 members ===")
    target = {"10007020-005", "10007020-030", "10007020-031"}
    case = out[out["members"].apply(lambda ms: bool(set(ms) & target))]
    cols = ["year", "VILLAGE", "P_CNT", "H_CNT", "members"]
    print(case[cols].sort_values("year").to_string(index=False))


if __name__ == "__main__":
    main()
