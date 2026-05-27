"""驗證整併後 panel 的村里數是否合理。

檢查項目：
1) 每年原始 V_ID 數 (csv 直接 count)
2) 每年 SAU panel 列數
3) 預期 SAU 列數 = 原始 V_ID 數 - 該年屬於同一 SAU 的「非 keeper」V_ID 數
4) 全國 P_CNT 跨年是否相等 (raw vs SAU)
5) 鹿港鎮頂厝里 SAU 跨 7 年 members 是否符合 YAML 紀錄
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

from scripts.ingest_segis import ingest_topic, list_topics  # noqa: E402


ROC_TO_AD = lambda roc: roc + 1911


def read_pop_csv(path: Path) -> pd.DataFrame:
    """讀 data_population/ 內 107、108 兩年 csv (UTF-8)."""
    m = re.match(r"(\d+)年12月行政區人口統計_村里\.csv$", path.name)
    year = ROC_TO_AD(int(m.group(1)))
    df = pd.read_csv(path, encoding="utf-8", skiprows=[1], dtype={"V_ID": str})
    df.columns = [c.strip() for c in df.columns]
    df["year"] = year
    return df


def main() -> None:
    # 來源 1: data_population/107-108
    data_dir = ROOT / "data_population"
    csvs = sorted(data_dir.glob("*年12月行政區人口統計_村里.csv"))
    dfs_local = [read_pop_csv(p) for p in csvs]
    # 來源 2: SEGIS/行政部/行政區人口統計 109-113
    segis_df = ingest_topic(list_topics()["行政部"]["行政區人口統計"])
    df = pd.concat(dfs_local + [segis_df], ignore_index=True)[
        ["V_ID", "year", "P_CNT"]
    ]
    years = sorted(df["year"].unique())

    cw = list(tc.load_crosswalk(ROOT / "crosswalk" / "village_changes.yaml"))
    lineage = tc.build_lineage(cw, year_range=(min(years), max(years)))

    out = tc.consolidate_panel(
        df, vid_col="V_ID", year_col="year",
        vars_spec={"P_CNT": "sum"},
        lineage=lineage,
        keep_member_list=True,
    )

    # ---- (1)(2)(3) 每年村里數對照 ----
    print("=== 每年村里數比對 ===")
    print(f"{'year':>6}  {'raw_VID':>8}  {'SAU_rows':>9}  "
          f"{'shrink':>7}  {'expected':>9}  {'ok'}")
    rows = []
    for y in years:
        raw_vids = df[df["year"] == y]["V_ID"].nunique()
        sau_rows = out[out["year"] == y].shape[0]

        # 預期：把該年所有原始 V_ID 對到 SAU，看有幾個 SAU
        raw_set = set(df[df["year"] == y]["V_ID"])
        sau_ids = {lineage.sau_of(v) for v in raw_set}
        expected = len(sau_ids)

        shrink = raw_vids - sau_rows
        ok = "✓" if sau_rows == expected else "✗"
        rows.append((y, raw_vids, sau_rows, shrink, expected, ok))
        print(f"{y:>6}  {raw_vids:>8}  {sau_rows:>9}  {shrink:>7}  "
              f"{expected:>9}  {ok}")

    # ---- (4) 全國總人口 ----
    print("\n=== 全國總人口 raw vs SAU ===")
    for y in years:
        raw = df[df["year"] == y]["P_CNT"].sum()
        sau = out[out["year"] == y]["P_CNT"].sum()
        flag = "✓" if raw == sau else f"✗ diff={raw-sau}"
        print(f"  {y}: raw={raw:,}  sau={sau:,}  {flag}")

    # ---- (5) 鹿港鎮頂厝里 SAU 案例 ----
    print("\n=== 鹿港鎮頂厝里 SAU 跨年 members ===")
    members_target = {"10007020-005", "10007020-030", "10007020-031"}
    case = out[out["members"].apply(
        lambda ms: bool(set(ms) & members_target)
    )].sort_values("year")
    # 預期：2018-2021 (拆分前) members 只含 005；2022-2024 含三個
    print(case[["year", "members", "P_CNT"]].to_string(index=False))

    expected_pre = {"10007020-005"}
    expected_post = {"10007020-005", "10007020-030", "10007020-031"}
    all_ok = True
    for _, r in case.iterrows():
        members_set = set(r["members"])
        if r["year"] <= 2021:
            ok = members_set == expected_pre
        else:
            ok = members_set == expected_post
        if not ok:
            print(f"  ✗ year={r['year']} members={members_set}")
            all_ok = False
    print("案例驗證:", "✓ 全部符合" if all_ok else "✗ 有不符")

    # ---- (6) 跨年 SAU 一致性 ----
    print("\n=== 跨年 SAU 集合一致性 ===")
    sau_per_year = {y: set(out[out["year"] == y]["sau_id"]) for y in years}
    base = sau_per_year[years[0]]
    for y in years[1:]:
        diff = sau_per_year[y] ^ base
        if not diff:
            print(f"  {years[0]} vs {y}: 完全一致 ({len(base)} SAU)")
        else:
            only_a = base - sau_per_year[y]
            only_b = sau_per_year[y] - base
            print(f"  {years[0]} vs {y}: 不一致 (僅 A: {len(only_a)}, 僅 B: {len(only_b)})")
            if only_b:
                sample = sorted(only_b)[:3]
                print(f"    只在 {y} 的 SAU 範例: {sample}")


if __name__ == "__main__":
    main()
