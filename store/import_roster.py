"""
匯入季度在職名單，覆核目前已驗證的 LINE 使用者是否還在職（sdd3.md §5.7）。
用法:
    python import_roster.py <名單csv路徑>              # 只印出差異報告，不會真的撤銷
    python import_roster.py <名單csv路徑> --commit      # 確認報告沒問題後，才真的送出撤銷
    python import_roster.py <名單csv路徑> --commit --force   # 名單筆數過少的防呆檢查也要略過時才加

CSV 只要求有一個姓名欄位，欄名可以是「姓名」或「name」（其他欄位會被忽略）。

比對邏輯是暫定方案：季度名單真實欄位格式 sdd3.md §10 還沒確認，這裡先用「去除
常見縣市地區前綴後比對姓名」當容錯規則，等名單格式確認後可能需要調整（呼應
firebase/functions/roster_match.py 的同一份說明）。

實際比對計算在 Cloud Functions 那端做（admin_import_roster），這支只負責讀本機
CSV、做基本格式檢查、把結果印出來——本機依這個安全模型本來就不該直接碰 Firestore。
"""
import argparse
import csv
import os
import sys

import requests
import urllib3
from dotenv import load_dotenv

load_dotenv()

# 院內網路對外 HTTPS 會被自簽憑證攔截（跟 upload_joomla.py/auto_checkin.py 遇到的是同一個環境限制），
# 略過憑證驗證，見 README.md「注意事項」。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FUNCTIONS_BASE_URL = os.getenv("STORE_AUTH_FUNCTIONS_BASE_URL")
ADMIN_SHARED_SECRET = os.getenv("ADMIN_SHARED_SECRET")

NAME_HEADER_CANDIDATES = ("姓名", "name", "Name")


def read_roster_csv(path: str) -> list:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit(f"{path} 看起來是空檔案")

        name_field = next((h for h in NAME_HEADER_CANDIDATES if h in reader.fieldnames), None)
        if not name_field:
            raise SystemExit(
                f"找不到姓名欄位，CSV 標題列必須包含「姓名」或「name」其中一個，"
                f"目前讀到的欄位是：{reader.fieldnames}"
            )

        roster = []
        for row in reader:
            name = (row.get(name_field) or "").strip()
            if name:
                roster.append({"name": name})
        return roster


def call_admin_import_roster(roster: list, commit: bool, force: bool) -> dict:
    resp = requests.post(
        f"{FUNCTIONS_BASE_URL}/admin_import_roster",
        json={"roster": roster, "commit": commit, "force": force},
        headers={"X-Admin-Secret": ADMIN_SHARED_SECRET},
        timeout=30,
        verify=False,
    )
    body = resp.json()
    if resp.status_code not in (200, 400):
        raise SystemExit(f"呼叫失敗（HTTP {resp.status_code}）：{resp.text}")
    return body


def print_report(result: dict):
    print(f"名單筆數：{result.get('rosterCount')}　目前已驗證人數：{result.get('verifiedCount')}")
    if result.get("blocked"):
        print(f"已擋下，未執行任何動作：{result.get('reason')}")
        return
    matched = result.get("matched", [])
    to_revoke = result.get("toRevoke", [])
    print(f"比對到在職：{len(matched)} 人")
    print(f"建議撤銷（名單中找不到）：{len(to_revoke)} 人")
    for user in to_revoke:
        print(f"  - notesId={user.get('notesId')!r} lineUserId={user.get('lineUserId')}")
    if result.get("committed"):
        print("已送出撤銷。")
    elif to_revoke:
        print("這是 dry-run，尚未真的撤銷；確認名單無誤後加 --commit 再執行一次。")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roster_csv", help="季度在職名單 CSV 路徑")
    parser.add_argument("--commit", action="store_true", help="確認報告無誤後，真的送出撤銷（預設只 dry-run）")
    parser.add_argument("--force", action="store_true", help="略過「名單筆數過少」的防呆檢查")
    args = parser.parse_args()

    if not all([FUNCTIONS_BASE_URL, ADMIN_SHARED_SECRET]):
        raise SystemExit("請確認 .env 已填寫 STORE_AUTH_FUNCTIONS_BASE_URL / ADMIN_SHARED_SECRET")

    if not os.path.exists(args.roster_csv):
        raise SystemExit(f"找不到檔案：{args.roster_csv}")

    roster = read_roster_csv(args.roster_csv)
    if not roster:
        raise SystemExit("CSV 裡沒有讀到任何有效姓名")

    result = call_admin_import_roster(roster, commit=args.commit, force=args.force)
    print_report(result)

    if not result.get("ok") and not result.get("blocked"):
        sys.exit(1)


if __name__ == "__main__":
    main()
