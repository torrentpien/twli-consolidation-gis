"""Demo: 用 107-113 (2018-2024) 民國年人口統計 csv 整成 7 年 SAU panel.

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
sys.path.insert(0, str(ROOT / "python"))

import pandas as pd  # noqa: E402

import twli_consolidate as tc  # noqa: E402


ROC_TO_AD = lambda roc: roc + 1911


def read_pop_csv(path: Path) -> pd.DataFrame:
    """讀社經平台「<民國年>年12月行政區人口統計_村里.csv」(已 UTF-8 化)."""
    m = re.match(r"(\d+)年12月行政區人口統計_村里\.csv$", path.name)
    if not m:
        raise ValueError(f"unexpected filename: {path.name}")
    year_ad = ROC_TO_AD(int(m.group(1)))
    df = pd.read_csv(path, encoding="utf-8", skiprows=[1], dtype={"V_ID": str})
    df.columns = [c.strip() for c in df.columns]
    df["year"] = year_ad
    return df


def main() -> None:
    data_dir = ROOT / "data_population"
    csvs = sorted(data_dir.glob("*年12月行政區人口統計_村里.csv"))
    print(f"找到 {len(csvs)} 個年度 csv")

    dfs = [read_pop_csv(p) for p in csvs]
    years = sorted({df["year"].iloc[0] for df in dfs})
    print(f"年度範圍：{min(years)}–{max(years)}")

    df = pd.concat(dfs, ignore_index=True)
    df = df[
        ["V_ID", "year", "COUNTY", "TOWN", "VILLAGE",
         "P_CNT", "H_CNT", "M_CNT", "F_CNT"]
    ]
    print(f"原始 long 資料：{len(df):,} 列")

    # 建立 panel 範圍的 lineage
    cw = tc.load_crosswalk(ROOT / "crosswalk" / "village_changes.yaml")
    lineage = tc.build_lineage(cw, year_range=(min(years), max(years)))

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
    print(f"整併後 panel：{len(out):,} 列  "
          f"({len(out)//len(years)} SAU × {len(years)} 年, 約)")

    out_path = (ROOT / "examples" / "output" /
                f"demo_panel_P_CNT_{min(years)}_{max(years)}.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, encoding="utf-8-sig", index=False)
    print(f"\n寫入 {out_path.relative_to(ROOT)}")

    # === 聚焦案例：鹿港鎮頂厝里 SAU 跨 7 年 ===
    members = {"10007020-005", "10007020-030", "10007020-031"}
    print("\n=== 鹿港鎮頂厝里 SAU 跨年 P_CNT ===")
    sau_rows = out[out["members"].apply(lambda ms: bool(set(ms) & members))]
    show = sau_rows[["year", "VILLAGE", "P_CNT", "H_CNT", "members"]].sort_values("year")
    print(show.to_string(index=False))

    # 健全性：每年原始 vs 整併後總和
    print("\n=== 健全性檢查（全國總人口）===")
    print(f"{'year':>6} {'raw_P_CNT':>14} {'sau_P_CNT':>14} {'diff':>6}")
    for y in years:
        raw = df.loc[df["year"] == y, "P_CNT"].sum()
        sau = out.loc[out["year"] == y, "P_CNT"].sum()
        flag = "✓" if raw == sau else "✗"
        print(f"{y:>6} {raw:>14,} {sau:>14,} {raw - sau:>6} {flag}")


if __name__ == "__main__":
    main()
