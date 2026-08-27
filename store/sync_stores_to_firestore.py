"""
把目前未作廢、未過期的特約商店清單同步到 Firestore（供 §5 存取控制後端 /stores 使用）。
用法: python sync_stores_to_firestore.py

跟 deploy_store.py 完全獨立，不共用也不修改它——deploy_store.py 繼續照舊把
stores.json scp 到 Ubuntu 主機給公開查詢頁用；這支另外把同一份資料送到 Firestore，
給之後上線的 LIFF 驗證查詢頁用（見 sdd3.md §5 實作計畫）。

本機端完全不持有 Firebase 憑證，只用共用密鑰打 Cloud Functions 的 admin 端點，
見 sdd3.md §5 實作計畫「架構總覽」。
"""
import os
from datetime import datetime

import requests
import urllib3
from dotenv import load_dotenv

from notes_store import fetch_active_stores

load_dotenv()

# 院內網路對外 HTTPS 會被自簽憑證攔截（跟 upload_joomla.py/auto_checkin.py 遇到的是同一個環境限制），
# 略過憑證驗證，見 README.md「注意事項」。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FUNCTIONS_BASE_URL = os.getenv("STORE_AUTH_FUNCTIONS_BASE_URL")
ADMIN_SHARED_SECRET = os.getenv("ADMIN_SHARED_SECRET")

if not all([FUNCTIONS_BASE_URL, ADMIN_SHARED_SECRET]):
    raise SystemExit("請確認 .env 已填寫 STORE_AUTH_FUNCTIONS_BASE_URL / ADMIN_SHARED_SECRET")

stores = fetch_active_stores()
payload = {
    "generated_at": datetime.now().isoformat(timespec="minutes"),
    "stores": stores,
}

resp = requests.post(
    f"{FUNCTIONS_BASE_URL}/admin_push_stores",
    json=payload,
    headers={"X-Admin-Secret": ADMIN_SHARED_SECRET},
    timeout=30,
    verify=False,
)

if resp.status_code != 200:
    raise SystemExit(f"同步失敗（HTTP {resp.status_code}）：{resp.text}")

print(f"已同步 {len(stores)} 筆到 Firestore：{resp.json()}")
