# twli-consolidation-gis

臺灣村里行政區整併歷年紀錄 + Python / R 整併套件。讓研究者能把跨年的村里級
panel data（人口、教育、所得等社經變數）依歷年實際的整併、分割、改名事件
自動聚合到「穩定分析單元（Stable Analysis Unit, SAU）」，避免 V_ID 變動造成
跨年資料不可比。

## 倉庫結構

```
twli-consolidation-gis/
├── crosswalk/
│   └── village_changes.yaml   ← 整併事件權威資料庫（4476 件 / 18 年）
├── scripts/
│   ├── build_crosswalk.py     ← 從 SHP 自動產生 YAML
│   ├── ingest_segis.py        ← SEGIS 多來源 csv 通用 ingest
│   ├── vars_spec.py           ← 各主題整併規則集中宣告
│   └── list_drive_inventory.py← 社經平台 Drive 盤點工具
├── python/
│   └── twli_consolidate/      ← Python 套件
├── R/
│   └── twliConsolidate/       ← R 套件
├── data/                      ← 18 年內政部 SHP 原檔
│   └── 97-114年12月行政區人口統計_村里_SHP/
├── SEGIS按資料類型分/         ← SEGIS 三來源 53 個 csv
│   ├── 行政部/、教育部/、財政部/
├── examples/                  ← demo 與驗證腳本
└── docs/                      ← 文件
```

## Crosswalk YAML：整個套件的核心

`crosswalk/village_changes.yaml` 是整個專案的權威資料來源——所有跨年整併
邏輯都建立在這份檔案上。

### 它記錄什麼

民國 97-114（2008-2025）共 18 年間，臺灣所有村里 V_ID 的歷年變化，共
**4476 個事件**，分 5 種類型：

| 類型 | 規則 | 範例 |
|---|---|---|
| `rename` | 1 個來源 → 1 個目標，V_ID 不同 | 永豊里 → 永豐里 |
| `merge` | N 個來源 → 1 個目標 | 高雄大寮光武里 + 忠義里 → 忠義里 |
| `split` | 1 個來源 → N 個目標 | 鹿港頂厝里 005 → 005 + 鹿和里 030 + 鹿東里 031 |
| `redistribute` | M 個來源 → N 個目標 | 八德重劃 |
| `boundary_adjust` | V_ID 不變但邊界 >5% 對稱差變動 | 內政部圖資重測 |

### YAML 結構

```yaml
version: 1
description: 臺灣村里行政區整併紀錄
type_glossary: { rename: ..., merge: ..., split: ..., ... }
transition_notes:
  2011: 民國99→100：五都升格 (新北、臺中、臺南、高雄)。2849 筆 rename...
  2015: 民國103→104：桃園升格直轄市。495 筆 rename...
  2019: 民國107→108：高雄市三民區等多區 V_ID 微調 + 圖資重測...
events:
  - id: 110_111_split_10007020-005     # 民100→111 之間的事件
    effective_year: 2022               # 西元 (生效年)
    effective_year_roc: 111            # 民國
    type: split
    sources:                           # 之前的 V_ID 們
      - { v_id: 10007020-005, county: 彰化縣, town: 鹿港鎮, village: 頂厝里 }
    targets:                           # 之後的 V_ID 們
      - { v_id: 10007020-005, ..., village: 頂厝里 }
      - { v_id: 10007020-030, ..., village: 鹿和里 }
      - { v_id: 10007020-031, ..., village: 鹿東里 }
    overlap:                           # 空間重疊比例
      - { to: 10007020-030, from: 10007020-005, pct_of_target: 1.0 }
      - { to: 10007020-031, from: 10007020-005, pct_of_target: 1.0 }
```

### 如何「被使用」

套件 API 把 YAML 載入後，建構出跨年「SAU 圖譜」：

