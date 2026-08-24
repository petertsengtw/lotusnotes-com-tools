"""
匯出特約商店資料，並透過 SSH 金鑰用 scp 部署到院內查詢網頁
用法: python deploy_store.py
"""
import json
import os
import subprocess
from datetime import datetime
from dotenv import load_dotenv
from notes_store import fetch_active_stores

load_dotenv()

SFTP_HOST         = os.getenv("SFTP_HOST")
SFTP_PORT         = os.getenv("SFTP_PORT", "22")
SFTP_USER         = os.getenv("SFTP_USER")
SFTP_KEY_PATH     = os.getenv("SFTP_KEY_PATH")
STORE_REMOTE_PATH = os.getenv("STORE_REMOTE_PATH")

if not all([SFTP_HOST, SFTP_USER, SFTP_KEY_PATH, STORE_REMOTE_PATH]):
    raise SystemExit("請確認 .env 已填寫 SFTP_HOST / SFTP_USER / SFTP_KEY_PATH / STORE_REMOTE_PATH")

BASE_DIR   = os.path.dirname(__file__)
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WEB_DIR    = os.path.join(BASE_DIR, "web")
JSON_PATH  = os.path.join(OUTPUT_DIR, "stores.json")
WEB_FILES  = [os.path.join(WEB_DIR, name) for name in
              ("index.html", "join.html", "qa.html", "style.css")]
SSH_TARGET = f"{SFTP_USER}@{SFTP_HOST}"

# 32-bit Python 存取 System32 會被 WOW64 導向 SysWOW64（沒有 OpenSSH），
# 用 Sysnative 繞過重導向找到真正的 64-bit ssh/scp
_SYSNATIVE = r"C:\Windows\Sysnative\OpenSSH"
SSH_EXE = os.path.join(_SYSNATIVE, "ssh.exe") if os.path.exists(_SYSNATIVE) else "ssh"
SCP_EXE = os.path.join(_SYSNATIVE, "scp.exe") if os.path.exists(_SYSNATIVE) else "scp"

# ── 產生最新 stores.json ──────────────────────────────
os.makedirs(OUTPUT_DIR, exist_ok=True)
stores = fetch_active_stores()
payload = {
    "generated_at": datetime.now().isoformat(timespec="minutes"),
    "stores": stores,
}
with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
print(f"已匯出 {len(stores)} 筆")

# ── 確保遠端目錄存在 ──────────────────────────────────
subprocess.run(
    [SSH_EXE, "-i", SFTP_KEY_PATH, "-p", SFTP_PORT,
     "-o", "StrictHostKeyChecking=accept-new",
     SSH_TARGET, f"mkdir -p {STORE_REMOTE_PATH}"],
    check=True,
)

# ── 上傳檔案（偶發網路問題時重試一次）──────────────────
for local_path in (*WEB_FILES, JSON_PATH):
    scp_cmd = [SCP_EXE, "-i", SFTP_KEY_PATH, "-P", SFTP_PORT,
               "-o", "StrictHostKeyChecking=accept-new",
               local_path, f"{SSH_TARGET}:{STORE_REMOTE_PATH}/"]
    result = subprocess.run(scp_cmd)
    if result.returncode != 0:
        print(f"上傳 {os.path.basename(local_path)} 失敗，重試一次...")
        subprocess.run(scp_cmd, check=True)
    print(f"已上傳：{os.path.basename(local_path)}")

print("部署完成")
