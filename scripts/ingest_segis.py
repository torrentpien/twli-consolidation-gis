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


_AGGREGATE_VILLAGE_NAMES = {"其他", "合計", "小計", "總計"}

# 可逐項調整啟用/停用的 normalization 規則
NORMALIZATION_STATS: dict[str, int] = {
    "drop_villagename_aggregate": 0,  # VILLAGE 為其他/合計等的彙整列
    "fix_equal_sign": 0,              # V_ID 用 `=` 取代 `-` 的 typo
    "fix_town_leading_zero": 0,       # TOWN_ID 缺前導 0 (7 位 → 8 位)
    "fix_town_rebuild": 0,            # TOWN_ID 長度不是 8 或開頭不是 COUNTY_ID，用 COUNTY_ID 重組
    "rebuild_from_town_id": 0,        # V_ID 開頭與同列 TOWN_ID 不符，用 TOWN_ID 重組
    "drop_999_aggregate": 0,          # V_ID 末三碼 999 的彙整列
}


def reset_normalization_stats() -> None:
    """歸零累計統計（每次 ingest 之前可呼叫）。"""
    for k in NORMALIZATION_STATS:
        NORMALIZATION_STATS[k] = 0


def _normalize_town_id(town_id: str, county_id: str) -> str:
    """8 位 TOWN_ID 標準化。

    規則：
    - 7 位 → 補前導 0（如 `9007020` → `09007020`）
    - 不以 COUNTY_ID 開頭 → 用 COUNTY_ID + 末 3 位重組
      （如 `100009020` COUNTY=`10009` → 取末 3 位 `020` → `10009020`）
    - 已是 8 位且開頭與 COUNTY_ID 對齊 → 不動
    """
    s = str(town_id).strip()
    cid = str(county_id).strip()
    if not s.isdigit():
        return s
    if len(s) == 7:
        NORMALIZATION_STATS["fix_town_leading_zero"] += 1
        return "0" + s
    if cid.isdigit() and len(cid) == 5 and not s.startswith(cid):
        # 開頭與 COUNTY_ID 不符，用 COUNTY_ID + 末 3 位重組
        if len(s) >= 3:
            NORMALIZATION_STATS["fix_town_rebuild"] += 1
            return cid + s[-3:]
    return s


def _normalize_vid_row(vid: str, town_id: str, county_id: str = "") -> str:
    """用同列 TOWN_ID 重組 V_ID（穩健規範化）。

    處理 typo：
    - `10018010=054` (TOWN_ID=10018010) → `10018010-054`
    - `9007020-999`  (TOWN_ID=9007020)  → `09007020-999`（先補 TOWN_ID 前導 0）
    - `100009020-003`(TOWN_ID=10009020) → `10009020-003`
      （V_ID 開頭與 TOWN_ID 不符時，用 TOWN_ID 重組）

    若 V_ID 末三碼不是合理的 3 位數字（如 V_ID 整個是 `999` 或非數字格式），
    不嘗試重組，原樣返回。
    """
    if not isinstance(vid, str):
        return vid
    s = vid.strip()
    if not s:
        return s

    # (a) `=` 修正
    if "=" in s:
        s = s.replace("=", "-")
        NORMALIZATION_STATS["fix_equal_sign"] += 1

    # 先規範化 TOWN_ID（補前導 0、用 COUNTY_ID 重組）
    town = _normalize_town_id(town_id, county_id)

    # (b) 只處理「V_ID 形式錯誤」的 case：V_ID 開頭部分不是 8 位數
    # （這才是真的 typo，例如 `100009020-003` 9 位 或 `9007020-999` 7 位）。
    #
    # 不處理「V_ID 開頭是 8 位數但與 TOWN_ID 不符」的 case
    # （那是行政區編碼時點不同步，例如 2019 年高雄三民區 V_ID=64000051-084
    # 但 TOWN_ID=64000050；兩者都對，只是時點不同，由整併 YAML 處理）
    if "-" in s:
        head, _, suffix = s.rpartition("-")
        if (suffix.isdigit() and len(suffix) == 3
                and town.isdigit() and len(town) == 8
                and head.isdigit() and len(head) != 8):
            # V_ID 開頭非 8 位數 → 用 TOWN_ID 重組
            NORMALIZATION_STATS["rebuild_from_town_id"] += 1
            s = f"{town}-{suffix}"
    return s


