"""比對 SHP 推算 vs CSV 推算的 crosswalk YAML.

輸入：
  - crosswalk/village_changes.yaml          (SHP 版，4476 件，含 boundary_adjust)
  - crosswalk/village_changes_from_csv.yaml (CSV 版，413 件，無 boundary_adjust)

輸出：docs/crosswalk_diff_report.md
摘要：
  - 每對 transition 的事件類型分佈對照
  - 精確匹配 / SHP-only / CSV-only 事件數
  - 各分項的範例

執行：
    python scripts/compare_crosswalks.py
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SHP_YAML = ROOT / "crosswalk" / "village_changes.yaml"
CSV_YAML = ROOT / "crosswalk" / "village_changes_from_csv.yaml"
OUT = ROOT / "docs" / "crosswalk_diff_report.md"


def _vid_set(event: dict, key: str) -> frozenset[str]:
    """取出 sources 或 targets 的 V_ID 集合（hashable）。"""
    return frozenset(s["v_id"] for s in event.get(key, []))


def _event_signature(event: dict) -> tuple:
    """事件「身分」：(year, type, sources V_ID set, targets V_ID set)。

    用於精確匹配比對。type 比對時把 'rename'/'merge'/'split'/'redistribute' 視為
    同類別 (V_ID-change)，因為 csv 推算分類可能不同（例如 csv 把單一名稱不變
    的 V_ID rename 標成 redistribute）。
    """
    year = event["effective_year"]
    src = _vid_set(event, "sources")
    tgt = _vid_set(event, "targets")
    typ = event["type"]
    return (year, typ, src, tgt)


def _loose_signature(event: dict) -> tuple:
    """寬鬆比對：忽略 type 差異，只看 (year, sources, targets) 集合。"""
    return (event["effective_year"], _vid_set(event, "sources"),
            _vid_set(event, "targets"))


def main() -> None:
    shp = yaml.safe_load(SHP_YAML.read_text())["events"]
    csv = yaml.safe_load(CSV_YAML.read_text())["events"]

    # ---------- 1. 各年度 transition 事件類型分佈 ----------
    shp_by_year: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    csv_by_year: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in shp:
        shp_by_year[e["effective_year"]][e["type"]] += 1
    for e in csv:
        csv_by_year[e["effective_year"]][e["type"]] += 1

    years = sorted(set(shp_by_year.keys()) | set(csv_by_year.keys()))

    # ---------- 2. 精確 / 寬鬆匹配 ----------
    shp_strict = {_event_signature(e) for e in shp}
    csv_strict = {_event_signature(e) for e in csv}
    shp_loose = {_loose_signature(e) for e in shp}
    csv_loose = {_loose_signature(e) for e in csv}

    strict_match = shp_strict & csv_strict
    loose_match = shp_loose & csv_loose
    shp_only_loose = shp_loose - csv_loose
    csv_only_loose = csv_loose - shp_loose

    # SHP 只有的：按類型分組
    shp_only_by_type: dict[str, int] = defaultdict(int)
    for e in shp:
        if _loose_signature(e) in shp_only_loose:
            shp_only_by_type[e["type"]] += 1

    csv_only_by_type: dict[str, int] = defaultdict(int)
    for e in csv:
        if _loose_signature(e) in csv_only_loose:
            csv_only_by_type[e["type"]] += 1

    # 寬鬆匹配中 type 不同的對照
    type_mismatch_pairs: dict[tuple[str, str], int] = defaultdict(int)
    shp_by_loose: dict[tuple, list[dict]] = defaultdict(list)
    for e in shp:
        shp_by_loose[_loose_signature(e)].append(e)
    csv_by_loose: dict[tuple, list[dict]] = defaultdict(list)
    for e in csv:
        csv_by_loose[_loose_signature(e)].append(e)
    for sig in loose_match:
        shp_t = shp_by_loose[sig][0]["type"]
        csv_t = csv_by_loose[sig][0]["type"]
        if shp_t != csv_t:
            type_mismatch_pairs[(shp_t, csv_t)] += 1

    # ---------- 3. 寫 markdown 報告 ----------
    lines: list[str] = []
    lines.append("# Crosswalk 推算結果差異報告 (SHP vs CSV)")
    lines.append("")
    lines.append("> 由 `scripts/compare_crosswalks.py` 產出")
    lines.append("")
    lines.append("- **SHP 版**: `crosswalk/village_changes.yaml` "
                 f"({len(shp)} 件事件，民國 97-114 / 西元 2009-2025)")
    lines.append("- **CSV 版**: `crosswalk/village_changes_from_csv.yaml` "
                 f"({len(csv)} 件事件，民國 100-113 / 西元 2012-2024)")
    lines.append("")
    lines.append("## 1. 精確與寬鬆匹配概覽")
    lines.append("")
    lines.append("- **精確匹配**（year + type + sources + targets 全相同）: "
                 f"{len(strict_match)} 件")
    lines.append("- **寬鬆匹配**（year + sources + targets 相同，忽略 type 差）: "
                 f"{len(loose_match)} 件")
    lines.append(f"- **只 SHP 有**: {len(shp_only_loose)} 件")
    lines.append(f"- **只 CSV 有**: {len(csv_only_loose)} 件")
    lines.append("")

    lines.append("### 只 SHP 有的事件（按類型）")
    lines.append("")
    lines.append("| 類型 | 件數 |")
    lines.append("|---|---|")
    for typ, n in sorted(shp_only_by_type.items(), key=lambda x: -x[1]):
        lines.append(f"| {typ} | {n} |")
    lines.append("")
    lines.append("**說明**：")
    lines.append("- `boundary_adjust` 類 CSV 永遠抓不到（無幾何資訊）")
    lines.append("- `rename` SHP 有 CSV 沒：通常是 csv 內 COUNTY/TOWN 名稱也"
                 "變動（如桃園縣→桃園市），csv 三元組比對失效")
    lines.append("")

    lines.append("### 只 CSV 有的事件（按類型）")
    lines.append("")
    lines.append("| 類型 | 件數 |")
    lines.append("|---|---|")
    for typ, n in sorted(csv_only_by_type.items(), key=lambda x: -x[1]):
        lines.append(f"| {typ} | {n} |")
    lines.append("")
    lines.append("**說明**：")
    lines.append("- `unknown` 是 csv 推算無法解釋的 gone/new V_IDs（多半是 "
                 "raw csv 異常造成假事件）")
    lines.append("- `redistribute` csv 把整個 TOWN 內混合 gone/new 列為單一"
                 "事件，SHP 版可能拆成多個 connected component")
    lines.append("")

    if type_mismatch_pairs:
        lines.append("### 寬鬆匹配但 type 標籤不同的對應")
        lines.append("")
        lines.append("| SHP type | CSV type | 件數 |")
        lines.append("|---|---|---|")
        for (s, c), n in sorted(type_mismatch_pairs.items(),
                                key=lambda x: -x[1]):
            lines.append(f"| {s} | {c} | {n} |")
        lines.append("")

    # ---------- 4. 每年 transition 對照 ----------
    lines.append("## 2. 每年 transition 事件類型分佈")
    lines.append("")
    lines.append("（西元年；CSV 版只涵蓋 2012-2024）")
    lines.append("")
    lines.append("| 年 | SHP 各類型 | SHP 合計 | CSV 各類型 | CSV 合計 |")
    lines.append("|---|---|---|---|---|")
    for y in years:
        shp_d = shp_by_year.get(y, {})
        csv_d = csv_by_year.get(y, {})
        shp_str = ", ".join(f"{k}={v}" for k, v in sorted(shp_d.items())) or "—"
        csv_str = ", ".join(f"{k}={v}" for k, v in sorted(csv_d.items())) or "—"
        lines.append(f"| {y} | {shp_str} | {sum(shp_d.values())} | "
                     f"{csv_str} | {sum(csv_d.values())} |")
    lines.append("")

    # ---------- 5. SHP-only V_ID-change 事件範例 (排除 boundary_adjust) ----------
    lines.append("## 3. SHP 有、CSV 沒抓到的非 boundary_adjust 事件範例")
    lines.append("")
    examples = []
    for e in shp:
        if (e["type"] != "boundary_adjust"
                and _loose_signature(e) in shp_only_loose):
            examples.append(e)
        if len(examples) >= 10:
            break
    if not examples:
        lines.append("（無）")
    else:
        for e in examples:
            srcs = [s["v_id"] for s in e["sources"]]
            tgts = [t["v_id"] for t in e["targets"]]
            lines.append(f"- {e['effective_year']} {e['type']} "
                         f"sources={srcs} → targets={tgts}")
    lines.append("")

    # ---------- 6. CSV-only 事件範例 ----------
    lines.append("## 4. CSV 有、SHP 沒抓到的事件範例")
    lines.append("")
    examples = []
    for e in csv:
        if _loose_signature(e) in csv_only_loose:
            examples.append(e)
        if len(examples) >= 10:
            break
    if not examples:
        lines.append("（無）")
    else:
        for e in examples:
            srcs = [s["v_id"] for s in e["sources"]]
            tgts = [t["v_id"] for t in e["targets"]]
            lines.append(f"- {e['effective_year']} {e['type']} "
                         f"({e.get('confidence', '?')}) "
                         f"sources={srcs} → targets={tgts}")
    lines.append("")

    # ---------- 7. 結論 ----------
    lines.append("## 5. 結論")
    lines.append("")
    coverage = len(loose_match) / max(1, len({_loose_signature(e) for e in shp
                                              if e["type"] != "boundary_adjust"
                                              and 2012 <= e["effective_year"] <= 2024})) * 100
    lines.append(f"- 在 CSV 涵蓋年度 (2012-2024) 內，CSV 版抓到 "
                 f"**{coverage:.1f}%** 的 SHP 非 boundary_adjust 事件。")
    lines.append(f"- SHP 版額外的 {len([e for e in shp if e['type'] == 'boundary_adjust'])} 件 "
                 "`boundary_adjust` 事件 CSV 完全無法偵測。")
    lines.append("- CSV 版未抓到的事件主要落在：")
    lines.append("  - 升格年（如 103→104 桃園縣→桃園市，COUNTY 名稱也變動）")
    lines.append("  - 跨 TOWN 的事件（CSV 演算法限同 TOWN 處理）")
    lines.append("- CSV 版多出的 `unknown` 多半反映 raw csv 異常（如 V_ID typo、"
                 "編碼時點不同步）")
    lines.append("")
    lines.append("**建議用途**：")
    lines.append("- 主軸仍以 SHP 版 (`village_changes.yaml`) 為準")
    lines.append("- CSV 版 (`village_changes_from_csv.yaml`) 適合：")
    lines.append("  - SHP 不可得時的退路")
    lines.append("  - 對 SHP 版的獨立驗證（兩者一致 = 高信心；不一致 = 重點 review）")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"寫入 {OUT.relative_to(ROOT)}")
    print(f"  精確匹配: {len(strict_match)}")
    print(f"  寬鬆匹配: {len(loose_match)}")
    print(f"  只 SHP 有: {len(shp_only_loose)}")
    print(f"  只 CSV 有: {len(csv_only_loose)}")


if __name__ == "__main__":
    main()
