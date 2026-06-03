"""Demo: 財政部「綜合所得稅所得總額申報統計」3 年 SAU panel (109-111).

財政部資料特殊性：
- FLD01 (納稅單位) / FLD02 (綜合所得總額) : 可 sum
- FLD03 (平均) : recompute = FLD02 / FLD01
- FLD04 (中位) / FLD05 (Q1) / FLD06 (Q3) / FLD07 (SD) / FLD08 (CV) :
  樣本級分位/變異統計量，無法從區級彙總精確重算。Q3 決議 (a)：
  受整併 SAU 標 NaN，未整併 SAU 保留原值 (新增 agg "keep_if_unique")。

驗證項目：
1) 每年原始 V_ID 數 vs SAU 列數
2) 跨年 SAU 集合一致性
3) FLD01/FLD02 加總跨年合理
4) FLD03 (平均) 重算 vs 原始 csv 平均比較
5) FLD04-08 keep_if_unique 行為：受整併 SAU NaN、未受整併 SAU 保留原值
6) 鹿港頂厝里 SAU 範例：拆分前單一 V_ID 保留 FLD04-08，拆分後標 NaN

執行：
    python examples/demo_tax_panel.py
輸出：
    examples/output/demo_segis_tax.csv
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
    tax_dir = topics["財政部"]["綜合所得稅所得總額申報統計"]
    tax_df = ingest_topic(tax_dir)
    years = sorted(tax_df["year"].unique().tolist())

    # ---- 資料品質檢查 (ingest 後) ----
    print("=== 資料品質檢查（ingest 後）===")
    for y in years:
        yr = tax_df[tax_df["year"] == y]
        n_dup = int((yr.groupby("V_ID").size() > 1).sum())
        n_dup_rows = int(yr.shape[0] - yr["V_ID"].nunique())
        n_aggvid = int(yr["V_ID"].str.endswith("-999").sum())  # 應該都 0
        print(f"  {y}: rows={len(yr):,}, "
              f"重複 V_ID={n_dup} ({n_dup_rows} 重複列), "
              f"-999 彙整列={n_aggvid}（已 drop）")
    print()


    cw = tc.load_crosswalk(ROOT / "crosswalk" / "village_changes.yaml")
    lineage = tc.build_lineage(cw, year_range=(years[0], years[-1]))

    tax_spec_key = topic_key("財政部", "綜合所得稅所得總額申報統計")
    spec = INGEST_SPECS[tax_spec_key]

    out = tc.consolidate_panel(
        tax_df,
        vid_col="V_ID",
        year_col="year",
        vars_spec=spec,
        lineage=lineage,
        extra_group_cols=["COUNTY", "TOWN", "VILLAGE"],
        keep_member_list=True,
    )
    print(f"財政部 panel: {len(out):,} 列 = "
          f"{len(out) // len(years)} SAU × {len(years)} 年 ({years[0]}-{years[-1]})")

    out_path = ROOT / "examples" / "output" / "demo_segis_tax.csv"
    out.to_csv(out_path, encoding="utf-8-sig", index=False)
    print(f"寫入 {out_path.relative_to(ROOT)}")

    # ---- 驗證 1: 每年 V_ID vs SAU ----
    print("\n=== 每年村里數比對 ===")
    print(f"{'year':>6}  {'raw_VID':>8}  {'SAU_rows':>9}  shrink  ok")
    for y in years:
        raw = tax_df[tax_df["year"] == y]["V_ID"].nunique()
        sau_rows = (out["year"] == y).sum()
        raw_set = set(tax_df[tax_df["year"] == y]["V_ID"])
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

    # ---- 驗證 3: FLD01/FLD02 加總跨年 ----
    print("\n=== FLD01 (納稅單位) / FLD02 (總額千元) 加總跨年 ===")
    print(f"{'year':>6}  {'FLD01_total':>14}  {'FLD02_total (千元)':>20}")
    for y in years:
        f1 = int(out.loc[out["year"] == y, "FLD01"].sum())
        f2 = int(out.loc[out["year"] == y, "FLD02"].sum())
        print(f"{y:>6}  {f1:>14,}  {f2:>20,}")

    # ---- 驗證 4: FLD03 (平均) 重算 vs raw csv 平均 ----
    print("\n=== FLD03 (平均) 重算驗證（未受整併 SAU）===")
    # 未受整併的 SAU (members 只有 1 個 V_ID)：FLD03 應等於原始 csv
    sample = out[(out["members"].apply(len) == 1) & (out["year"] == years[0])].iloc[0]
    sau_vid = sample["members"][0]
    raw_row = tax_df[(tax_df["V_ID"] == sau_vid) & (tax_df["year"] == years[0])].iloc[0]
    recomputed = sample["FLD03"]
    raw_avg = raw_row["FLD03"]
    print(f"  V_ID={sau_vid}, year={years[0]}")
    print(f"  raw FLD03 (csv 平均)     = {raw_avg:.2f}")
    print(f"  recomputed FLD02/FLD01    = {recomputed:.2f}")
    diff = abs(recomputed - raw_avg)
    print(f"  diff = {diff:.4f}  {'✓' if diff < 1.0 else '✗'} (微差來自原始 csv 平均的四捨五入)")

    # ---- 驗證 5: keep_if_unique 行為 ----
    # 預期 NaN 數 = (sau_id, year) 內 raw row count > 1 的 group 數
    # （含真實整併 + raw csv 重複 V_ID + raw csv 原本就 NaN 的 V_ID）
    print("\n=== keep_if_unique 行為（FLD04 中位數）===")
    tax_df_with_sau = tax_df.copy()
    tax_df_with_sau["sau_id"] = tax_df_with_sau["V_ID"].map(lineage.sau_of)
    for y in years:
        yr = out[out["year"] == y]
        nan_count = int(yr["FLD04"].isna().sum())

        # 真實整併 SAU：members 多於 1 個 V_ID
        consolidated = int(yr["members"].apply(lambda ms: len(ms) > 1).sum())

        # 預期 NaN = SAU 內 raw row > 1 + 1-member SAU 但 raw 該欄為 NaN 的數
        raw_yr = tax_df_with_sau[tax_df_with_sau["year"] == y]
        sau_rowcount = raw_yr.groupby("sau_id").size()
        multi_row_sau = int((sau_rowcount > 1).sum())
        # 1-row SAU 中 raw FLD04 為 NaN 的數
        single_row_saus = sau_rowcount[sau_rowcount == 1].index
        raw_single = raw_yr[raw_yr["sau_id"].isin(single_row_saus)]
        single_nan = int(raw_single["FLD04"].isna().sum())
        expected = multi_row_sau + single_nan

        flag = "✓" if nan_count == expected else "✗"
        print(f"  {y}: panel NaN={nan_count:>3}, 真實整併 SAU={consolidated:>3}, "
              f"raw 多列 SAU={multi_row_sau:>3} + single 內 NaN={single_nan:>2} = "
              f"預期 {expected:>3}  {flag}")

    # ---- 驗證 6: 鹿港頂厝里 SAU 跨年表現 ----
    print("\n=== 鹿港頂厝里 SAU 跨年 (FLD04 中位/FLD08 CV) ===")
    members_target = {"10007020-005", "10007020-030", "10007020-031"}
    sau_rows = out[out["members"].apply(lambda ms: bool(set(ms) & members_target))]
    cols = ["year", "VILLAGE", "FLD01", "FLD02", "FLD03", "FLD04", "FLD08", "members"]
    print(sau_rows[cols].sort_values("year").to_string(index=False))


if __name__ == "__main__":
    main()
