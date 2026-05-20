"""Demo: 用 110→111 整併紀錄把 2021/12 與 2022/12 的人口資料整成跨年 panel.

聚焦案例：彰化縣鹿港鎮頂厝里 (10007020-005)
- 2021 (民100/12): 只有頂厝里 1 個 V_ID
- 2022 (民111/12): 頂厝里 + 鹿和里 (030) + 鹿東里 (031)  ← 由 005 拆出 (1→3 split)

經 twli_consolidate 整併後，兩年都聚合為同一個 SAU，P_CNT 跨年連續、可分析。

執行：
    python examples/demo_population_panel.py
輸出：
    examples/output/demo_panel_P_CNT_2021_2022.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import pandas as pd  # noqa: E402

import twli_consolidate as tc  # noqa: E402


def read_pop_csv(path: Path, year: int) -> pd.DataFrame:
    """讀社經平台「行政區人口統計_村里.csv」(原檔 CP950/Big5，本 repo 已轉 UTF-8；第 2 列為中文 header)."""
    df = pd.read_csv(path, encoding="utf-8", skiprows=[1], dtype={"V_ID": str})
    df.columns = [c.strip() for c in df.columns]
    df["year"] = year
    return df


def main() -> None:
    data_dir = ROOT / "data_population"
    df_2021 = read_pop_csv(data_dir / "110年12月行政區人口統計_村里.csv", 2021)
    df_2022 = read_pop_csv(data_dir / "111年12月行政區人口統計_村里.csv", 2022)

    df = pd.concat([df_2021, df_2022], ignore_index=True)
    df = df[
        ["V_ID", "year", "COUNTY", "TOWN", "VILLAGE",
         "P_CNT", "H_CNT", "M_CNT", "F_CNT"]
    ]
    print(f"原始 long 資料：{len(df):,} 列  "
          f"(2021={len(df_2021):,}, 2022={len(df_2022):,})")

    # 載入整併紀錄、建構 2021–2022 範圍的 lineage
    cw = tc.load_crosswalk(ROOT / "crosswalk" / "village_changes.yaml")
    lineage = tc.build_lineage(cw, year_range=(2021, 2022))

    out = tc.consolidate_panel(
        df,
        vid_col="V_ID",
        year_col="year",
        vars_spec={
            "P_CNT": "sum",
            "H_CNT": "sum",
            "M_CNT": "sum",
            "F_CNT": "sum",
        },
        lineage=lineage,
        extra_group_cols=["COUNTY", "TOWN", "VILLAGE"],
        keep_member_list=True,
    )
    print(f"整併後 panel：{len(out):,} 列  (每個 SAU 每年 1 列)")

    out_path = ROOT / "examples" / "output" / "demo_panel_P_CNT_2021_2022.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, encoding="utf-8-sig", index=False)
    print(f"\n寫入 {out_path.relative_to(ROOT)}")

    # === 聚焦案例：鹿港鎮頂厝里 SAU ===
    members = {"10007020-005", "10007020-030", "10007020-031"}

    print("\n=== 鹿港鎮頂厝里 SAU 整併「前」===")
    src = df[df["V_ID"].isin(members)].sort_values(["year", "V_ID"])
    print(src.to_string(index=False))

    print("\n=== 鹿港鎮頂厝里 SAU 整併「後」===")
    sau_rows = out[out["members"].apply(lambda ms: bool(set(ms) & members))]
    print(sau_rows.sort_values("year").to_string(index=False))

    # 健全性：全國總人口跨年是否相等
    raw_2021 = df.loc[df["year"] == 2021, "P_CNT"].sum()
    raw_2022 = df.loc[df["year"] == 2022, "P_CNT"].sum()
    sau_2021 = out.loc[out["year"] == 2021, "P_CNT"].sum()
    sau_2022 = out.loc[out["year"] == 2022, "P_CNT"].sum()
    print("\n=== 健全性檢查（全國總人口）===")
    print(f"原始 2021={raw_2021:>12,}  整併後 2021={sau_2021:>12,}  "
          f"diff={raw_2021 - sau_2021}")
    print(f"原始 2022={raw_2022:>12,}  整併後 2022={sau_2022:>12,}  "
          f"diff={raw_2022 - sau_2022}")


if __name__ == "__main__":
    main()
