# SDD4 — 福利公告查詢（LINE@ 圖文選單第二項功能）

規格驅動開發文件。記錄「職工福利行政小組」院內公佈欄公告，透過 LINE@ 圖文選單提供給同仁查詢的功能設計，2026-08-27 完成並上線。

---

## 1. 背景與問題

職工福利行政小組平常透過院內公佈欄（另一個 Notes 資料庫 `mdabulletin.nsf`，不是 sdd3.md 特約商店那個 `ContributingStore.nsf`）發布福委相關公告（好康優惠轉知、中秋禮盒預購等）。這些公告同仁要自己去公佈欄翻找，不方便；sdd3.md §5 已經做好一套 LINE@ + LIFF 的身分驗證機制（原本給特約商店查詢用），這裡延伸同一套驗證，讓同仁可以直接在 LINE 裡查公告。

## 2. 目標 / 非目標

**目標**
- 從 `mdabulletin.nsf` 匯出「職工福利行政小組」發布、未過期的公告（標題、內容、公告日、效期），含內嵌圖片。
- 部署成一個限本院同仁查詢的頁面，跟特約商店查詢頁共用同一套 LINE@ + LIFF 驗證身分（sdd3.md §5），不用重新驗證一次。
- 資料**不進 Firebase**——JSON + 圖片存在 Ubuntu 網站伺服器，Cloud Functions 驗證身分後代替使用者去抓，瀏覽器/LIFF 頁本身不知道實際網址。

**非目標**
- 不做公告的新增/編輯（純查詢，公告本身仍在 Notes 公佈欄那邊維護）。
- 不做圖文選單本身的設定（LINE Official Account Manager 手動設定，非本專案程式碼處理）。
- 不特別過濾公告裡的敏感內容——公告本身定位是「同仁可公開看到的訊息轉知」，不是高敏感資料。

## 3. 使用者情境

**匯出/部署（維護者視角）**
> 職工福利小組在公佈欄發了新公告，想同步到 LINE 查詢頁。執行 `deploy_bulletin.py`，程式會去 Notes 公佈欄撈「職工福利行政小組」發的、未過期的公告，含內嵌圖片，透過 SSH 金鑰把 JSON 跟圖片丟到網站伺服器一個沒有頁面連結的目錄下。

**查詢（同仁視角）**
> 我已經是特約商店查詢頁的驗證用戶，圖文選單點「福利公告查詢」，因為已經驗證過，直接看到公告列表，不用再輸入一次姓名跟驗證碼。如果我是第一次用（還沒驗證過），一樣要輸入姓名/Notes ID + 本期驗證碼才能看。

## 4. 設計

### 4.1 資料撈取與篩選（`bulletin/notes_bulletin.py` → `fetch_active_bulletins()`）

| 項目 | 內容 |
|---|---|
| 資料來源 | Notes 伺服器 `mda/medicine/Tzuchi`，資料庫 `OAuse\mdabulletin.nsf`，View「花蓮慈院」 |
| 篩選條件 | `fd_AncDepartment == "職工福利行政小組"`，其他部門的公告一律不收 |
| 過期判斷 | `fd_AncExpDate` 視為效期，+8 小時校正 UTC 後取日期，早於今天者排除 |
| 欄位 | `subject`（`fd_Subject`）／`content`（`fd_Contain` 純文字）／`date`（`fd_AncDate`）／`expire`（`fd_AncExpDate`）／`images`（內嵌圖片檔名列表） |
| 圖片擷取 | 沿用 `query_news.py` 既有手法：`notes.CreateDXLExporter()` 把整份文件匯出 DXL XML，解析裡面的 `jpeg`/`gif`/`png` 節點，base64 解碼存檔，檔名格式 `{UniversalID}_{序號}.{副檔名}` |
| 排序 | 依公告日新到舊 |

### 4.2 部署（`bulletin/deploy_bulletin.py`）

| 步驟 | 內容 |
|---|---|
| ① 匯出 | JSON 寫到 `bulletin/output/bulletin.json`，圖片存到 `bulletin/output/images/` |
| ② 確保遠端目錄 | `ssh mkdir -p {STORE_REMOTE_PATH}/{BULLETIN_SECRET_SLUG}/images` |
| ③ 上傳 | scp `bulletin.json` + 所有圖片到該目錄，單檔失敗重試一次 |
| 存取控制 | `BULLETIN_SECRET_SLUG` 是一組 24 bytes 亂數產生的隨機字串（`.env` 跟 Cloud Functions 的 secret 要一致），沒有任何頁面連到這個路徑，目錄列表本身回 403（已實測確認） |

