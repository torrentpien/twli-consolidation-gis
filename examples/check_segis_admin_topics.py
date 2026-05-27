"""Phase B4: 行政部 9 主題整併後驗證腳本.

涵蓋 9 個主題：
- 7 個直接整併主題：人口統計、三段年齡、五歲年齡、十歲年齡、
  分齡兒少、原住民人口統計、原住民十歲年齡組
- 2 個衍生指標主題：人口指標、原住民人口指標（不直接整併，
  由 base 主題 sum 後 recompute；本腳本只標示說明）

驗證層次：
A. 每個主題 panel 基本檢查（原始 V_ID 數 vs SAU 列數、跨年 SAU 一致性）
B. 主題內欄位加總（性別合計、各組合計）
C. 主題間交叉驗證（人口統計 P_CNT == 三段年齡組總和、原住民 O+NON_O == 全人口...）

執行：
    python examples/check_segis_admin_topics.py
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
from scripts.vars_spec import (  # noqa: E402
    DERIVED_FORMULAS,
    INGEST_SPECS,
    topic_key,
)


def fmt(n: int | float) -> str:
    return f"{n:>14,}" if isinstance(n, int) else f"{n:>14.2f}"


def main() -> None:
    topics_tree = list_topics()
    admin_topics = topics_tree["行政部"]

    # 載入 lineage 一次（共用）
    cw = tc.load_crosswalk(ROOT / "crosswalk" / "village_changes.yaml")

    # ============================================================
    # A. 每個直接整併主題的 panel 基本檢查
    # ============================================================
    print("=" * 72)
    print("A. 每個直接整併主題 panel 基本檢查")
    print("=" * 72)

    panels: dict[str, pd.DataFrame] = {}
    raw_dfs: dict[str, pd.DataFrame] = {}
    direct_topics = [
        "行政區人口統計",
        "行政區三段年齡組性別人口統計",
        "行政區五歲年齡組性別人口統計",
        "行政區十歲年齡組性別人口統計",
        "行政區分齡兒童及少年性別人口統計",
        "行政區原住民人口統計",
        "行政區原住民十歲年齡組性別人口統計",
    ]

    years_seen = None
    for topic in direct_topics:
        folder = admin_topics[topic]
        df = ingest_topic(folder)
        years = sorted(df["year"].unique().tolist())
        if years_seen is None:
            years_seen = years
        spec = INGEST_SPECS[topic_key("行政部", topic)]
        lineage = tc.build_lineage(cw, year_range=(years[0], years[-1]))
        out = tc.consolidate_panel(
            df,
            vid_col="V_ID",
            year_col="year",
            vars_spec=spec,
            lineage=lineage,
            keep_member_list=True,
        )
        panels[topic] = out
        raw_dfs[topic] = df

        sau_per_year = {y: int((out["year"] == y).sum()) for y in years}
        sau_set_per_year = {y: set(out.loc[out["year"] == y, "sau_id"]) for y in years}
        all_same = all(sau_set_per_year[y] == sau_set_per_year[years[0]] for y in years)

        print(f"\n[{topic}]  cols={len(spec)}")
        print(f"  raw rows={len(df):,}, panel rows={len(out):,}")
        print(f"  SAU per year: {sau_per_year}")
        print(f"  跨年 SAU 集合一致: {'✓' if all_same else '✗'}")

    # ============================================================
    # B. 主題內欄位加總（性別合計、各組合計）
    # ============================================================
    print()
    print("=" * 72)
    print("B. 主題內加總驗證")
    print("=" * 72)

    # B1. 三段年齡組：A?_CNT == A?_M_CNT + A?_F_CNT
    print("\nB1. 三段年齡組性別合計 (A?_CNT == A?_M_CNT + A?_F_CNT)")
    p3 = panels["行政區三段年齡組性別人口統計"]
    for y in years_seen:
        yr = p3[p3["year"] == y]
        bad = 0
        for grp in ["A0A14", "A15A64", "A65UP"]:
            total = yr[f"{grp}_CNT"].sum()
            mf_sum = yr[f"{grp}_M_CNT"].sum() + yr[f"{grp}_F_CNT"].sum()
            if total != mf_sum:
                bad += 1
        flag = "✓" if bad == 0 else f"✗ {bad}/3 不符"
        print(f"  {y}: {flag}")

    # B2. 原住民人口統計：O_CNT == O1+O2 == O_M+O_F
    print("\nB2. 原住民人口統計 (O_CNT == O1+O2 == O_M+O_F)")
    pip_ = panels["行政區原住民人口統計"]
    for y in years_seen:
        yr = pip_[pip_["year"] == y]
        o = yr["O_CNT"].sum()
        o12 = yr["O1_CNT"].sum() + yr["O2_CNT"].sum()
        omf = yr["O_M_CNT"].sum() + yr["O_F_CNT"].sum()
        f1 = "✓" if o == o12 else "✗"
        f2 = "✓" if o == omf else "✗"
        print(f"  {y}: O={o:,}, O1+O2={o12:,} {f1},  O_M+O_F={omf:,} {f2}")

    # ============================================================
    # C. 主題間交叉驗證
    # ============================================================
    print()
    print("=" * 72)
    print("C. 主題間交叉驗證")
    print("=" * 72)

    p_pop = panels["行政區人口統計"]
    p5 = panels["行政區五歲年齡組性別人口統計"]
    p10 = panels["行政區十歲年齡組性別人口統計"]
    p_ip = panels["行政區原住民人口統計"]
    p_ip10 = panels["行政區原住民十歲年齡組性別人口統計"]

    # C1. P_CNT == 三段年齡組總和
    print("\nC1. P_CNT (人口統計) == A0A14 + A15A64 + A65UP (三段年齡組)")
    for y in years_seen:
        a = p_pop.loc[p_pop["year"] == y, "P_CNT"].sum()
        b = (p3.loc[p3["year"] == y, ["A0A14_CNT", "A15A64_CNT", "A65UP_CNT"]]
             .sum().sum())
        flag = "✓" if a == b else f"✗ diff={a-b:+,}"
        print(f"  {y}: P_CNT={a:>11,}, 3-group sum={b:>11,}  {flag}")

    # C2. P_CNT == 五歲組總和
    print("\nC2. P_CNT == 五歲年齡組所有 _CNT 加總")
    five_total_cols = [c for c in p5.columns
                       if c.endswith("_CNT") and not c.endswith("_M_CNT") and not c.endswith("_F_CNT")]
    for y in years_seen:
        a = p_pop.loc[p_pop["year"] == y, "P_CNT"].sum()
        b = int(p5.loc[p5["year"] == y, five_total_cols].sum().sum())
        flag = "✓" if a == b else f"✗ diff={a-b:+,}"
        print(f"  {y}: P_CNT={a:>11,}, 5y total={b:>11,}  {flag}")

    # C3. P_CNT == 十歲組總和
    print("\nC3. P_CNT == 十歲年齡組所有 _CNT 加總")
    ten_total_cols = [c for c in p10.columns
                      if c.endswith("_CNT") and not c.endswith("_M_CNT") and not c.endswith("_F_CNT")]
    for y in years_seen:
        a = p_pop.loc[p_pop["year"] == y, "P_CNT"].sum()
        b = int(p10.loc[p10["year"] == y, ten_total_cols].sum().sum())
        flag = "✓" if a == b else f"✗ diff={a-b:+,}"
        print(f"  {y}: P_CNT={a:>11,}, 10y total={b:>11,}  {flag}")

    # C4. M_CNT / F_CNT vs 三段年齡組性別總和
    print("\nC4. M_CNT (人口統計) == A?_M_CNT (三段年齡組各組男性總和)")
    for y in years_seen:
        a = p_pop.loc[p_pop["year"] == y, "M_CNT"].sum()
        b = (p3.loc[p3["year"] == y, ["A0A14_M_CNT", "A15A64_M_CNT", "A65UP_M_CNT"]]
             .sum().sum())
        flag = "✓" if a == b else f"✗ diff={a-b:+,}"
        print(f"  {y}: M_CNT={a:>11,}, 3-group M={b:>11,}  {flag}")

    # C5. 原住民 + 非原住民 == 總人口
    print("\nC5. P_CNT == O_CNT + NON_O_CNT")
    for y in years_seen:
        a = p_pop.loc[p_pop["year"] == y, "P_CNT"].sum()
        b = (p_ip.loc[p_ip["year"] == y, ["O_CNT", "NON_O_CNT"]].sum().sum())
        flag = "✓" if a == b else f"✗ diff={a-b:+,}"
        print(f"  {y}: P_CNT={a:>11,}, O+NON_O={b:>11,}  {flag}")

    # C6. 原住民 O_CNT vs 原住民十歲年齡組總和
    print("\nC6. O_CNT (原住民人口統計) == 原住民十歲年齡組所有 M/F 加總")
    ip10_cols = [c for c in p_ip10.columns if c.endswith("_M_CNT") or c.endswith("_F_CNT")]
    for y in years_seen:
        a = p_ip.loc[p_ip["year"] == y, "O_CNT"].sum()
        b = int(p_ip10.loc[p_ip10["year"] == y, ip10_cols].sum().sum())
        flag = "✓" if a == b else f"✗ diff={a-b:+,}"
        print(f"  {y}: O_CNT={a:>11,}, IP10 total={b:>11,}  {flag}")

    # ============================================================
    # D. 已知 raw csv 異常（非套件 bug，驗證後標示）
    # ============================================================
    print()
    print("=" * 72)
    print("D. 已知 RAW csv 異常（非套件 bug）")
    print("=" * 72)

    # D1. 2020 分齡兒少少 2 個 V_ID
    print("\nD1. 分齡兒少 2020 少 2 個 V_ID (raw csv 本身少)")
    pop_2020_vids = set(raw_dfs["行政區人口統計"].loc[
        raw_dfs["行政區人口統計"]["year"] == 2020, "V_ID"])
    ch_2020_vids = set(raw_dfs["行政區分齡兒童及少年性別人口統計"].loc[
        raw_dfs["行政區分齡兒童及少年性別人口統計"]["year"] == 2020, "V_ID"])
    miss = sorted(pop_2020_vids - ch_2020_vids)
    print(f"  缺少 V_ID: {miss}")
    print(f"  推測：該村里該年無 18 歲以下兒少人口，SEGIS 略過該列")

    # D2. 2020 原住民十歲組少 423 個 V_ID
    print("\nD2. 原住民十歲年齡組 2020 少 423 個 V_ID (raw csv 本身少)")
    ip_2020_vids = set(raw_dfs["行政區原住民人口統計"].loc[
        raw_dfs["行政區原住民人口統計"]["year"] == 2020, "V_ID"])
    ip10_2020_vids = set(raw_dfs["行政區原住民十歲年齡組性別人口統計"].loc[
        raw_dfs["行政區原住民十歲年齡組性別人口統計"]["year"] == 2020, "V_ID"])
    miss10 = ip_2020_vids - ip10_2020_vids
    print(f"  缺少 {len(miss10)} 個 V_ID")
    print(f"  推測：2020 SEGIS 此主題只列「有原住民人口」的村里，2021+ 補齊全村里")

    # D3. C5 P_CNT != O+NON_O (raw csv 本身就不等)
    print("\nD3. P_CNT != O_CNT + NON_O_CNT (raw csv 本身就不等)")
    print(f"  {'year':>6}  {'P_CNT':>14}  {'O+NON_O':>14}  {'diff':>10}")
    for y in years_seen:
        p = int(raw_dfs["行政區人口統計"]
                .loc[raw_dfs["行政區人口統計"]["year"] == y, "P_CNT"].sum())
        ip = raw_dfs["行政區原住民人口統計"]
        on = int(ip.loc[ip["year"] == y, ["O_CNT", "NON_O_CNT"]].sum().sum())
        print(f"  {y:>6}  {p:>14,}  {on:>14,}  {p - on:>+10,}")
    print(f"  解讀：2021+ NON_O_CNT 統計範圍可能不含外籍/無戶籍人口，")
    print(f"        SEGIS 來源資料本身的定義差異，使用者需注意。")

    # ============================================================
    # E. 衍生指標主題（不直接整併，只列出說明）
    # ============================================================
    print()
    print("=" * 72)
    print("E. 衍生指標主題（不直接整併，由 base 主題 recompute）")
    print("=" * 72)
    for topic_name in ["行政區人口指標", "行政區原住民人口指標"]:
        key = topic_key("行政部", topic_name)
        if key not in DERIVED_FORMULAS:
            continue
        print(f"\n[{topic_name}] base = base topics 整併後 sum，再 recompute:")
        for col, info in DERIVED_FORMULAS[key].items():
            print(f"  {col:<20} = {info['expr']:<50} # {info['desc']}")


if __name__ == "__main__":
    main()
