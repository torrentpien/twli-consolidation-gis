"""集中宣告 SEGIS 各主題的整併規則 (vars_spec)。

設計原則：
1. **可直接 sum 的主題**：所有 _CNT 欄位（人口、戶數、各年齡層人數、教育程度
   分類人口等）。
2. **不直接整併、由 base 主題重算的主題**（DERIVED_FORMULAS）：人口指標 csv
   本身全是衍生比率（性比例、戶量、扶養比等），不直接整併，而是先 sum 人口
   統計 + 三段年齡組，再用公式 recompute 出指標。Q2 決議 (a)。
3. **特殊規則的主題**（財政部）：FLD01/FLD02 sum；FLD03 recompute；FLD04-08
   是樣本級分位數/變異統計量，無法精確重算，用 keep_if_unique 對受整併的
   SAU 標 NaN。Q3 決議 (a)。

用法（在 demo / 分析腳本內）::

    from scripts.vars_spec import INGEST_SPECS, DERIVED_FORMULAS
    from scripts.ingest_segis import list_topics, ingest_topic
    import twli_consolidate as tc

    pop_topic = list_topics()["行政部"]["行政區人口統計"]
    df = ingest_topic(pop_topic)
    spec = INGEST_SPECS["行政部・行政區人口統計"]
    out = tc.consolidate_panel(df, vid_col="V_ID", year_col="year",
                                vars_spec=spec, lineage=lineage)
"""
from __future__ import annotations

# ---------- 各主題直接整併規則 ----------

INGEST_SPECS: dict[str, dict[str, str | dict]] = {
    # =====================================================================
    # 行政部 9 主題
    # =====================================================================
    "行政部・行政區人口統計": {
        "H_CNT": "sum",
        "P_CNT": "sum",
        "M_CNT": "sum",
        "F_CNT": "sum",
    },
    "行政部・行政區三段年齡組性別人口統計": {
        # 0-14, 15-64, 65+ 三段，每段含總、男、女 → 9 欄
        "A0A14_CNT": "sum", "A0A14_M_CNT": "sum", "A0A14_F_CNT": "sum",
        "A15A64_CNT": "sum", "A15A64_M_CNT": "sum", "A15A64_F_CNT": "sum",
        "A65UP_CNT": "sum", "A65UP_M_CNT": "sum", "A65UP_F_CNT": "sum",
    },
    "行政部・行政區五歲年齡組性別人口統計": {
        # 0-4, 5-9, ..., 95-99, 100+ 共 21 組 × (總,男,女) = 63 欄
        # 自動生成
        **{f"A{lo}A{lo+4}_{s}CNT": "sum"
           for lo in range(0, 100, 5)
           for s in ("", "M_", "F_")},
        **{f"A100UP_5_{s}CNT": "sum" for s in ("", "M_", "F_")},
    },
    "行政部・行政區十歲年齡組性別人口統計": {
        # 0-9, 10-19, ..., 90-99, 100+ 共 11 組 × 3 = 33 欄
        **{f"A{lo}A{lo+9}_{s}CNT": "sum"
           for lo in range(0, 100, 10)
           for s in ("", "M_", "F_")},
        **{f"A100UP_{s}CNT": "sum" for s in ("", "M_", "F_")},
    },
    "行政部・行政區分齡兒童及少年性別人口統計": {
        # 0-5, 6-11, 12-17 三組 × 3 = 9 欄
        **{f"A{lo}A{lo+5}_{s}CNT": "sum"
           for lo in (0, 6, 12)
           for s in ("", "M_", "F_")},
    },
    # 原住民系列 3 主題 (人口統計/十歲年齡組/人口指標) 依研究方向決議**排除**，
    # 不納入 INGEST_SPECS / DERIVED_FORMULAS。SEGIS 內仍保留原始 csv（2020-2024,
    # 5 年），需要時可單獨 ingest 使用。完整名單見 SKIPPED_TOPICS。

    # 「人口指標」是 derived，由人口統計 + 三段年齡組 sum 後 recompute，
    # 見 DERIVED_FORMULAS（人口指標不在 INGEST_SPECS 內）。

    # =====================================================================
    # 教育部 1 主題
    # =====================================================================
    "教育部・行政區15歲以上人口教育程度統計": {
        # 9 個教育程度分類人口數
        "E1314_CNT": "sum",  # 博士
        "E1112_CNT": "sum",  # 碩士
        "E2122_CNT": "sum",  # 大學院校
        "E3_4_5_CNT": "sum", # 專科
        "E6_7_CNT": "sum",   # 高中職
        "E8_9_CNT": "sum",   # 國中初職
        "E1_2_CNT": "sum",   # 小學
        "E03_CNT": "sum",    # 自修
        "E04_CNT": "sum",    # 不識字
    },

    # =====================================================================
    # 財政部 1 主題
    # =====================================================================
    "財政部・綜合所得稅所得總額申報統計": {
        "FLD01": "sum",  # 納稅單位
        "FLD02": "sum",  # 綜合所得總額
        # FLD03 平均 = 總額 / 納稅單位
        "FLD03": {"agg": "recompute", "expr": "FLD02 / FLD01"},
        # FLD04 中位、FLD05 Q1、FLD06 Q3、FLD07 SD、FLD08 CV：
        # 樣本級分位/變異統計量無法從區級彙總重算，受整併 SAU 標 NaN
        "FLD04": "keep_if_unique",  # 中位數
        "FLD05": "keep_if_unique",  # 第一分位數
        "FLD06": "keep_if_unique",  # 第三分位數
        "FLD07": "keep_if_unique",  # 標準差
        "FLD08": "keep_if_unique",  # 變異係數
    },
}


