"""
匯出特約商店資料給院內查詢網頁使用
用法: python export_store_json.py
"""
import json
import os
from datetime import datetime
from notes_store import fetch_active_stores

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
JSON_PATH  = os.path.join(OUTPUT_DIR, "stores.json")

os.makedirs(OUTPUT_DIR, exist_ok=True)

stores = fetch_active_stores()
payload = {
    "generated_at": datetime.now().isoformat(timespec="minutes"),
    "stores": stores,
}

with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

print(f"已匯出 {len(stores)} 筆 -> {JSON_PATH}")
