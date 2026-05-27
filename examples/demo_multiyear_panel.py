"""Demo: 用 107-113 (2018-2024) 民國年人口統計 csv 整成 7 年 SAU panel.

來源混用：
- data_population/107-108 兩年（SEGIS 未涵蓋的早期）
- SEGIS按資料類型分/行政部/行政區人口統計/109-113 五年（主來源）

涵蓋整併事件：
- 107 → 108 (大整併: 68 merge, 20 split, 20 redistribute)
- 110 → 111 (彰化鹿港鎮頂厝里 1→3 split 等)
- 111 → 112, 112 → 113 (邊界調整)
- 113 → 114 (零異動)

執行：
    python examples/demo_multiyear_panel.py
輸出：
    examples/output/demo_panel_P_CNT_2018_2024.csv
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))

import pandas as pd  # noqa: E402

import twli_consolidate as tc  # noqa: E402

from scripts.ingest_segis import ingest_topic, list_topics, read_csv  # noqa: E402


ROC_TO_AD = lambda roc: roc + 1911


def read_local_pop_csv(path: Path) -> pd.DataFrame:
    """讀 data_population/ 內 107、108 兩年 csv（已 UTF-8 化）."""
    m = re.match(r"(\d+)年12月行政區人口統計_村里\.csv$", path.name)
    if not m:
        raise ValueError(f"unexpected filename: {path.name}")
    year_ad = ROC_TO_AD(int(m.group(1)))
    df = pd.read_csv(path, encoding="utf-8", skiprows=[1], dtype={"V_ID": str})
    df.columns = [c.strip() for c in df.columns]
    df["year"] = year_ad
    return df


def main() -> None:
    # Source 1: data_population/107-108
    data_dir = ROOT / "data_population"
    local_csvs = sorted(data_dir.glob("*年12月行政區人口統計_村里.csv"))
    local_dfs = [read_local_pop_csv(p) for p in local_csvs]
    print(f"data_population/: {len(local_csvs)} 檔，年份 "
          f"{[df['year'].iloc[0] for df in local_dfs]}")

    # Source 2: SEGIS/行政部/行政區人口統計 109-113
    pop_topic = list_topics()["行政部"]["行政區人口統計"]
    segis_df = ingest_topic(pop_topic)
    print(f"SEGIS 人口統計: {len(segis_df):,} 列，年份 "
          f"{sorted(segis_df['year'].unique().tolist())}")

    # 合併兩來源
    df = pd.concat(local_dfs + [segis_df], ignore_index=True)
    df = df[
        ["V_ID", "year", "COUNTY", "TOWN", "VILLAGE",
         "P_CNT", "H_CNT", "M_CNT", "F_CNT"]
    ]
    years = sorted(df["year"].unique().tolist())
    print(f"\n合併後 long 資料：{len(df):,} 列，年度範圍 {years[0]}–{years[-1]}")

    # 整併
    cw = tc.load_crosswalk(ROOT / "crosswalk" / "village_changes.yaml")
    lineage = tc.build_lineage(cw, year_range=(years[0], years[-1]))

    out = tc.consolidate_panel(
        df,
        vid_col="V_ID",
        year_col="year",
        vars_spec={
            "P_CNT": "sum", "H_CNT": "sum",
            "M_CNT": "sum", "F_CNT": "sum",
        },
        lineage=lineage,
        extra_group_cols=["COUNTY", "TOWN", "VILLAGE"],
        keep_member_list=True,
    )
    print(f"整併後 panel：{len(out):,} 列  ({len(out) // len(years)} SAU × {len(years)} 年)")

    out_path = ROOT / "examples" / "output" / "demo_panel_P_CNT_2018_2024.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, encoding="utf-8-sig", index=False)
    print(f"\n寫入 {out_path.relative_to(ROOT)}")

    # 鹿港鎮頂厝里 SAU 跨 7 年
    members = {"10007020-005", "10007020-030", "10007020-031"}
    print("\n=== 鹿港鎮頂厝里 SAU 跨年 P_CNT ===")
    sau_rows = out[out["members"].apply(lambda ms: bool(set(ms) & members))]
    show = sau_rows[["year", "VILLAGE", "P_CNT", "H_CNT", "members"]].sort_values("year")
    print(show.to_string(index=False))

    # 健全性
    print("\n=== 健全性檢查（全國總人口）===")
    print(f"{'year':>6} {'raw_P_CNT':>14} {'sau_P_CNT':>14} {'diff':>6}")
    for y in years:
        raw = df.loc[df["year"] == y, "P_CNT"].sum()
        sau = out.loc[out["year"] == y, "P_CNT"].sum()
        flag = "✓" if raw == sau else "✗"
        print(f"{y:>6} {raw:>14,} {sau:>14,} {raw - sau:>6} {flag}")


if __name__ == "__main__":
    main()