# ---------- 衍生指標（不直接整併原始指標 csv，從 base 主題重算）----------

DERIVED_FORMULAS: dict[str, dict[str, dict]] = {
    "行政部・行政區人口指標": {
        # base = 整併後的「行政區人口統計」+「行政區三段年齡組」寬表
        # 需 join 兩份 panel
        "M_F_RAT":          {"expr": "M_CNT / F_CNT * 100",
                             "desc": "性比例 = 男 / 女 × 100"},
        "P_H_CNT":          {"expr": "P_CNT / H_CNT",
                             "desc": "戶量 = 人口 / 戶數"},
        # P_DEN (人口密度) 需要 SHP 面積，留給含面積的 demo 處理
        "DEPENDENCY_RAT":   {"expr": "(A0A14_CNT + A65UP_CNT) / A15A64_CNT * 100",
                             "desc": "扶養比"},
        "A0A14_A15A65_RAT": {"expr": "A0A14_CNT / A15A64_CNT * 100",
                             "desc": "扶幼比（原欄名 A15A65 實為 A15A64）"},
        "A65UP_A15A64_RAT": {"expr": "A65UP_CNT / A15A64_CNT * 100",
                             "desc": "扶老比"},
        "A65_A0A14_RAT":    {"expr": "A65UP_CNT / A0A14_CNT * 100",
                             "desc": "老化指數 = 65+ / 0-14 × 100"},
    },
    # 原住民人口指標：依研究方向決議排除，見 SKIPPED_TOPICS。
}


# ---------- 排除的主題（保留紀錄）----------

SKIPPED_TOPICS = {
    "行政部・行政區原住民人口統計":
        "依研究方向決議排除；SEGIS 仍保留原始 csv (2020-2024)。",
    "行政部・行政區原住民人口指標":
        "依研究方向決議排除；衍生指標，原本應由原住民人口 + 年齡 recompute。",
    "行政部・行政區原住民十歲年齡組性別人口統計":
        "依研究方向決議排除；SEGIS 仍保留原始 csv (2020-2024)。",
}


# ---------- 便利函式 ----------

def get_spec(topic_key: str) -> dict[str, str | dict]:
    """Return vars_spec for a given topic, or KeyError."""
    return INGEST_SPECS[topic_key]


def topic_key(ministry: str, topic: str) -> str:
    """Compose dict key used in INGEST_SPECS / DERIVED_FORMULAS."""
    return f"{ministry}・{topic}"


if __name__ == "__main__":
    # 快速 self-check
    print("INGEST_SPECS topics:")
    for k, spec in INGEST_SPECS.items():
        aggs = {}
        for col, rule in spec.items():
            a = rule if isinstance(rule, str) else rule.get("agg")
            aggs[a] = aggs.get(a, 0) + 1
        print(f"  {k}  ({len(spec)} cols, agg counts={aggs})")
    print()
    print("DERIVED_FORMULAS topics:")
    for k, formulas in DERIVED_FORMULAS.items():
        print(f"  {k}  ({len(formulas)} formulas)")
        for col, info in formulas.items():
            print(f"    {col}: {info['expr']}  # {info['desc']}")
    print()
    print("SKIPPED_TOPICS:")
    for k, reason in SKIPPED_TOPICS.items():
        print(f"  {k}  ← {reason}")
