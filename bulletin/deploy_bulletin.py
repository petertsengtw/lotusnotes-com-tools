"""
匯出福委會（職工福利行政小組）在院內公佈欄的未過期公告，連同內嵌圖片一起透過
SSH 金鑰部署到 Ubuntu 網站伺服器一個沒有任何頁面連結、路徑本身是亂碼的目錄下。
用法: python deploy_bulletin.py

這個路徑的隨機字串（.env 的 BULLETIN_SECRET_SLUG）就是唯一的存取控制——資料本身
不進 Firebase，但查詢仍然需要 LINE 驗證：Cloud Functions 的 bulletin 端點確認身分
後才會代替使用者來抓這個網址，瀏覽器/LIFF 頁不會直接拿到這個網址（見 sdd4.md）。
"""
import json
import os
import subprocess
from datetime import datetime

from dotenv import load_dotenv

from notes_bulletin import fetch_active_bulletins

load_dotenv()

SFTP_HOST           = os.getenv("SFTP_HOST")
SFTP_PORT           = os.getenv("SFTP_PORT", "22")
SFTP_USER           = os.getenv("SFTP_USER")
SFTP_KEY_PATH       = os.getenv("SFTP_KEY_PATH")
STORE_REMOTE_PATH   = os.getenv("STORE_REMOTE_PATH", "").strip()
BULLETIN_SECRET_SLUG = os.getenv("BULLETIN_SECRET_SLUG")

if not all([SFTP_HOST, SFTP_USER, SFTP_KEY_PATH, STORE_REMOTE_PATH, BULLETIN_SECRET_SLUG]):
    raise SystemExit(
        "請確認 .env 已填寫 SFTP_HOST / SFTP_USER / SFTP_KEY_PATH / STORE_REMOTE_PATH / BULLETIN_SECRET_SLUG"
    )

BASE_DIR   = os.path.dirname(__file__)
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
IMAGE_DIR  = os.path.join(OUTPUT_DIR, "images")
JSON_PATH  = os.path.join(OUTPUT_DIR, "bulletin.json")

REMOTE_DIR = f"{STORE_REMOTE_PATH.rstrip('/')}/{BULLETIN_SECRET_SLUG}"
SSH_TARGET = f"{SFTP_USER}@{SFTP_HOST}"

_SYSNATIVE = r"C:\Windows\Sysnative\OpenSSH"
SSH_EXE = os.path.join(_SYSNATIVE, "ssh.exe") if os.path.exists(_SYSNATIVE) else "ssh"
SCP_EXE = os.path.join(_SYSNATIVE, "scp.exe") if os.path.exists(_SYSNATIVE) else "scp"

SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]


def run_ssh(args, check=True):
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"指令失敗（exit {result.returncode}）: {' '.join(args)}\n{result.stderr}")
    return result


def scp_with_retry(local_path, remote_path):
    scp_cmd = [SCP_EXE, "-i", SFTP_KEY_PATH, "-P", SFTP_PORT, *SSH_OPTS, local_path, f"{SSH_TARGET}:{remote_path}"]
    result = run_ssh(scp_cmd, check=False)
    if result.returncode != 0:
        print(f"上傳 {os.path.basename(local_path)} 失敗，重試一次...\n{result.stderr}")
        run_ssh(scp_cmd)


# ── 匯出最新公告 + 圖片 ──────────────────────────────
os.makedirs(IMAGE_DIR, exist_ok=True)
bulletins = fetch_active_bulletins(IMAGE_DIR)
payload = {
    "generated_at": datetime.now().isoformat(timespec="minutes"),
    "bulletins": bulletins,
}
with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
print(f"已匯出 {len(bulletins)} 則公告")

# ── 部署 ──────────────────────────────────────────
# 先清空遠端 images 目錄再重建：公告過期後圖片就不會再進 bulletin.json，
# 但舊圖檔案本身不會自動消失，先清空可以避免殘留檔案越積越多。
run_ssh([SSH_EXE, "-i", SFTP_KEY_PATH, "-p", SFTP_PORT, *SSH_OPTS,
         SSH_TARGET, f"rm -rf {REMOTE_DIR}/images && mkdir -p {REMOTE_DIR}/images"])

scp_with_retry(JSON_PATH, f"{REMOTE_DIR}/bulletin.json")
print("已上傳：bulletin.json")

image_files = [f for b in bulletins for f in b["images"]]
for filename in image_files:
    scp_with_retry(os.path.join(IMAGE_DIR, filename), f"{REMOTE_DIR}/images/{filename}")
print(f"已上傳：{len(image_files)} 張圖片")

print("部署完成")
