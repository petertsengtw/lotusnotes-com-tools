# SDD3 — 特約商店查詢頁自動部署

規格驅動開發文件。本文件回溯記錄「從 Lotus Notes 特約商店資料庫匯出清單、部署成靜態查詢網頁」這項功能的現況規格。

---

## 1. 背景與問題

院內同仁常需要查詢目前有哪些特約商店優惠，原本清單只存在 Lotus Notes 的 `ContributingStore.nsf`，同仁若沒有 Notes 用戶端或不方便用手機查 Notes，取得資訊不方便。本功能把資料庫內容匯出成一個免登入、手機可查的靜態網頁。

## 2. 目標 / 非目標

**目標**
- 從 `ContributingStore.nsf` 匯出「未作廢、未過期」的特約商店清單。
- 部署成一個不需帳密、手機瀏覽器可查詢（關鍵字搜尋 + 類別篩選）的靜態網頁。
- 網頁放在既有 Joomla 網站伺服器上，但**不經過 Joomla 的資料庫或文章系統**，只用檔案系統層級的靜態檔案部署。

**非目標**
- 不做網頁端的新增/編輯功能（`join.html` 是純靜態說明頁，不是表單送出到後端）。
- 不做存取控制／登入驗證（資料屬店家自願提供給同仁的優惠資訊，敏感度低，見 README「注意事項」）。
- 不做排程自動化（見「6. 邊界情境」，Notes ID 密碼互動限制與新聞稿擷取功能相同）。
- 不透過 Joomla 內容管理介面呈現，因此不使用、也不影響 Joomla 既有的文章、分類、外掛設定。

## 3. 使用者情境

> 我想讓同仁不用開 Notes，直接用手機查特約商店。執行 `deploy_store.py`，程式會去 Notes 撈最新清單、轉成 JSON、透過 SSH 金鑰把查詢頁的檔案跟 JSON 一起丟到網站伺服器的指定目錄，同仁打開網址就能直接搜尋、篩選類別。

## 4. 設計

### 4.1 資料撈取與篩選（`notes_store.py` → `fetch_active_stores()`）

| 項目 | 內容 |
|---|---|
| 資料來源 | Notes 伺服器 `mdaapa/medicine/Tzuchi`，資料庫 `OAUse\ContributingStore.nsf`，View「依商店」 |
| 排除條件 | `fd_Cancel == "1"`（已作廢）直接排除 |
| 過期判斷 | `fd_ChangeDate` 視為到期日，+8 小時校正 UTC 後取日期，早於今天者排除；欄位不存在則視為無到期日（永久有效） |
| 欄位 | `name`／`kind`／`tel`／`address`／`contents`／`expire`（ISO 日期字串或 `null`） |
| 排序 | 依 `(kind, name)` |

### 4.2 匯出 JSON（兩個入口，邏輯各自獨立）

- `export_store_json.py`：獨立手動匯出，寫到 `store/output/stores.json`，不部署（供本機檢查用）。
- `deploy_store.py`：內部直接呼叫 `fetch_active_stores()`（不呼叫前者，邏輯重複但獨立維護），匯出後緊接部署流程。

### 4.3 部署（`deploy_store.py`）

| 步驟 | 內容 |
|---|---|
| ① 產生 JSON | 寫入 `store/output/stores.json`，含 `generated_at` 時間戳 |
| ② 確保遠端目錄 | `ssh mkdir -p {STORE_REMOTE_PATH}` |
| ③ 上傳檔案 | `scp` 依序上傳 `index.html`／`join.html`／`qa.html`／`style.css`／`stores.json`，單檔失敗重試一次，仍失敗則整體中止（`check=True`） |
| 連線方式 | SSH 金鑰登入（非密碼），金鑰路徑來自 `.env` 的 `SFTP_KEY_PATH` |
| 32-bit 特例 | 因專案是 32-bit Python，會被 WOW64 導向 `SysWOW64`（無 OpenSSH），改用 `C:\Windows\Sysnative\OpenSSH` 繞過導向找到真正的 64-bit `ssh.exe`/`scp.exe` |

### 4.4 查詢頁前端（`store/web/`）

| 檔案 | 用途 |
|---|---|
| `index.html` | 主查詢頁：頁面載入時 `fetch("./stores.json")`，前端關鍵字搜尋（比對名稱/地址/內容）+ 類別下拉篩選，純前端運算、無後端 API |
| `join.html` | 加入特約店家的說明頁（靜態內容） |
| `qa.html` | 常見問題（靜態內容） |
| `style.css` | 共用樣式 |

### 4.5 流程圖

