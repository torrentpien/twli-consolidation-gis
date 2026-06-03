# SEGIS 多來源資料盤點與使用指南

> 本文件為 SEGIS 三來源、村里級 csv 的整合說明。  
> 整併套件相關背景請見 [`docs/plan_segis_multi_source.md`](plan_segis_multi_source.md)。
>
> **更新註記**：原住民系列 3 主題（人口統計、人口指標、十歲年齡組）依研究方向**已排除**，
> 不納入主要分析流程；SEGIS 仍保留其原始 csv (2020-2024)。

## 1. 來源結構

```
SEGIS按資料類型分/
├── 行政部/   採用 6 主題 (× 14 年, 100-113) + 排除 3 個原住民主題
│   ├── 行政區人口統計
│   ├── 行政區人口指標                  ← 衍生指標，不直接整併
│   ├── 行政區三段年齡組性別人口統計
│   ├── 行政區五歲年齡組性別人口統計
│   ├── 行政區十歲年齡組性別人口統計
│   ├── 行政區分齡兒童及少年性別人口統計
│   ├── (行政區原住民人口統計)         ← 排除，僅 109-113
│   ├── (行政區原住民人口指標)         ← 排除，僅 109-113
│   └── (行政區原住民十歲年齡組...)    ← 排除，僅 109-113
├── 教育部/   1 主題 × 14 年 (100-113)
│   └── 行政區15歲以上人口教育程度統計
└── 財政部/   1 主題 × 13 年 (100-112)
    └── 綜合所得稅所得總額申報統計
```

採用主題：**8 個**（行政部 6 + 教育部 1 + 財政部 1）。

## 2. Schema 共通結構

所有 csv 的左半邊欄位一致：

```
COUNTY_ID, COUNTY, TOWN_ID, TOWN, V_ID, VILLAGE, <variables>..., INFO_TIME
```

財政部多一個 `TAG` 欄位在最前（彙整列標籤，ingest 自動過濾）。

- **編碼**：絕大多數 UTF-8-BOM，少數年度為 CP950（ingest 自動偵測）
- **第 2 列**：中文欄位說明（ingest 自動跳過）
- **主鍵**：`V_ID`（村里代碼，與既有 4476 件 crosswalk YAML 完全相容）
- **INFO_TIME 格式**：人口類 `113Y12M`、教育/所得稅 `113Y`

## 3. 各主題欄位概覽

| 主題 | 欄位數 | 變數類型 | 整併規則 |
|---|---|---|---|
| 人口統計 | 4 | _CNT | sum |
| 三段年齡組 | 9 | _CNT (3 組 × 總/M/F) | sum |
| 五歲年齡組 | 63 | _CNT (21 組 × 總/M/F) | sum |
| 十歲年齡組 | 33 | _CNT (11 組 × 總/M/F) | sum |
| 分齡兒少 | 9 | _CNT (3 組 × 總/M/F) | sum |
| **人口指標** | 7 | RAT/CNT (性比例、戶量、密度、扶養比…) | **不直接整併，由 base recompute** |
| 教育程度 | 9 | _CNT (博士~不識字 9 級) | sum |
| 所得稅 | 8 | FLD01-08 (納稅單位、總額、平均、中位、Q1、Q3、SD、CV) | sum + recompute + keep_if_unique 混用 |

完整欄位定義見 [`scripts/vars_spec.py`](../scripts/vars_spec.py)。

## 4. 整併規則：三種策略

### 4.1 直接 sum（127 欄位 / 6 主題）
所有 _CNT 類欄位都可直接加總。整併後的 SAU 計數欄位仍可正常加總、比較跨年。

### 4.2 衍生指標 recompute（1 主題）
原始的「人口指標」csv 全是比率/密度等衍生欄位。直接整併（例如 weighted_mean）只是近似；正確做法是：

1. 把 base 主題（人口統計、三段年齡）各自 sum 整併
2. join 整併後寬表
3. 用公式 recompute 出指標

範例公式（[`vars_spec.py` DERIVED_FORMULAS](../scripts/vars_spec.py)）：
```
M_F_RAT          = M_CNT / F_CNT * 100
P_H_CNT          = P_CNT / H_CNT
DEPENDENCY_RAT   = (A0A14_CNT + A65UP_CNT) / A15A64_CNT * 100
A0A14_A15A65_RAT = A0A14_CNT / A15A64_CNT * 100   # 扶幼比
A65UP_A15A64_RAT = A65UP_CNT / A15A64_CNT * 100   # 扶老比
A65_A0A14_RAT    = A65UP_CNT / A0A14_CNT * 100    # 老化指數
```

`P_DEN`（人口密度）需 SHP 面積，待 task #12 demo 處理。