def read_csv(
    path: Path | str,
    drop_aggregate_vids: bool = True,
    normalize_vid: bool = True,
) -> pd.DataFrame:
    """Read a single year csv from SEGIS folder.

    - 自動編碼判斷後以 utf-8 餵 pandas
    - 跳過第 2 列中文 header
    - 強制 V_ID 為 str
    - 自動加入 `year` 欄（從檔名解析）
    - 自動過濾財政部 TAG 非空白的彙整列
    - `normalize_vid=True`（預設）：對已知 typo 規範化
      ・`=054` → `-054`（財政部 2023 已知 2 列）
      ・7 位數 TOWN_ID 補前導 0（如 `9007020-999` → `09007020-999`）
      ・9 位數 TOWN_ID 去掉多餘前導 0（如 `100009020-003` → `10009020-003`，
        財政部 2021 已知 25 列）
      ・額外過濾 VILLAGE 為「其他/合計/小計/總計」的彙整列
    - 若 `drop_aggregate_vids=True`（預設），過濾 V_ID 末三碼為 999 的彙整列
      （例如「64000030-999」是該鄉鎮無法分配個別村里的彙整數據）

    每次呼叫累計到模組層級的 NORMALIZATION_STATS，可手動 reset_normalization_stats()。
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
        dtype={"V_ID": str, "TOWN_ID": str, "COUNTY_ID": str},
    )
    df.columns = [c.strip() for c in df.columns]

    # 財政部 TAG 欄處理：先記錄 TAG 統計，再丟掉欄位
    # （彙整列識別改用 VILLAGE/V_ID 規則，因為 TAG=X 列中有些是 V_ID typo
    # 但實際是真實村里資料，例如 110 雲林斗南鎮 24 個里被誤標 TAG=X 且
    # V_ID 前綴多 1 個 0。先靠 VILLAGE 名與 V_ID 末三碼判斷彙整列，
    # 再 normalize V_ID 把這些真實村里救回來。）
    if "TAG" in df.columns:
        df = df.drop(columns=["TAG"])

    # 加入 year
    df["year"] = meta["year"]

    # V_ID 標準化（去掉首尾空白）
    df["V_ID"] = df["V_ID"].astype(str).str.strip()

    # VILLAGE 為「其他/合計/小計/總計」的彙整列過濾
    # 注意 SEGIS 內這些彙整列可能含全形空白（例：「其　他」），
    # 故先去除所有空白（半形/全形）再比對。
    if normalize_vid and "VILLAGE" in df.columns:
        def _norm_v(s):
            return str(s or "").replace(" ", "").replace("　", "").strip()
        is_village_agg = df["VILLAGE"].fillna("").map(_norm_v).isin(
            _AGGREGATE_VILLAGE_NAMES
        )
        n = int(is_village_agg.sum())
        if n:
            NORMALIZATION_STATS["drop_villagename_aggregate"] += n
            df = df.loc[~is_village_agg].copy()

    # V_ID + TOWN_ID typo 規範化（用同列 COUNTY_ID + 重組）
    if normalize_vid and "TOWN_ID" in df.columns:
        df["TOWN_ID"] = df["TOWN_ID"].astype(str).str.strip()
        cid_col = df["COUNTY_ID"].astype(str).str.strip() if "COUNTY_ID" in df.columns else [""] * len(df)
        df["V_ID"] = [
            _normalize_vid_row(v, t, c)
            for v, t, c in zip(df["V_ID"], df["TOWN_ID"], cid_col)
        ]
        # 同步規範化 TOWN_ID 自身
        df["TOWN_ID"] = [_normalize_town_id(t, c) for t, c in zip(df["TOWN_ID"], cid_col)]

    # 過濾彙整列（V_ID 末三碼 999）
    if drop_aggregate_vids:
        is_999 = df["V_ID"].str.endswith("-999")
        n = int(is_999.sum())
        if n:
            NORMALIZATION_STATS["drop_999_aggregate"] += n
            df = df.loc[~is_999].copy()

    return df


# ---------- 整個主題 ----------

def ingest_topic(
    topic_dir: Path | str,
    years: Iterable[int] | None = None,
    drop_aggregate_vids: bool = True,
    normalize_vid: bool = True,
) -> pd.DataFrame:
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
        dfs.append(read_csv(
            csv_path,
            drop_aggregate_vids=drop_aggregate_vids,
            normalize_vid=normalize_vid,
        ))

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
