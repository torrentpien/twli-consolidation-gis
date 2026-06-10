"""從 SEGIS 行政部人口統計 csv 推算整併事件（不需 SHP）.

用途：
- 在 SHP 不可得時，用 csv 反推 rename/merge/split/redistribute 歷史
- 與既有 SHP 版 crosswalk 做交叉驗證

限制：
- boundary_adjust（V_ID 不變但邊界調整）無法偵測（CSV 沒有幾何資訊）
- 同 TOWN 內 redistribute 群組可能不夠精準

演算法（每對相鄰年度）:
  1. 比對 V_ID 集合得 gone / new / common
  2. rename 偵測: 同 (COUNTY, TOWN, VILLAGE) 名稱跨年配對
  3. 同 TOWN 內 merge/split/redistribute 偵測:
     - 純 merge: N gones 全部 + common 內某 V_ID 人口暴增 ≈ gones 總和
     - 純 split: 0 gones + 1 common V_ID 人口縮減 ≈ news 總和
     - 混合: redistribute

輸出：crosswalk/village_changes_from_csv.yaml
（不覆蓋既有 SHP 版 crosswalk/village_changes.yaml）

執行：
    python scripts/build_crosswalk_from_csv.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ingest_segis import (  # noqa: E402
    ROC_TO_AD_OFFSET,
    ingest_topic,
    list_topics,
)


OUT = ROOT / "crosswalk" / "village_changes_from_csv.yaml"

# 人口守恆容差（split 時 source 人口下降 vs new 群人口總和）
POP_TOLERANCE_REL = 0.10


def ce_to_roc(ce: int) -> int:
    return ce - ROC_TO_AD_OFFSET


def _describe(row: pd.Series) -> dict:
    return {
        "v_id": row["V_ID"],
        "county": row.get("COUNTY"),
        "town": row.get("TOWN"),
        "village": row.get("VILLAGE") if pd.notna(row.get("VILLAGE")) else None,
    }


def build_events_for_pair(df_a: pd.DataFrame, df_b: pd.DataFrame,
                          year_a: int, year_b: int) -> list[dict]:
    """從兩年 csv 推算事件 list。"""
    df_a = df_a.set_index("V_ID")
    df_b = df_b.set_index("V_ID")
    vid_a = set(df_a.index)
    vid_b = set(df_b.index)
    gone = vid_a - vid_b
    new = vid_b - vid_a
    common = vid_a & vid_b

    events: list[dict] = []
    consumed_gone: set[str] = set()
    consumed_new: set[str] = set()

    # ----- Step 1: rename 偵測 -----
    # 用 (COUNTY, TOWN, VILLAGE) 三元組比對
    def _name_key(row):
        return (str(row.get("COUNTY", "")), str(row.get("TOWN", "")),
                str(row.get("VILLAGE", "")))

    new_name_to_vid: dict[tuple, list[str]] = defaultdict(list)
    for vid in new:
        new_name_to_vid[_name_key(df_b.loc[vid])].append(vid)

    for vid in gone:
        key = _name_key(df_a.loc[vid])
        cands = new_name_to_vid.get(key, [])
        if len(cands) == 1:
            tgt_vid = cands[0]
            events.append({
                "id": f"{ce_to_roc(year_a):02d}_{ce_to_roc(year_b):02d}"
                      f"_rename_{vid}",
                "effective_year": year_b,
                "effective_year_roc": ce_to_roc(year_b),
                "type": "rename",
                "confidence": "high",
                "method": "name_match",
                "sources": [_describe(df_a.loc[vid].rename({"V_ID": vid}).to_dict()
                                      | {"V_ID": vid})],
                "targets": [_describe(df_b.loc[tgt_vid].rename({"V_ID": tgt_vid}).to_dict()
                                      | {"V_ID": tgt_vid})],
            })
            consumed_gone.add(vid)
            consumed_new.add(tgt_vid)
            # 該 key 已用掉，從 candidates 移除以避免之後誤判
            new_name_to_vid[key].remove(tgt_vid)

    # ----- Step 2: merge / split / redistribute -----
    rem_gone = gone - consumed_gone
    rem_new = new - consumed_new

    # 按 TOWN（用 b 的 TOWN_ID 或 a 的，可能不同）分組
    # 策略：用 (COUNTY, TOWN) 名稱當 key
    def _town_key_a(vid):
        r = df_a.loc[vid]
        return (str(r.get("COUNTY", "")), str(r.get("TOWN", "")))

    def _town_key_b(vid):
        r = df_b.loc[vid]
        return (str(r.get("COUNTY", "")), str(r.get("TOWN", "")))

    gone_by_town: dict[tuple, list[str]] = defaultdict(list)
    for v in rem_gone:
        gone_by_town[_town_key_a(v)].append(v)

    new_by_town: dict[tuple, list[str]] = defaultdict(list)
    for v in rem_new:
        new_by_town[_town_key_b(v)].append(v)

    all_towns = set(gone_by_town.keys()) | set(new_by_town.keys())
    for town_key in sorted(all_towns):
        gones = gone_by_town.get(town_key, [])
        news = new_by_town.get(town_key, [])
        if not gones and not news:
            continue

        # 該 TOWN 內 common V_IDs（在 a 與 b 都存在）
        common_in_town = [
            v for v in common
            if _town_key_a(v) == town_key or _town_key_b(v) == town_key
        ]

        # 計算 common V_IDs 在 a→b 的人口差
        delta = []
        for v in common_in_town:
            pa = int(df_a.loc[v].get("P_CNT", 0) or 0)
            pb = int(df_b.loc[v].get("P_CNT", 0) or 0)
            delta.append((v, pb - pa))

        # 計算 gones 總和、news 總和
        gone_pop_sum = sum(int(df_a.loc[v].get("P_CNT", 0) or 0) for v in gones)
        new_pop_sum = sum(int(df_b.loc[v].get("P_CNT", 0) or 0) for v in news)

        # 啟發式判斷：
        if news and not gones:
            # 純 split 候選：找 common V_ID 人口下降量最接近 -new_pop_sum
            if not delta:
                # 沒有 common V_ID 可比對人口 → unknown
                events.append({
                    "id": f"{ce_to_roc(year_a):02d}_{ce_to_roc(year_b):02d}"
                          f"_unknown_new_{news[0]}",
                    "effective_year": year_b,
                    "effective_year_roc": ce_to_roc(year_b),
                    "type": "unknown",
                    "confidence": "low",
                    "method": "no_common_vid_in_town",
                    "sources": [],
                    "targets": [_describe(df_b.loc[v].to_dict() | {"V_ID": v})
                                for v in news],
                })
                continue
            best = min(delta, key=lambda x: abs(-new_pop_sum - x[1]))
            best_vid, best_delta = best
            tol = max(POP_TOLERANCE_REL * abs(best_delta or 1),
                      POP_TOLERANCE_REL * new_pop_sum)
            if -best_delta > 0 and abs(-best_delta - new_pop_sum) <= tol:
                # split: best_vid → best_vid + news
                events.append({
                    "id": f"{ce_to_roc(year_a):02d}_{ce_to_roc(year_b):02d}"
                          f"_split_{best_vid}",
                    "effective_year": year_b,
                    "effective_year_roc": ce_to_roc(year_b),
                    "type": "split",
                    "confidence": "medium",
                    "method": "pop_conservation",
                    "sources": [_describe(df_a.loc[best_vid].to_dict()
                                          | {"V_ID": best_vid})],
                    "targets": ([_describe(df_b.loc[best_vid].to_dict()
                                           | {"V_ID": best_vid})]
                                + [_describe(df_b.loc[v].to_dict() | {"V_ID": v})
                                   for v in news]),
                    "pop_evidence": {
                        "source_pop_drop": -best_delta,
                        "new_pop_sum": new_pop_sum,
                    },
                })
                continue
            # 否則：unknown new
            events.append({
                "id": f"{ce_to_roc(year_a):02d}_{ce_to_roc(year_b):02d}"
                      f"_unknown_new_{news[0]}",
                "effective_year": year_b,
                "effective_year_roc": ce_to_roc(year_b),
                "type": "unknown",
                "confidence": "low",
                "method": "unmatched_new",
                "sources": [],
                "targets": [_describe(df_b.loc[v].to_dict() | {"V_ID": v})
                            for v in news],
            })

        elif gones and not news:
            # 純 merge 候選：找 common V_ID 人口增加量最接近 gone_pop_sum
            if not delta:
                events.append({
                    "id": f"{ce_to_roc(year_a):02d}_{ce_to_roc(year_b):02d}"
                          f"_unknown_gone_{gones[0]}",
                    "effective_year": year_b,
                    "effective_year_roc": ce_to_roc(year_b),
                    "type": "unknown",
                    "confidence": "low",
                    "method": "no_common_vid_in_town",
                    "sources": [_describe(df_a.loc[v].to_dict() | {"V_ID": v})
                                for v in gones],
                    "targets": [],
                })
                continue
            best = min(delta, key=lambda x: abs(gone_pop_sum - x[1]))
            best_vid, best_delta = best
            tol = max(POP_TOLERANCE_REL * abs(best_delta or 1),
                      POP_TOLERANCE_REL * gone_pop_sum)
            if best_delta > 0 and abs(best_delta - gone_pop_sum) <= tol:
                # merge: gones + best_vid → best_vid
                events.append({
                    "id": f"{ce_to_roc(year_a):02d}_{ce_to_roc(year_b):02d}"
                          f"_merge_{best_vid}",
                    "effective_year": year_b,
                    "effective_year_roc": ce_to_roc(year_b),
                    "type": "merge",
                    "confidence": "medium",
                    "method": "pop_conservation",
                    "sources": ([_describe(df_a.loc[best_vid].to_dict()
                                           | {"V_ID": best_vid})]
                                + [_describe(df_a.loc[v].to_dict() | {"V_ID": v})
                                   for v in gones]),
                    "targets": [_describe(df_b.loc[best_vid].to_dict()
                                          | {"V_ID": best_vid})],
                    "pop_evidence": {
                        "gone_pop_sum": gone_pop_sum,
                        "target_pop_gain": best_delta,
                    },
                })
                continue
            # 否則：unknown gone
            events.append({
                "id": f"{ce_to_roc(year_a):02d}_{ce_to_roc(year_b):02d}"
                      f"_unknown_gone_{gones[0]}",
                "effective_year": year_b,
                "effective_year_roc": ce_to_roc(year_b),
                "type": "unknown",
                "confidence": "low",
                "method": "unmatched_gone",
                "sources": [_describe(df_a.loc[v].to_dict() | {"V_ID": v})
                            for v in gones],
                "targets": [],
            })

        else:
            # 混合：redistribute（不分組，整 TOWN 一個事件）
            events.append({
                "id": f"{ce_to_roc(year_a):02d}_{ce_to_roc(year_b):02d}"
                      f"_redistribute_{(gones+news)[0]}",
                "effective_year": year_b,
                "effective_year_roc": ce_to_roc(year_b),
                "type": "redistribute",
                "confidence": "low",
                "method": "town_grouped",
                "sources": [_describe(df_a.loc[v].to_dict() | {"V_ID": v})
                            for v in gones],
                "targets": [_describe(df_b.loc[v].to_dict() | {"V_ID": v})
                            for v in news],
                "pop_evidence": {
                    "gone_pop_sum": gone_pop_sum,
                    "new_pop_sum": new_pop_sum,
                },
            })

    return events


def main() -> None:
    print("從 SEGIS 行政部・人口統計 csv 推算整併事件...")
    topics = list_topics()
    df = ingest_topic(topics["行政部"]["行政區人口統計"])
    years = sorted(int(y) for y in df["year"].unique())
    print(f"涵蓋年份: {years[0]}–{years[-1]} ({len(years)} 年)")

    all_events: list[dict] = []
    for y1, y2 in zip(years[:-1], years[1:]):
        df_a = df[df["year"] == y1].drop_duplicates(subset=["V_ID"])
        df_b = df[df["year"] == y2].drop_duplicates(subset=["V_ID"])
        evs = build_events_for_pair(df_a, df_b, y1, y2)
        type_counts: dict[str, int] = defaultdict(int)
        for e in evs:
            type_counts[e["type"]] += 1
        print(f"  {y1}->{y2}: {len(evs)} 件 {dict(type_counts)}")
        all_events.extend(evs)

    out = {
        "version": 1,
        "description": "從 SEGIS csv 推算的村里整併紀錄（不含 boundary_adjust）",
        "generated_from": "SEGIS按資料類型分/行政部/行政區人口統計/*.csv",
        "method": "name_match + population_conservation",
        "limitations": [
            "無 SHP 幾何資訊，無法偵測 boundary_adjust 事件",
            "redistribute 群組依 TOWN 整批切，無法精確配對 source→target",
            "人口守恆容差 ±10%，邊界 case 可能誤判為 unknown",
        ],
        "type_glossary": {
            "rename": "VILLAGE 名稱不變但 V_ID 變動",
            "merge": "N 個來源被某保留 V_ID 吸收（人口暴增 ≈ 來源總和）",
            "split": "保留 V_ID 拆出多個新 V_ID（保留方人口下降 ≈ 新增總和）",
            "redistribute": "同 TOWN 內 M 個來源 + N 個新 V_ID（無法逐一配對）",
            "unknown": "無法解釋的 gone/new V_ID（待人工 review）",
        },
        "events": all_events,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, allow_unicode=True, sort_keys=False)
    print(f"\n寫入 {OUT.relative_to(ROOT)} （{len(all_events)} 件事件）")


if __name__ == "__main__":
    main()
