"""Phase 5: 跨來源 wide panel — 把行政部、教育部、財政部主題在 (sau_id, year) join 成寬表.

涵蓋主題（5 個）：
1. 行政部・人口統計           4 欄 (H_CNT, P_CNT, M_CNT, F_CNT)
2. 行政部・三段年齡組         9 欄 (A0A14/A15A64/A65UP × 總/M/F)
3. 行政部・原住民人口統計     10 欄 (O_CNT, O1, O2, NON_O × 總/M/F)
4. 教育部・15+ 教育程度       9 欄 (E1314 博士 ~ E04 不識字)
5. 財政部・所得稅             8 欄 (FLD01-08，含 keep_if_unique)

年度範圍策略：
- 行政部、教育部都涵蓋 109-113 (5 年)
- 財政部只到 111 (3 年)
- 採取「聯集」：panel 涵蓋 109-113 五年，財政部欄位在 112-113 為 NaN

執行：
    python examples/demo_multi_source_panel.py
輸出：
    examples/output/demo_multi_source_panel_109_113.csv
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


# 各主題的整合 metadata
TOPICS = [
    ("行政部", "行政區人口統計", "pop"),
    ("行政部", "行政區三段年齡組性別人口統計", "age3"),
    ("行政部", "行政區原住民人口統計", "ip"),
    ("教育部", "行政區15歲以上人口教育程度統計", "edu"),
    ("財政部", "綜合所得稅所得總額申報統計", "tax"),
]


def consolidate_topic(folder: Path, ministry: str, topic: str,
                      lineage: tc.Lineage) -> pd.DataFrame:
    """讀單一主題 → 整併成 SAU panel."""
    df = ingest_topic(folder)
    spec = INGEST_SPECS[topic_key(ministry, topic)]
    out = tc.consolidate_panel(
        df,
        vid_col="V_ID",
        year_col="year",
        vars_spec=spec,
        lineage=lineage,
        extra_group_cols=["COUNTY", "TOWN", "VILLAGE"],
        keep_member_list=True,
    )
    return out


def main() -> None:
    topics_tree = list_topics()

    # 用 109-113 範圍建一次 lineage 共用
    cw = tc.load_crosswalk(ROOT / "crosswalk" / "village_changes.yaml")
    lineage = tc.build_lineage(cw, year_range=(2020, 2024))

    panels: dict[str, pd.DataFrame] = {}
    for ministry, topic, alias in TOPICS:
        folder = topics_tree[ministry][topic]
        out = consolidate_topic(folder, ministry, topic, lineage)
        panels[alias] = out
        yrs = sorted(out["year"].unique().tolist())
        print(f"[{alias:<5}] {ministry}・{topic}  "
              f"年份 {yrs[0]}–{yrs[-1]} ({len(yrs)} 年)，"
              f"{len(out):,} 列")

    # ---- Join 策略 ----
    # 主軸：行政部・人口統計（最完整、涵蓋 109-113 全年度）
    # 其他主題用 LEFT JOIN 接上去
    base = panels["pop"].copy()
    base_keys = ["sau_id", "year"]
    base = base.rename(columns={
        "COUNTY": "COUNTY", "TOWN": "TOWN", "VILLAGE": "VILLAGE",
        "members": "members_pop",
    })

    def drop_meta(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
        """從子表丟掉 COUNTY/TOWN/VILLAGE，重新命名 members."""
        drop = [c for c in ("COUNTY", "TOWN", "VILLAGE") if c in df.columns]
        df = df.drop(columns=drop)
        if "members" in df.columns:
            df = df.rename(columns={"members": f"members_{prefix}"})
        return df

    wide = base
    for ministry, topic, alias in TOPICS:
        if alias == "pop":
            continue
        sub = drop_meta(panels[alias], alias)
        wide = wide.merge(sub, on=base_keys, how="left")

    # 報告 join 後狀況
    print(f"\n[join 後] 列數: {len(wide):,}  欄數: {len(wide.columns)}")
    print(f"[join 後] 年份分佈:")
    print(wide["year"].value_counts().sort_index().to_string())

    # ---- 驗證 ----
    # 1. 主軸 (pop) 跨年 SAU 數
    print("\n=== 驗證 1: 主軸 (人口統計) SAU 跨年覆蓋 ===")
    for y in sorted(wide["year"].unique()):
        n = (wide["year"] == y).sum()
        print(f"  {y}: {n:,} 列")

    # 2. 各主題覆蓋率（NaN 比例）
    print("\n=== 驗證 2: 各主題在 wide panel 內覆蓋率 ===")
    print(f"{'topic':<6}  {'sample col':<12}  {'年份':>6}  {'NaN 比例':>10}")
    sample_cols = {"age3": "A0A14_CNT", "ip": "O_CNT", "edu": "E1314_CNT",
                   "tax": "FLD01"}
    for alias, col in sample_cols.items():
        for y in sorted(wide["year"].unique()):
            yr = wide[wide["year"] == y]
            nan_pct = yr[col].isna().mean() * 100
            print(f"{alias:<6}  {col:<12}  {y:>6}  {nan_pct:>9.2f}%")

    # 3. 跨來源加總交叉驗證 (raw csv 已知會差，這裡 spot check 確認套件忠實傳遞)
    print("\n=== 驗證 3: 跨來源加總 spot check ===")
    print(f"{'year':>6}  {'P_CNT':>14}  {'A_total':>14}  {'O+NON_O':>14}")
    for y in sorted(wide["year"].unique()):
        yr = wide[wide["year"] == y]
        p = int(yr["P_CNT"].sum())
        a3 = int(yr[["A0A14_CNT", "A15A64_CNT", "A65UP_CNT"]].sum().sum())
        ip_sum = int(yr[["O_CNT", "NON_O_CNT"]].dropna().sum().sum())
        print(f"{y:>6}  {p:>14,}  {a3:>14,}  {ip_sum:>14,}")

    # 4. 鹿港頂厝里 SAU 跨年觀察（跨來源視角）
    print("\n=== 驗證 4: 鹿港頂厝里 SAU 跨年（跨來源視角）===")
    members = {"10007020-005", "10007020-030", "10007020-031"}
    rows = wide[wide["members_pop"].apply(lambda ms: bool(set(ms) & members))]
    cols = ["year", "VILLAGE", "P_CNT", "A15A64_CNT", "O_CNT",
            "E2122_CNT", "FLD02", "members_pop"]
    print(rows[cols].sort_values("year").to_string(index=False))

    # 輸出
    out_path = (ROOT / "examples" / "output" /
                "demo_multi_source_panel_109_113.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wide.to_csv(out_path, encoding="utf-8-sig", index=False)
    print(f"\n寫入 {out_path.relative_to(ROOT)}  "
          f"({len(wide):,} 列 × {len(wide.columns)} 欄)")


if __name__ == "__main__":
    main()