### 4.3 財政部特殊規則
| 欄位 | 規則 | 說明 |
|---|---|---|
| FLD01 納稅單位 | sum | |
| FLD02 綜合所得總額 | sum | |
| FLD03 平均 | recompute = FLD02/FLD01 | |
| FLD04 中位 / FLD05 Q1 / FLD06 Q3 / FLD07 SD / FLD08 CV | **keep_if_unique** | 樣本級分位/變異統計量無法從區級彙總精確重算；對受整併 SAU 標 NaN，對 1-member SAU（未整併）保留原值 |

## 5. 已知 raw csv 異常（非套件 bug，使用者需注意）

| # | 主題 | 異常 | 推測原因 |
|---|---|---|---|
| 1 | 行政部 分齡兒少 | 2020 年少 2 個 V_ID (10002110-007, 10008130-014) | 該村里該年無 18 歲以下兒少 |
| 2 | 財政部 | 部分年度有 V_ID 重複（如 2022 有 9 個 V_ID 對應兩個 VILLAGE 名、2023 有 1 個）| 疑亂碼造成 |
| 3 | 財政部 | 15 列 V_ID 末三碼 `-999`（如 64000030-999）| 鄉鎮無法分配的彙整列，**ingest 自動過濾** |

驗證腳本：[`examples/check_segis_admin_topics.py`](../examples/check_segis_admin_topics.py)。

## 6. 跨來源 join 注意事項

### 6.1 年度範圍不齊
- 行政部、教育部：100-113 (14 年)
- 財政部：100-112 (13 年)

joint panel 採取「主軸 LEFT JOIN」：以人口統計為主，財政部欄位在 113 為 NaN。

### 6.2 V_ID 覆蓋不齊
個別主題某些年份 raw csv 少幾個 V_ID（見 §5）。整併後 SAU panel 列數可能略少於主軸；join 後對應欄位為 NaN。

### 6.3 跨來源加總交叉驗證
- 行政部主題之間（P_CNT == 三段/五歲/十歲組總和、性別合計）：✓ 14 年全等
- 教育部 vs 行政部 15+ 歲人口：11 個年度 100% 完全相等；2016 微差 1、2021 微差 0.21%、2023 微差 6

## 7. Panel 規模

| Panel | 列數 | 結構 |
|---|---|---|
| 行政部 6 主題（個別）| 106,414 | 7601 SAU × 14 年（分齡兒少 106,412，2020 缺 2 個 SAU）|
| 教育部 | 106,414 | 7601 SAU × 14 年 |
| 財政部 | 98,648 | 7588 SAU × 13 年 |
| 跨來源寬表 | 106,414 × 39 欄 | 4 個來源在 (sau_id, year) join |

SAU 總數 **7601**（14 年 panel，跨年完全一致）。

## 8. 工具與 demo 速查表

### Ingest

```python
from scripts.ingest_segis import list_topics, ingest_topic

topics = list_topics()         # {ministry: {topic: folder_path}}
df = ingest_topic(topics["行政部"]["行政區人口統計"])
# df 含 V_ID, year, COUNTY..., 各變數欄位
```

### 整併（用集中宣告的 vars_spec）

```python
from scripts.vars_spec import INGEST_SPECS, topic_key
import twli_consolidate as tc

cw = tc.load_crosswalk("crosswalk/village_changes.yaml")
lineage = tc.build_lineage(cw, year_range=(2011, 2024))
spec = INGEST_SPECS[topic_key("行政部", "行政區人口統計")]
out = tc.consolidate_panel(df, vid_col="V_ID", year_col="year",
                            vars_spec=spec, lineage=lineage)
```

### 既有 demo / 驗證腳本

| 路徑 | 用途 |
|---|---|
| `examples/demo_segis_panel.py` | 行政部・人口統計 14 年 SAU panel |
| `examples/demo_education_panel.py` | 教育部 14 年 panel + 交叉驗證 |
| `examples/demo_tax_panel.py` | 財政部 13 年 panel + keep_if_unique 驗證 |
| `examples/demo_multi_source_panel.py` | **跨來源寬表 panel**（4 主題、39 欄、14 年） |
| `examples/check_segis_admin_topics.py` | 行政部 6 主題完整驗證（主題內 + 主題間 + 異常記錄） |
| `scripts/ingest_segis.py` | 通用 ingest 函式庫；可直接執行列出主題摘要 |
| `scripts/vars_spec.py` | 集中宣告的整併規則 |

## 9. 與既有 `docs/data_inventory.md` 的關係

`data_inventory.md` 記錄 Drive 上 21 個時點快照與 SHP 對應，是**資料來源層**的盤點。本文件是已整理進 git 的 SEGIS **資料工程層**的說明。兩者並存。
