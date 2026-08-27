"""
換一組新的期效性驗證碼，並把碼跟 LINE@ 加入方式寄給院內同仁群組信箱（sdd3.md §5.3、§5.6）。
用法: python broadcast_code.py

換碼本身呼叫 Cloud Functions 的 admin_rotate_code 端點；換碼完成後才用 notes_store.py
新增的 send_broadcast_mail() 寄信——這是季度、單一操作者手動觸發的動作，跟這個 repo
其他 Notes 功能一樣沒辦法排程無人值守執行（見 sdd3.md §5.6、README.md 既有說明）。
"""
import os

import requests
import urllib3
from dotenv import load_dotenv

from notes_store import send_broadcast_mail

load_dotenv()

# 院內網路對外 HTTPS 會被自簽憑證攔截（跟 upload_joomla.py/auto_checkin.py 遇到的是同一個環境限制），
# 略過憑證驗證，見 README.md「注意事項」。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FUNCTIONS_BASE_URL = os.getenv("STORE_AUTH_FUNCTIONS_BASE_URL")
ADMIN_SHARED_SECRET = os.getenv("ADMIN_SHARED_SECRET")
NOTES_BROADCAST_GROUP = os.getenv("NOTES_BROADCAST_GROUP")
LIFF_URL = os.getenv("STORE_LIFF_URL", "")

if not all([FUNCTIONS_BASE_URL, ADMIN_SHARED_SECRET, NOTES_BROADCAST_GROUP]):
    raise SystemExit(
        "請確認 .env 已填寫 STORE_AUTH_FUNCTIONS_BASE_URL / ADMIN_SHARED_SECRET / NOTES_BROADCAST_GROUP"
    )

resp = requests.post(
    f"{FUNCTIONS_BASE_URL}/admin_rotate_code",
    json={},
    headers={"X-Admin-Secret": ADMIN_SHARED_SECRET},
    timeout=30,
    verify=False,
)
if resp.status_code != 200:
    raise SystemExit(f"換碼失敗（HTTP {resp.status_code}）：{resp.text}")

result = resp.json()
code = result["code"]
valid_until = result["validUntil"]

print(f"已產生新驗證碼：{code}（效期至 {valid_until}）")

subject = "花蓮慈濟醫院特約商店查詢 - 本期驗證碼"
body_lines = [
    "各位同仁好，",
    "",
    "特約商店查詢頁本期驗證碼如下，請掃描 LINE@ QR code 加入好友後，",
    "在查詢頁輸入您的姓名/Notes ID 與本期驗證碼完成綁定，之後即可隨時查詢特約優惠。",
    "",
    f"本期驗證碼：{code}",
    f"效期至：{valid_until}",
]
if LIFF_URL:
    body_lines.append(f"查詢頁網址：{LIFF_URL}")
body_lines += [
    "",
    "請勿將驗證碼轉發給非本院同仁。",
    "",
    "職工福利行政小組",
]

send_broadcast_mail(subject, "\n".join(body_lines), NOTES_BROADCAST_GROUP)
print(f"已寄出廣播信給 {NOTES_BROADCAST_GROUP}")
