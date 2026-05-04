"""
Spatially analyze year-pair SHP transitions and emit a crosswalk YAML
documenting every village merge / split / rename / redistribute /
boundary_adjust event.

Usage:
    python scripts/build_crosswalk.py
"""
from __future__ import annotations

import warnings
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd
import yaml

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "crosswalk" / "village_changes.yaml"

# 民國年 -> 西元年 (snapshot taken end of December)
YEARS_ROC = [97, 98, 99, 100, 101, 102, 103, 104, 105, 106,
             107, 108, 109, 110, 111, 112, 113, 114]


def roc_to_ce(roc: int) -> int:
    return roc + 1911


def load_year(roc: int) -> gpd.GeoDataFrame:
    p = DATA / f"{roc}年12月行政區人口統計_村里_SHP" / f"{roc}年12月行政區人口統計_村里.SHP"
    g = gpd.read_file(p, encoding="cp950")
    # Older snapshots include rows with no V_ID (military zones, ports, etc.).
    # They cannot participate in lineage tracking, so drop them.
    g = g[g["V_ID"].notna()].copy()
    g["AREA"] = g.geometry.area
    return g.reset_index(drop=True)


def overlap_table(src_df: gpd.GeoDataFrame, tgt_df: gpd.GeoDataFrame, src_ids: list[str], min_pct=0.01):
    """For each src V_ID, return list of target V_IDs whose intersection covers
    > min_pct of the source polygon area."""
    rows = []
    sindex = tgt_df.sindex
    src_lookup = src_df.set_index("V_ID")
    for vid in src_ids:
        poly = src_lookup.loc[vid].geometry
        a = poly.area
        for ci in sindex.intersection(poly.bounds):
            other = tgt_df.iloc[ci]
            inter = poly.intersection(other.geometry).area
            if a > 0 and inter / a > min_pct:
                rows.append({
                    "src_vid": vid,
                    "tgt_vid": other["V_ID"],
                    "pct_of_src": inter / a,
                })
    return pd.DataFrame(rows)


def build_events_for_pair(roc_from: int, roc_to: int):
    """Return list of crosswalk event dicts for one year-pair transition."""
    g_from = load_year(roc_from)
    g_to = load_year(roc_to)
    s_from, s_to = set(g_from["V_ID"]), set(g_to["V_ID"])

    gone = sorted(s_from - s_to)        # disappeared
    new = sorted(s_to - s_from)         # appeared
    common = list(s_from & s_to)

    info_from = g_from.set_index("V_ID")
    info_to = g_to.set_index("V_ID")

    # ---- step 1: V_ID-changing events (rename / merge / split / redistribute) ----
    # Build undirected bipartite edges: (gone, *) and (*, new) via spatial overlap
    events = []
    consumed_gone, consumed_new = set(), set()

    # For every gone V_ID, find target overlap
    ov_gone = overlap_table(g_from, g_to, gone, min_pct=0.05) if gone else pd.DataFrame()
    # For every new V_ID, find source overlap
    ov_new = overlap_table(g_to, g_from, new, min_pct=0.05) if new else pd.DataFrame()

    # Build a graph linking gone-or-new V_IDs to also-affected V_IDs (from either snapshot).
    # Nodes: V_IDs from either snapshot. Edges: spatial overlap involving any gone or new V_ID.
    adj = defaultdict(set)
    edges = []
    for _, r in ov_gone.iterrows():
        edges.append((("from", r["src_vid"]), ("to", r["tgt_vid"])))
    for _, r in ov_new.iterrows():
        edges.append((("to", r["src_vid"]), ("from", r["tgt_vid"])))
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)

    # Connected components within this transition
    seen = set()
    components: list[list[tuple[str, str]]] = []
    for node in list(adj.keys()):
        if node in seen:
            continue
        stack = [node]
        comp = []
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            comp.append(n)
            stack.extend(adj[n] - seen)
        components.append(comp)

    # Track which V_IDs are absorbed into V_ID-change events (excluded from boundary_adjust)
    consumed_in_change_events: set[str] = set()

    # Emit one event per component, classifying by counts
    for comp in components:
        side_from = sorted({vid for side, vid in comp if side == "from"})
        side_to = sorted({vid for side, vid in comp if side == "to"})
        # Augment: a surviving V_ID present in both snapshots should appear on both sides
        sources = sorted(set(side_from) | {v for v in side_to if v in s_from})
        targets = sorted(set(side_to) | {v for v in side_from if v in s_to})
        # Skip degenerate
        if not sources or not targets:
            continue
        gone_in = [v for v in sources if v not in s_to]
        new_in = [v for v in targets if v not in s_from]

        if len(gone_in) == 0 and len(new_in) == 0:
            continue  # pure boundary adjust, handled later
        elif len(sources) == 1 and len(targets) == 1 and len(gone_in) == 1 and len(new_in) == 1:
            etype = "rename"
        elif len(targets) == 1 and len(gone_in) >= 1:
            etype = "merge"
        elif len(sources) == 1 and len(new_in) >= 1:
            etype = "split"
        else:
            etype = "redistribute"

        consumed_in_change_events.update(sources)
        consumed_in_change_events.update(targets)

        ev = {
            "id": f"{roc_from}_{roc_to}_{etype}_{sources[0]}",
            "effective_year": roc_to_ce(roc_to),
            "effective_year_roc": roc_to,
            "type": etype,
            "sources": [_describe(info_from, v, year=roc_from) for v in sources],
            "targets": [_describe(info_to, v, year=roc_to) for v in targets],
            "overlap": _emit_overlap(ov_gone, ov_new, sources, targets),
        }
        events.append(ev)

    # ---- step 2: pure boundary_adjust events (V_ID kept, geom changed >5%) ----
    g_from_c = info_from.loc[common]
    g_to_c = info_to.loc[common]
    # symmetric difference ratio
    sym = g_from_c.geometry.symmetric_difference(g_to_c.geometry, align=False).area
    a_from = g_from_c.geometry.area
    ratio = (sym / a_from.replace(0, 1)).rename("ratio")
    df_adj = pd.DataFrame({"ratio": ratio}).join(g_from_c[["COUNTY", "TOWN", "VILLAGE"]])
    df_adj = df_adj[df_adj["ratio"] > 0.05].sort_values("ratio", ascending=False)

    # Exclude V_IDs already part of V_ID-change events (their geometry change is explained there)
    df_adj = df_adj[~df_adj.index.isin(consumed_in_change_events)]

    if not df_adj.empty:
        adj_ids = list(df_adj.index)
        adj_geoms = info_from.loc[adj_ids].geometry
        # Build edges: V_IDs in same TOWN whose geometries touch
        towns = info_from.loc[adj_ids, "TOWN"]
        edges = defaultdict(set)
        for i, vi in enumerate(adj_ids):
            for j in range(i + 1, len(adj_ids)):
                vj = adj_ids[j]
                if towns[vi] != towns[vj]:
                    continue
                if adj_geoms[vi].distance(adj_geoms[vj]) < 1.0:
                    edges[vi].add(vj)
                    edges[vj].add(vi)

        seen2 = set()
        for vid in adj_ids:
            if vid in seen2:
                continue
            stack = [vid]
            comp = []
            while stack:
                n = stack.pop()
                if n in seen2:
                    continue
                seen2.add(n)
                comp.append(n)
                stack.extend(edges[n] - seen2)
            comp = sorted(comp)
            ev = {
                "id": f"{roc_from}_{roc_to}_boundary_adjust_{comp[0]}",
                "effective_year": roc_to_ce(roc_to),
                "effective_year_roc": roc_to,
                "type": "boundary_adjust",
                "sources": [_describe(info_from, v, year=roc_from) for v in comp],
                "targets": [_describe(info_to, v, year=roc_to) for v in comp],
                "symdiff_pct": {v: round(float(df_adj.loc[v, "ratio"]), 4) for v in comp},
            }
            events.append(ev)

    return events