```mermaid
flowchart TD
    A([手動執行 deploy_store.py]) --> B[Lotus Notes COM API]
    B --> C[(ContributingStore.nsf 特約商店資料庫)]
    C --> D{fd_Cancel=1?\n或已過期?}
    D -- 是 --> E[排除]
    D -- 否 --> F[加入清單]
    F --> G[寫入 store/output/stores.json]
    G --> H[ssh mkdir -p 遠端目錄]
    H --> I[scp 上傳 web/*.html + style.css + stores.json]
    I --> J([Ubuntu 網站伺服器\n靜態檔案更新完成])
    J --> K([同仁瀏覽器打開網址\n前端 fetch stores.json 顯示查詢頁])
```

## 5. 對 Joomla 正式站的影響面

與新聞稿上傳功能不同，本功能**完全不經過 Joomla 的 REST API 或資料庫**，只是把靜態檔案透過 SSH/SCP 放進網站伺服器檔案系統下的 `STORE_REMOTE_PATH` 子目錄（掛在 Joomla 網站底下的一個獨立靜態頁面）。因此：
- 不會影響 Joomla 現有文章、分類、選單、外掛或後台設定。
- 部署失敗（SSH/SCP 錯誤）最多只影響 `STORE_REMOTE_PATH` 這個子目錄本身，不會波及 Joomla 其他部分。
- 風險僅限於：部署路徑設定錯誤時可能覆蓋到不該覆蓋的目錄（見「7. 已知問題」7.1）。

## 6. 邊界情境

| 情境 | 現況行為 |
|---|---|
| `.env` 缺 `SFTP_HOST`/`SFTP_USER`/`SFTP_KEY_PATH`/`STORE_REMOTE_PATH` 任一項 | 啟動時直接 `raise SystemExit`，不會嘗試連線 |
| 遠端目錄不存在 | 自動 `mkdir -p` 建立 |
| SCP 單檔上傳失敗（網路抖動） | 自動重試一次；第二次仍失敗則整支腳本中止（`check=True` 拋例外），已上傳的檔案不會回滾 |
| Notes ID 未開放「允許其他 Notes 程式使用此密碼」 | `Initialize()` 會跳出互動式密碼視窗，**無法無人值守排程**，必須手動在畫面上輸入密碼（見 README） |
| 商店資料 `fd_ChangeDate` 欄位不存在 | 視為無到期日，永久顯示在清單中 |
| 查詢頁無登入驗證 | 任何知道網址的人都能查詢（設計上刻意如此，資料低敏感度） |
| `STORE_REMOTE_PATH` 設定錯誤（指到非預期目錄） | 腳本不會檢查目的地是否合理，會直接把檔案 scp 上去——**設定錯誤時有覆蓋錯誤目錄的風險**（見已知問題 7.1） |

## 7. 已知問題 / 技術債

| # | 問題 | 影響 | 建議 |
|---|---|---|---|
| 7.1 | `STORE_REMOTE_PATH` 純靠 `.env` 手動設定，程式不做任何合理性檢查（例如是否為空字串、是否為根目錄） | 中（設定錯誤時可能覆蓋錯誤位置的檔案） | 部署前加一道基本檢查（例如禁止空字串或 `/`），或至少在輸出中明確印出即將部署的完整目的地路徑供人工確認 |
| 7.2 | `export_store_json.py` 與 `deploy_store.py` 各自獨立呼叫 `fetch_active_stores()`、各自組出幾乎相同的 JSON 輸出邏輯 | 低（重複程式碼，非功能性風險） | 可考慮讓 `deploy_store.py` 直接沿用 `export_store_json.py` 的匯出邏輯，而不是重寫一份 |
| 7.3 | 目前無法排程，只能手動執行並手動輸入 Notes 密碼 | 中（資料新鮮度依賴人工記得執行） | 待 Notes ID 開放「允許其他程式使用此密碼」後，可比照自動打卡功能的排程模式（Windows 工作排程器）自動化 |

## 8. 驗收標準

- [x] 可正確篩選出未作廢、未過期的商店清單
- [x] `stores.json` 可正確產出並含 `generated_at` 時間戳
- [x] SSH 金鑰登入可成功、遠端目錄不存在時可自動建立
- [x] 查詢頁可用關鍵字與類別篩選正確顯示資料
- [x] 已實際部署上線（見專案 commit 記錄「新增特約商店查詢/匯出/部署工具與網頁」）
- [ ] SCP 部署失敗時的重試與中止行為尚未有意外情境下的實測記錄（僅程式邏輯層面確認）

## 9. 待確認 / 後續可討論事項

- 是否要在 `deploy_store.py` 加上部署目的地的人工確認提示（列印完整路徑、輸入 y 才繼續），降低 7.1 的風險。
- 若未來 Notes ID 開放非互動登入，是否要排程自動每日/每週跑一次 `deploy_store.py`，讓查詢頁資料保持最新。
- `export_store_json.py` 與 `deploy_store.py` 的重複邏輯要不要合併（7.2）。