```python
import twli_consolidate as tc

# 1. 載入 YAML 為事件 list
events = tc.load_crosswalk("crosswalk/village_changes.yaml")

# 2. 依分析年度範圍建構 lineage（用 connected component 把相關 V_ID 連成 SAU）
lineage = tc.build_lineage(events, year_range=(2011, 2024))

# 3. 套用 lineage 把 panel data 整併
panel = tc.consolidate_panel(
    df,
    vid_col="V_ID",
    year_col="year",
    vars_spec={
        "P_CNT": "sum",
        "DENSITY": {"agg": "recompute", "expr": "P_CNT / AREA"},
    },
    lineage=lineage,
)
```

R 套件 API 對齊（`load_crosswalk()` / `build_lineage()` / `liSum()` / `liEqu()` / `liShp()`）。

### 如何產生

`scripts/build_crosswalk.py` **從 SHP 自動產出**，演算法摘要：

對每對相鄰年度（例如 2021→2022）：

1. 讀兩個年度的 SHP（內政部行政區圖）
2. 比對 V_ID 集合：消失的、新增的、共同的
3. 對消失/新增的 V_ID 做**空間相交分析**，找誰跟誰的多邊形重疊 >5%
4. 用 connected component 演算法把空間相關的 V_ID 連成群組
5. 依群組成員數量分類（rename/merge/split/redistribute）
6. 對 V_ID 不變但邊界對稱差 >5% 的，標 `boundary_adjust` 事件

### 維護流程（新年度 SHP 釋出時）

當內政部釋出新年度 SHP（例如民國 115，2026 年 12 月）：

```bash
# 1. 把新年 SHP 放進 data/
data/115年12月行政區人口統計_村里_SHP/
    115年12月行政區人口統計_村里.SHP
    115年12月行政區人口統計_村里.DBF
    115年12月行政區人口統計_村里.SHX

# 2. 把 build_crosswalk.py 內年度範圍擴到包含新年
#    （目前預設 YEARS_ROC = [110, 111, 112, 113, 114]）
#    改為涵蓋所有可用年份：
sed -i '' 's/YEARS_ROC = .*/YEARS_ROC = list(range(97, 116))/' scripts/build_crosswalk.py

# 3. 重跑
python scripts/build_crosswalk.py
# Output: crosswalk/village_changes.yaml (含新年度事件)

# 4. 人工 review 新增的事件（重點看新年度的 merge / split / redistribute）
git diff crosswalk/village_changes.yaml | less

# 5. 同步更新套件內 bundled YAML
cp crosswalk/village_changes.yaml python/twli_consolidate/data/
cp crosswalk/village_changes.yaml R/twliConsolidate/inst/extdata/

# 6. 跑驗證確認沒回歸
python -m pytest python/tests/                  # 套件單元測試 23/23
python examples/check_segis_admin_topics.py     # 行政部主題交叉驗證

# 7. Commit
git add crosswalk/ python/twli_consolidate/data/ R/twliConsolidate/inst/extdata/
git commit -m "extend crosswalk to民國 NNN (YYYY-MM)"
```

### Lineage 與 SAU 的概念

- **Lineage**：把所有「血緣相關」的 V_ID（不論是否被改名、合併、拆分）連成
  同一個 connected component
- **SAU (Stable Analysis Unit)**：每個 connected component 就是一個 SAU，
  命名為 `SAU_<群組內首個 V_ID>`（如 `SAU_10007020-005`）
- 跨年 panel data 只要把同 SAU 的多個 V_ID 數據加總，就得到跨年連續可比的
  分析單元

範例：鹿港頂厝里 SAU（2011-2024 panel）

| 年份 | V_IDs 在 raw 中 | SAU 整併後 P_CNT |
|---|---|---|
| 2011-2021 | [005] | 8,999 → 10,312 |
| 2022 | [005, 030, 031] | 3,923 + 3,003 + 3,400 = **10,326** |
| 2023 | [005, 030, 031] | **10,284** |
| 2024 | [005, 030, 031] | **10,336** |

