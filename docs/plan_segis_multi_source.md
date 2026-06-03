# SEGIS 多來源資料整併規劃（提案 v2，v3 更新註記）

> v1 誤認資料為鄉鎮市區級；資料已替換為村里級，v2 整體大幅簡化。  
> **v3 更新**（資料補齊到 14 年 + 排除原住民系列）：見最末段 §8。

## 1. 新增資料現況

`SEGIS按資料類型分/` 下三個來源、共 **11 個主題、53 個 csv**，全部 **村里級**（主鍵 V_ID）、**UTF-8-BOM 編碼**：

```
SEGIS按資料類型分/
├── 行政部/   (9 主題 × 5 年 = 45 csv，皆 109–113)
│   ├── 行政區人口統計        ← 與既有 data_population/109-113 完全相同
│   ├── 行政區人口指標
│   ├── 行政區三段年齡組性別人口統計
│   ├── 行政區五歲年齡組性別人口統計
│   ├── 行政區十歲年齡組性別人口統計
│   ├── 行政區分齡兒童及少年性別人口統計
│   ├── 行政區原住民人口統計
│   ├── 行政區原住民人口指標
│   └── 行政區原住民十歲年齡組性別人口統計
├── 教育部/   (1 主題 × 5 年 = 5 csv，109–113)
│   └── 行政區15歲以上人口教育程度統計
└── 財政部/   (1 主題 × 3 年 = 3 csv，109–111)
    └── 綜合所得稅所得總額申報統計
```

資料量：**11 MB 全部加起來**。

## 2. ✓ 完全相容於既有套件

| 維度 | 既有 panel demo (data_population) | SEGIS 新資料 |
|---|---|---|
| 主鍵 | V_ID | V_ID ✓ |
| 編碼 | CP950/UTF-8 混雜 | 全部 UTF-8-BOM ✓ |
| Schema 左半邊 | COUNTY_ID/COUNTY/TOWN_ID/TOWN/V_ID/VILLAGE | 同上 ✓（財政部多 TAG） |
| 整併紀錄 | crosswalk/village_changes.yaml (4476 件) | **同一份 YAML 完全適用** ✓ |

**結論：不需要做任何 town-level crosswalk、不需要新套件 API**。直接重用 `consolidate_panel` / `build_lineage` / `li_sum` / `li_equ`，把不同主題的 csv 餵進去即可。

## 3. 既有 data_population/ 與新資料的關係

| 年度 | data_population/ | SEGIS/行政部/人口統計 |
|---|---|---|
| 107 | ✓ | ✗（SEGIS 從 109 起）|
| 108 | ✓ | ✗ |
| 109–113 | ✓ | ✓（資料完全相同，僅編碼/換行差異）|

**建議**：
- 移除 `data_population/109-113` 五個檔（與 SEGIS 重複）
- 保留 `data_population/107-108` 兩個檔（SEGIS 沒有）
- 之後分析以 SEGIS 為主來源；要拉早於 109 的年度需另外從 Drive 補

## 4. 三來源各別處理

### 4.1 行政部（9 主題）

| 主題 | 欄位 | 整併方式 |
|---|---|---|
| 人口統計 | H_CNT, P_CNT, M_CNT, F_CNT | **sum** |
| 三段/五歲/十歲年齡組 | A?A?_CNT (含 _M/_F) | **sum** |
| 分齡兒少 | _CNT 系列 | **sum** |
| 原住民人口統計、原住民十歲 | O_*_CNT | **sum** |
| **人口指標** | M_F_RAT, P_H_CNT, P_DEN, DEPENDENCY_RAT 等 | **不直接整併** → 由人口統計 + 年齡組 sum 後 **recompute**（人口密度另需 SHP 面積）|
| **原住民人口指標** | O_PER, O_DEPENDENCY_PER 等 | **不直接整併** → 由原住民人口統計 + 年齡組 sum 後 **recompute** |

### 4.2 教育部（1 主題）

- 9 個教育程度 _CNT（博士、碩士、大學、專科、高中職、國中初職、小學、自修、不識字）
- 全部 **sum**
- 交叉驗證：9 欄位加總 ≈ 行政部 15+ 歲人口（從三段年齡 A15A64 + A65UP 推算）

### 4.3 財政部（1 主題、最特殊）

- schema 多一個 `TAG` 欄位在最前
- 欄位語意：
  - FLD01 納稅單位、FLD02 綜合所得總額 → **sum**
  - FLD03 平均、FLD04 中位、FLD05 第一分位、FLD06 第三分位、FLD07 標準差、FLD08 變異係數
- 整併規則：
  - 平均 (FLD03) 可由 `FLD02 / FLD01` **recompute**
  - 中位、Q1、Q3、SD、CV **無法從區級彙總精確重算**
  - 但 99% 的村里在 SAU 內是 unique（沒被整併），這些指標可直接保留
  - 只有少數 SAU 真實整併過（鹿港頂厝里、八德重劃等），這些 SAU 的分位數需要決議：標 NaN / 加權近似 / 捨棄

## 5. 工作項目（修訂後）

> Phase 1（鄉鎮市區 crosswalk）已刪除，不需要。

