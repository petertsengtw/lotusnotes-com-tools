"""
換一組新的期效性驗證碼（sdd3.md §5.3）。
用法: python broadcast_code.py <部門/情境名稱>
範例: python broadcast_code.py 職工福利小組

只負責換碼、把碼印出來——公告本身透過院內另一個 Notes 公佈欄資料庫手動張貼，
不是本專案自動寄信，這是季度、單一操作者手動觸發的動作。

不同部門/情境的碼各自獨立：換某個部門的碼只會停用「同一個部門名稱」之前的舊碼，
不影響其他部門目前有效的碼。部門名稱純粹是給自己追蹤用，所有部門查到的商店資料
都是同一份，不會因為用哪個部門的碼而有差異。
"""
import argparse
import os

import requests
import urllib3
from dotenv import load_dotenv

load_dotenv()

# 院內網路對外 HTTPS 會被自簽憑證攔截（跟 upload_joomla.py/auto_checkin.py 遇到的是同一個環境限制），
# 略過憑證驗證，見 README.md「注意事項」。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FUNCTIONS_BASE_URL = os.getenv("STORE_AUTH_FUNCTIONS_BASE_URL")
ADMIN_SHARED_SECRET = os.getenv("ADMIN_SHARED_SECRET")
LIFF_URL = os.getenv("STORE_LIFF_URL", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("label", help="部門/情境名稱，純粹供自己追蹤用，例如「職工福利小組」")
    args = parser.parse_args()

    if not all([FUNCTIONS_BASE_URL, ADMIN_SHARED_SECRET]):
        raise SystemExit("請確認 .env 已填寫 STORE_AUTH_FUNCTIONS_BASE_URL / ADMIN_SHARED_SECRET")

    resp = requests.post(
        f"{FUNCTIONS_BASE_URL}/admin_rotate_code",
        json={"label": args.label},
        headers={"X-Admin-Secret": ADMIN_SHARED_SECRET},
        timeout=30,
        verify=False,
    )
    if resp.status_code != 200:
        raise SystemExit(f"換碼失敗（HTTP {resp.status_code}）：{resp.text}")

    result = resp.json()
    code = result["code"]
    valid_until = result["validUntil"]

    print(f"【{args.label}】已產生新驗證碼：{code}（效期至 {valid_until}）")
    print()
    print("請把以下內容手動貼到院內公佈欄公告：")
    print("-" * 40)
    print("特約商店查詢頁本期驗證碼如下，請掃描 LINE@ QR code 加入好友後，")
    print("在查詢頁輸入您的姓名/Notes ID 與本期驗證碼完成綁定，之後即可隨時查詢特約優惠。")
    print()
    print(f"本期驗證碼：{code}")
    print(f"效期至：{valid_until}")
    if LIFF_URL:
        print(f"查詢頁網址：{LIFF_URL}")
    print()
    print("請勿將驗證碼轉發給非本院同仁。")
    print("-" * 40)


if __name__ == "__main__":
    main()