### 4.3 後端：Cloud Functions `bulletin` 端點（`firebase/functions/main.py`）

沿用 sdd3.md §5 已經上線的身分驗證系統（`verify` 端點、Firestore `lineAuth`），新增共用檢查函式 `_require_verified_user()`（`stores` 端點也改用這個，避免兩處邏輯各自維護、之後改壞其中一個沒同步）：

1. 驗證 `Authorization: Bearer <LINE ID token>`，確認是真的 LINE 登入身分
2. 查 Firestore `lineAuth.status == "verified"`，沒通過直接拒絕（403）
3. 通過後，伺服器端 `requests.get()` 抓 `{BULLETIN_BASE_URL}/{BULLETIN_SECRET_SLUG}/bulletin.json`（`BULLETIN_BASE_URL` 是一般環境變數，`BULLETIN_SECRET_SLUG` 是 Cloud Functions secret）
4. 把回傳資料裡每則公告的 `images`（檔名）補成完整網址後回傳給呼叫者

### 4.4 前端（`store/web/liff/bulletin.html`）

跟 `store/web/liff/index.html`（特約商店查詢）結構相同但**是獨立檔案，不共用程式碼**（sdd3.md 的既有慣例——各進入點獨立維護，不互相耦合）：`liff.init()` → 未登入則 `liff.login()` → 已登入嘗試呼叫 `/bulletin`（帶 ID token）→ 成功直接顯示公告列表（含圖片），失敗（未驗證）顯示姓名/驗證碼表單，驗證成功後重新載入。

**LIFF 進入點注意事項**：一個 LIFF ID 只對應一個固定 Endpoint URL（目前是 `index.html`），所以圖文選單「福利公告查詢」按鈕要直接連 `https://hlm.tzuchi.com.tw/store/liff/bulletin.html` 完整網址，不能用 `https://liff.line.me/{LIFF_ID}` 短網址（那個永遠導去 Endpoint URL 設定的頁面）。`liff.init()` 用同一組 LIFF ID 在任何頁面呼叫都能正常登入，不需要為這個功能另外申請新的 LIFF app。

## 5. 安全性

- 公告資料本身敏感度低（院內福委轉知訊息），跟 sdd3.md 特約商店合約資料不同，因此接受「路徑亂碼即防護」這個較低強度的保護（跟驗證碼本身的防護等級一致），不做 Apache 帳密或簽章驗證。
- 圖片網址在使用者拿到 `/bulletin` 回傳的 JSON 之後即為明碼網址，理論上可以脫離驗證直接分享圖片本身——這是刻意接受的殘餘風險，跟 sdd3.md §5.5 對驗證碼外流風險的態度一致。
- Ubuntu 目錄列表已實測確認回 403，不會不小心洩漏檔名清單。

## 6. 已知限制 / 待確認

- `fetch_active_bulletins()` 目前用**整份文件 DXL 匯出**擷取圖片，效能上如果公告很多、附件很大，執行時間會拉長——目前 18 則公告、30 張圖片實測沒有明顯延遲，先不處理，量大再優化。
- 公告內容 `fd_Contain` 讀出來是純文字（RichText 的 `.Text`屬性），原始的字型/顏色/連結等格式會遺失，只保留文字跟圖片。
- `BULLETIN_SECRET_SLUG` 換過的話，本機 `.env` 跟 Cloud Functions secret 要記得同步更新，兩邊沒有自動同步機制。

## 7. 驗收標準

- [x] 可正確篩選出「職工福利行政小組」發布、未過期的公告
- [x] 內嵌圖片可正確擷取並另存成檔案（實測：18 則公告、30 張圖片，圖片內容確認正常）
- [x] 部署後的 JSON/圖片路徑目錄列表回 403，猜錯路徑回 404（已實測）
- [x] Cloud Functions `bulletin` 端點沒帶身分憑證會被拒絕（實測回 401）
- [ ] 真實 LINE 帳號完整走過「驗證 → 查看公告 → 圖片正常顯示」全流程（尚待手機實測）
- [ ] 圖文選單「福利公告查詢」按鈕正確連到 `bulletin.html`（尚待使用者在 LINE Official Account Manager 設定並測試）