### Phase A: 基礎 ingest

| # | 工作 | task id |
|---|---|---|
| A1 | `scripts/ingest_segis.py`：通用 ingest，吃任一主題資料夾，回傳 long-format dataframe | #4 |
| A2 | 處理 `data_population/` 重複資料（109-113 五檔移除或保留待議）| #11 |

### Phase B: 行政部多主題 demo

| # | 工作 | task id |
|---|---|---|
| B1 | `examples/demo_segis_panel.py`：人口統計 5 年 (109-113) SAU panel（最小可動範例）| #5 |
| B2 | 各主題 vars_spec 設計（特別處理人口指標）| #6 |
| B3 | 人口指標重算 demo：sum 人口統計+年齡組後 recompute 出指標 | #12 |
| B4 | 行政部 9 主題驗證 | #7 |

### Phase C: 教育部與財政部

| # | 工作 | task id |
|---|---|---|
| C1 | 教育部 ingest + 驗證（與行政部 15+ 歲交叉比對）| #8 |
| C2 | 財政部 ingest + 過濾 TAG + 分位數策略 | #9 |

### Phase D: 整合

| # | 工作 | task id |
|---|---|---|
| D1 | 跨來源 join：人口統計 + 教育程度 + 所得稅 串成寬表 panel | #10 |
| D2 | 更新 `docs/data_inventory.md` 涵蓋 SEGIS | #10 |

## 6. 待確認關鍵決策

### Q1. **既有 data_population/109-113 五個檔怎麼處理**？
- (a) 移除（與 SEGIS 重複），改以 SEGIS 為唯一來源 

### Q2. **人口指標如何整併**？
- (a) **不直接整併指標 csv**，改從「人口統計 + 年齡組」sum 後重算指標欄位（精確）— **推薦**

### Q3. **財政部 FLD03-08（中位/Q1/Q3/SD/CV）如何處理**？
- (a) 受整併影響的 SAU 標 `NaN`，未整併的 SAU 保留原值 — **推薦**

### Q4. **SEGIS 資料 commit 進 git**？
資料量 11 MB，量不大可全部進。
- (a) 全部 commit

### Q5. **優先順序**？
- (a) 先做 Phase A + B1（最小可動範例），驗證流程通了再做後面 

## 7. 工程量估計（修訂後）

| Phase | 預估 |
|---|---|
| Phase A | 1 個 commit |
| Phase B | 2–3 個 commit |
| Phase C | 1–2 個 commit |
| Phase D | 1 個 commit |
| **合計** | **5–7 個 commit** |

（v1 估 8–14 個 commit；村里級對齊後省下鄉鎮市區 crosswalk 建構工作）

---

## 8. v3 更新（資料補齊 + 排除原住民系列）

於 Phase B/C/D 全部完成後，使用者更新了 SEGIS 資料夾：

### 8.1 範圍變更

| 維度 | v2 範圍 | v3 範圍 |
|---|---|---|
| 行政部非原住民主題 (6 個) | 109-113 (5 年) | **100-113 (14 年)** |
| 行政部原住民主題 (3 個) | 109-113 | **依研究方向排除**（仍保留原始 csv） |
| 教育部 | 109-113 (5 年) | **100-113 (14 年)** |
| 財政部 | 109-111 (3 年) | **100-112 (13 年)** |

### 8.2 對程式碼的影響

- `scripts/vars_spec.py`：原住民 3 個 INGEST_SPECS 與 1 個 DERIVED_FORMULAS 條目移除；新增 `SKIPPED_TOPICS` 註明排除原因
- `examples/demo_multi_source_panel.py`：TOPICS 列表移除 `ip`，year_range 改自動偵測
- `examples/check_segis_admin_topics.py`：direct_topics 移除原住民 2 主題，B2/C5/C6/D2/D3 等原住民相關驗證移除；新增 D1 跨年版 V_ID 覆蓋檢查（分齡兒少）
- `data_population/107-108`：與 SEGIS 重複，移除（SEGIS 已涵蓋 100-113 全年度）
- `examples/demo_multiyear_panel.py`、`examples/check_panel_integrity.py`：被 SEGIS 14 年版完全涵蓋，移除

### 8.3 v3 驗證結果

- 14 年 panel：**7601 SAU × 14 年 = 106,414 列**（5 年版是 7714 SAU；增加的早期年度涵蓋更多整併事件，連通分量數降低）
- 跨年 SAU 集合完全一致（5 個非分齡兒少主題）
- 全國 P_CNT raw vs SAU diff = 0（14 年全等）
- 主題間加總交叉驗證 C1-C4：14 年全 ✓
- 教育部 9 欄總和 vs 行政部 15+ 歲人口：11 個年度 100% 相等、2016/2021/2023 微差 < 0.21%

### 8.4 新發現異常

- 分齡兒少 2020 缺 2 個 V_ID 與 v2 觀察一致
- 財政部 2022 年 9 個 V_ID 重複、2023 年 1 個 V_ID 重複（疑亂碼）
- 財政部 2024 整年無資料（資料只到 112）

更詳細的當前狀況、欄位與工具，見 [`docs/segis_inventory.md`](segis_inventory.md)。