跨年 P_CNT 連續可比，沒有因 2022 拆分造成跳動。

## 安裝與快速開始

### Python 套件

```bash
git clone https://github.com/torrentpien/twli-consolidation-gis.git
cd twli-consolidation-gis
pip install pandas pyyaml geopandas pytest
export PYTHONPATH=python
python -m pytest python/tests/   # 23 個單元測試應全綠
```

### R 套件

```R
# 從本地安裝
devtools::install_local("R/twliConsolidate")
```

### 第一個 demo

```bash
python examples/demo_segis_panel.py
# 跑 14 年（2011-2024）的人口統計 SAU panel
# Output: examples/output/demo_segis_population.csv
```

## SEGIS 多來源資料整合

`SEGIS按資料類型分/` 內含三來源、8 個採用主題、53 個 csv，皆為村里級
（V_ID 主鍵）。Ingest 與整併規則已在 `scripts/ingest_segis.py` 與
`scripts/vars_spec.py` 配置好。

詳細結構與使用見 [`docs/segis_inventory.md`](docs/segis_inventory.md)。

### 已採用主題

| 來源 | 主題 | 年度 | 欄位數 |
|---|---|---|---|
| 行政部 | 人口統計 / 人口指標 / 三段/五歲/十歲年齡組 / 分齡兒少 | 100-113 | 4 + 7 + 9 + 63 + 33 + 9 |
| 教育部 | 15+ 教育程度 | 100-113 | 9 |
| 財政部 | 綜合所得稅所得總額 | 100-112 | 8 |

行政部「原住民人口統計／人口指標／十歲年齡組」三主題已依研究方向排除，仍保留原始 csv。

### 跨來源寬表

```bash
python examples/demo_multi_source_panel.py
# 4 個主題在 (sau_id, year) 上 LEFT JOIN
# Output: examples/output/demo_multi_source_panel.csv
# 規模：106,414 列 × 39 欄
```

## 文件清單

| 路徑 | 內容 |
|---|---|
| [`docs/segis_inventory.md`](docs/segis_inventory.md) | SEGIS 三來源完整使用指南 |
| [`docs/plan_segis_multi_source.md`](docs/plan_segis_multi_source.md) | SEGIS 整合方案的規劃與決議 |
| [`docs/data_inventory.md`](docs/data_inventory.md) | 雲端硬碟原始資料盤點（21 個時點 ↔ SHP 對應）|
| [`docs/tax_alignment_report.md`](docs/tax_alignment_report.md) | 財政部 vs 其他來源對齊檢查報告 |

## 開發與測試

```bash
python -m pytest python/tests/ -q          # 套件單元測試
python examples/check_segis_admin_topics.py # 行政部主題交叉驗證
python examples/check_tax_alignment.py      # 財政部對齊診斷
```

R 套件單元測試（需 R runtime + testthat）：
```R
testthat::test_dir("R/twliConsolidate/tests/testthat")
```

## 授權與引用

本專案的 Python / R 套件 API 設計沿用 [torrentpien/twli](https://github.com/torrentpien/twli)
（既有 R 套件）的命名與慣例：`liRef` / `liSum` / `liEqu` / `liShp`，方便已熟悉
twli 的研究者直接套用。

## 已知限制

1. **腳本預設範圍與 YAML 內容不一致**：`scripts/build_crosswalk.py` 內
   `YEARS_ROC = [110, 111, 112, 113, 114]`，僅 5 年。實際 YAML 涵蓋 18 年是
   先前手動擴增後產出的。日後維護需先把 `YEARS_ROC` 改回完整範圍。
2. **R 套件無 testthat 自動測試紀錄**：開發環境無 R runtime，R 套件 API 與
   Python 邏輯對齊但未跑單元測試。
3. **財政部 2024、原住民系列早於 2020 的資料不存在**：SEGIS 來源限制。
