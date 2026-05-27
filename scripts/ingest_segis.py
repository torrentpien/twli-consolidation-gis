"""Ingest 社經平台 SEGIS 村里級 csv 為 long-format dataframe.

用法（作為模組）::

    from scripts.ingest_segis import list_topics, ingest_topic

    topics = list_topics()  # {ministry: {topic: folder_path}}
    df = ingest_topic(topics["行政部"]["行政區人口統計"])
    # df.columns = ["V_ID", "year", "COUNTY", "TOWN", "VILLAGE",
    #               "H_CNT", "P_CNT", "M_CNT", "F_CNT"]

設計重點：
- 自動偵測編碼（UTF-8-BOM / UTF-8 / CP950）
- 跳過第 2 列中文 header
- 解析檔名取得民國年（'109年12月XXX.csv' → 2020）
- 財政部主題的 TAG 欄位：非空白者是縣市/全國總計，ingest 時過濾掉
- 統一輸出欄位 V_ID, year 為主鍵；保留 COUNTY/TOWN/VILLAGE 文字欄
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pandas as pd

ROC_TO_AD_OFFSET = 1911

# 預設根目錄（相對 repo 根）
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "SEGIS按資料類型分"


# ---------- 編碼處理 ----------

def _decode_bytes(raw: bytes) -> tuple[str, str]:
    """Return (text, encoding_used). Tries UTF-8-BOM → UTF-8 → CP950."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8"), "utf-8-sig"
    for enc in ("utf-8", "cp950"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("cp950", errors="replace"), "cp950+replace"


# ---------- 檔名解析 ----------

_FNAME_PATTERN = re.compile(
    r"^(?P<roc>\d+)年(?P<month>\d+月)?(?P<topic>.+)_村里\.csv$"
)


def parse_filename(name: str) -> dict | None:
    """Parse 'NNN年[12月]主題_村里.csv' filename.

    Returns dict with keys: roc (int), year (西元 int), month (str|None), topic (str).
    """
    m = _FNAME_PATTERN.match(name)
    if not m:
        return None
    roc = int(m.group("roc"))
    return {
        "roc": roc,
        "year": roc + ROC_TO_AD_OFFSET,
        "month": m.group("month"),  # '12月' or None
        "topic": m.group("topic"),
    }


# ---------- 目錄掃描 ----------

def list_topics(root: Path | str = DEFAULT_ROOT) -> dict[str, dict[str, Path]]:
    """Return {ministry: {topic: folder_path}}."""
    root = Path(root)
    out: dict[str, dict[str, Path]] = {}
    for ministry_dir in sorted(root.iterdir()):
        if not ministry_dir.is_dir():
            continue
        topics: dict[str, Path] = {}
        for topic_dir in sorted(ministry_dir.iterdir()):
            if topic_dir.is_dir():
                topics[topic_dir.name] = topic_dir
        if topics:
            out[ministry_dir.name] = topics
    return out


def list_years(topic_dir: Path | str) -> list[int]:
    """List Gregorian years available under a topic folder."""
    topic_dir = Path(topic_dir)
    years: list[int] = []
    for p in sorted(topic_dir.glob("*.csv")):
        meta = parse_filename(p.name)
        if meta is not None:
            years.append(meta["year"])
    return sorted(years)


# ---------- CSV 讀取 ----------

# 必有的左半邊欄位
_BASE_COLS = ["COUNTY_ID", "COUNTY", "TOWN_ID", "TOWN", "V_ID", "VILLAGE"]


def read_csv(path: Path | str) -> pd.DataFrame:
    """Read a single year csv from SEGIS folder.

    - 自動編碼判斷後以 utf-8 餵 pandas
    - 跳過第 2 列中文 header
    - 強制 V_ID 為 str
    - 自動加入 `year` 欄（從檔名解析）
    - 自動過濾財政部 TAG 非空白的彙整列
    """
    path = Path(path)
    meta = parse_filename(path.name)
    if meta is None:
        raise ValueError(f"無法從檔名解析年份／主題: {path.name}")

    raw = path.read_bytes()
    text, _ = _decode_bytes(raw)

    # Use StringIO to feed pandas
    from io import StringIO

    df = pd.read_csv(
        StringIO(text),
        skiprows=[1],            # 跳過第 2 列「縣市代碼,縣市名稱,...」中文 header
        dtype={"V_ID": str},
    )
    df.columns = [c.strip() for c in df.columns]

    # 財政部 TAG 處理：保留 TAG 為空/NaN 的列（村里級資料），過濾縣市/全國彙整列
    if "TAG" in df.columns:
        # 空白字串、純空白、NaN 都當作「非彙整列」保留
        is_aggregate = df["TAG"].fillna("").astype(str).str.strip().ne("")
        n_drop = int(is_aggregate.sum())
        if n_drop:
            df = df.loc[~is_aggregate].copy()
        df = df.drop(columns=["TAG"])

    # 加入 year
    df["year"] = meta["year"]

    # V_ID 標準化（去掉首尾空白）
    df["V_ID"] = df["V_ID"].astype(str).str.strip()

    return df


# ---------- 整個主題 ----------

def ingest_topic(topic_dir: Path | str, years: Iterable[int] | None = None) -> pd.DataFrame:
    """Read all year csvs under one topic folder, concat into a long-format df.

    Parameters
    ----------
    topic_dir : path-like
        One topic folder, e.g. 'SEGIS按資料類型分/行政部/行政區人口統計'.
    years : iterable of Gregorian int, optional
        If provided, only ingest these years.

    Returns
    -------
    DataFrame with columns: [V_ID, year, COUNTY_ID, COUNTY, TOWN_ID, TOWN,
    VILLAGE, *topic-specific variables*]
    """
    topic_dir = Path(topic_dir)
    year_filter = set(years) if years is not None else None

    dfs: list[pd.DataFrame] = []
    for csv_path in sorted(topic_dir.glob("*.csv")):
        meta = parse_filename(csv_path.name)
        if meta is None:
            continue
        if year_filter is not None and meta["year"] not in year_filter:
            continue
        dfs.append(read_csv(csv_path))

    if not dfs:
        raise FileNotFoundError(f"No csvs ingested from {topic_dir}")

    df = pd.concat(dfs, ignore_index=True)

    # 把主鍵欄放前面
    front = ["V_ID", "year"] + [c for c in _BASE_COLS if c in df.columns and c != "V_ID"]
    other = [c for c in df.columns if c not in front]
    df = df[front + other]
    return df


# ---------- CLI ----------

def _main() -> None:
    """快速掃描 SEGIS 樹並列出每個主題的年份與行數摘要。"""
    topics = list_topics()
    for ministry, ts in topics.items():
        print(f"=== {ministry} ===")
        for topic, folder in ts.items():
            years = list_years(folder)
            print(f"  {topic:<32}  years={years[:1]}..{years[-1:]}  n={len(years)}")


if __name__ == "__main__":
    _main()
