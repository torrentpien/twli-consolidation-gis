"""Demo: 教育部「15 歲以上人口教育程度」5 年 SAU panel (109-113).

驗證項目：
1) 每年原始 V_ID 數 vs SAU 列數
2) 跨年 SAU 集合一致性
3) 教育程度 9 欄加總跨年合理（人口隨時間平穩變化）
4) 交叉驗證：教育部 9 欄加總 ≈ 行政部 15+ 歲人口
   （= 三段年齡組 A15A64_CNT + A65UP_CNT）

執行：
    python examples/demo_education_panel.py
輸出：
    examples/output/demo_segis_education_109_113.csv
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
    edu_dir = topics["教育部"]["行政區15歲以上人口教育程度統計"]
    edu_df = ingest_topic(edu_dir)
    years = sorted(edu_df["year"].unique().tolist())

    cw = tc.load_crosswalk(ROOT / "crosswalk" / "village_changes.yaml")
    lineage = tc.build_lineage(cw, year_range=(years[0], years[-1]))

    edu_spec_key = topic_key("教育部", "行政區15歲以上人口教育程度統計")
    spec = INGEST_SPECS[edu_spec_key]
    edu_cols = list(spec.keys())

    out = tc.consolidate_panel(
        edu_df,
        vid_col="V_ID",
        year_col="year",
        vars_spec=spec,
        lineage=lineage,
        extra_group_cols=["COUNTY", "TOWN", "VILLAGE"],
        keep_member_list=True,
    )
    print(f"教育部 panel: {len(out):,} 列 = "
          f"{len(out) // len(years)} SAU × {len(years)} 年 (109-113)")

    out_path = ROOT / "examples" / "output" / "demo_segis_education_109_113.csv"
    out.to_csv(out_path, encoding="utf-8-sig", index=False)
    print(f"寫入 {out_path.relative_to(ROOT)}")

    # ---- 驗證 1: 每年 V_ID vs SAU ----
    print("\n=== 每年村里數比對 ===")
    print(f"{'year':>6}  {'raw_VID':>8}  {'SAU_rows':>9}  shrink  ok")
    for y in years:
        raw = edu_df[edu_df["year"] == y]["V_ID"].nunique()
        sau_rows = (out["year"] == y).sum()
        raw_set = set(edu_df[edu_df["year"] == y]["V_ID"])
        expected = len({lineage.sau_of(v) for v in raw_set})
        ok = "✓" if sau_rows == expected else "✗"
        print(f"{y:>6}  {raw:>8}  {sau_rows:>9}  {raw - sau_rows:>6}  {ok}")

    # ---- 驗證 2: 跨年 SAU 集合 ----
    sau_per_year = {y: set(out[out["year"] == y]["sau_id"]) for y in years}
    base = sau_per_year[years[0]]
    print("\n=== 跨年 SAU 集合一致性 ===")
    for y in years[1:]:
        diff = sau_per_year[y] ^ base
        flag = "✓ 完全一致" if not diff else f"✗ 差 {len(diff)}"
        print(f"  {years[0]} vs {y}: {flag} ({len(base)} SAU)")

    # ---- 驗證 3: 9 欄加總跨年 ----
    print("\n=== 教育程度 9 欄加總跨年 ===")
    print(f"{'year':>6}  {'15+人口總計':>14}  各教育程度小計")
    edu_totals_by_year = {}
    for y in years:
        yr_out = out[out["year"] == y]
        sub = {c: int(yr_out[c].sum()) for c in edu_cols}
        total = sum(sub.values())
        edu_totals_by_year[y] = total
        print(f"{y:>6}  {total:>14,}")
        for c in edu_cols:
            print(f"          {c:>12} = {sub[c]:>10,}")

    # ---- 驗證 4: 交叉驗證 vs 行政部 15+ 人口 ----
    pop_age = topics["行政部"]["行政區三段年齡組性別人口統計"]
    age_df = ingest_topic(pop_age, years=years)
    age_df["age15up"] = age_df["A15A64_CNT"] + age_df["A65UP_CNT"]
    age_totals = age_df.groupby("year")["age15up"].sum()
    print("\n=== 交叉驗證：教育部 9 欄總和 vs 行政部 15+ 人口 ===")
    print(f"{'year':>6}  {'edu_total':>12}  {'age15up':>12}  diff       ratio")
    for y in years:
        edu = edu_totals_by_year[y]
        a15 = int(age_totals.loc[y])
        ratio = edu / a15 * 100
        print(f"{y:>6}  {edu:>12,}  {a15:>12,}  "
              f"{edu - a15:>+10,}  {ratio:>6.2f}%")


if __name__ == "__main__":
    main()
