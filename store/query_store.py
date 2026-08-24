from datetime import datetime
import os, csv
from notes_store import fetch_active_stores

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

stores = fetch_active_stores()
for s in stores:
    s["expire"] = datetime.fromisoformat(s["expire"]).strftime("%Y/%m/%d") if s["expire"] else "無到期日"

# ── 類別篩選 ──────────────────────────────────────────
kinds = sorted({s["kind"] for s in stores if s["kind"]})
print("可選類別：" + "、".join(kinds))
choice = input("輸入類別篩選（直接 Enter = 全部）：").strip().lstrip("﻿")
if choice:
    stores = [s for s in stores if s["kind"] == choice]

for s in stores:
    print(f"[{s['kind']}] {s['name']}")
    print(f"  電話：{s['tel']}")
    print(f"  地址：{s['address']}")
    print(f"  內容：{s['contents']}")
    print(f"  到期：{s['expire']}")
    print()

print(f"共 {len(stores)} 筆（未作廢、未過期）")

# ── 輸出 CSV ──────────────────────────────────────────
export = input("是否輸出 CSV？(y/N)：").strip().lstrip("﻿").lower()
if export == "y":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUTPUT_DIR, f"特約商店_{choice or '全部'}_{datetime.now():%Y%m%d}.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["kind", "name", "tel", "address", "contents", "expire"])
        writer.writerow({"kind": "類別", "name": "商店名稱", "tel": "電話", "address": "地址", "contents": "內容", "expire": "到期日"})
        writer.writerows(stores)
    print(f"已輸出：{csv_path}")