def _describe(info_df: gpd.GeoDataFrame, v_id: str, year: int) -> dict:
    r = info_df.loc[v_id]
    return {
        "v_id": v_id,
        "county": r["COUNTY"],
        "town": r["TOWN"],
        "village": r["VILLAGE"] if pd.notna(r["VILLAGE"]) else None,
    }


def _emit_overlap(ov_gone: pd.DataFrame, ov_new: pd.DataFrame, sources, targets) -> list:
    rows = []
    if not ov_gone.empty:
        for _, r in ov_gone[ov_gone["src_vid"].isin(sources)].iterrows():
            if r["tgt_vid"] in targets:
                rows.append({
                    "from": r["src_vid"],
                    "to": r["tgt_vid"],
                    "pct_of_source": round(float(r["pct_of_src"]), 4),
                })
    if not ov_new.empty:
        for _, r in ov_new[ov_new["src_vid"].isin(targets)].iterrows():
            if r["tgt_vid"] in sources:
                rows.append({
                    "to": r["src_vid"],
                    "from": r["tgt_vid"],
                    "pct_of_target": round(float(r["pct_of_src"]), 4),
                })
    return rows


def main():
    all_events = []
    for y1, y2 in zip(YEARS_ROC[:-1], YEARS_ROC[1:]):
        print(f"Analyzing 民國{y1} -> {y2} ...")
        evs = build_events_for_pair(y1, y2)
        print(f"  -> {len(evs)} events ({sum(e['type']!='boundary_adjust' for e in evs)} V_ID-change, {sum(e['type']=='boundary_adjust' for e in evs)} boundary_adjust)")
        all_events.extend(evs)

    out = {
        "version": 1,
        "description": "臺灣村里行政區整併紀錄 (從內政部行政區圖比對自動產生，需人工 review)",
        "generated_from": "data/{民國年}年12月行政區人口統計_村里_SHP",
        "year_format": "effective_year=西元, effective_year_roc=民國; 事件代表 effective_year 起該邊界生效",
        "type_glossary": {
            "rename": "改名或代碼重編，幾何不變或微調",
            "merge": "多個來源村里合併為一個 (V_ID 數減少)",
            "split": "一個來源村里分割為多個 (V_ID 數增加)",
            "redistribute": "M→N 重劃，多對多重新分配",
            "boundary_adjust": "V_ID 不變但幾何顯著變動 (>5% 對稱差)",
        },
        "transition_notes": {
            2011: "民國99→100：五都升格 (新北、臺中、臺南、高雄)。約 2849 筆 rename"
                  "事件均為同地理位置之 V_ID 大量重編。",
            2015: "民國103→104：桃園升格直轄市。約 495 筆 rename 為桃園縣→桃園市之"
                  "V_ID 重編。",
            2019: "民國107→108：高雄市三民區等多區 V_ID 微調，並大量內政部圖資重新測"
                  "繪 (>3000 個村里幾何 5% 以上變動，多為測量更新而非真正行政區劃調整)。",
            2020: "民國108→109：高雄市部分 TOWN 代碼回退調整。",
        },
        "events": all_events,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, allow_unicode=True, sort_keys=False)
    print(f"\nWrote {OUT} with {len(all_events)} events.")


if __name__ == "__main__":
    main()
