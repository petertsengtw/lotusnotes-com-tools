"""
把 store/web/liff/index.html 部署到 Ubuntu 主機的 {STORE_REMOTE_PATH}/liff/ 子目錄。
用法: python deploy_liff.py

跟 deploy_store.py 完全獨立、不共用也不修改它——這支只管 LIFF 驗證頁這一個檔案。
部署前會把檔案裡的 __LIFF_ID__、__FUNCTIONS_BASE_URL__ 佔位字串換成 .env 對應的值，
換完寫到暫存檔再 scp 上去，原始檔案（含佔位字串）保持不動，這樣就不用為了不同環境
手動改 HTML。

沿用 deploy_store.py 同一套 SSH 金鑰登入、Sysnative 64-bit ssh/scp 繞過 WOW64、
capture_output 避免 VS Code 終端機被進度條卡住的作法。
"""
import os
import subprocess
import tempfile

from dotenv import load_dotenv

load_dotenv()

SFTP_HOST         = os.getenv("SFTP_HOST")
SFTP_PORT         = os.getenv("SFTP_PORT", "22")
SFTP_USER         = os.getenv("SFTP_USER")
SFTP_KEY_PATH     = os.getenv("SFTP_KEY_PATH")
STORE_REMOTE_PATH = os.getenv("STORE_REMOTE_PATH")
LIFF_ID           = os.getenv("LIFF_ID")
FUNCTIONS_BASE_URL = os.getenv("STORE_AUTH_FUNCTIONS_BASE_URL")

if not all([SFTP_HOST, SFTP_USER, SFTP_KEY_PATH, STORE_REMOTE_PATH, LIFF_ID, FUNCTIONS_BASE_URL]):
    raise SystemExit(
        "請確認 .env 已填寫 SFTP_HOST / SFTP_USER / SFTP_KEY_PATH / STORE_REMOTE_PATH / "
        "LIFF_ID / STORE_AUTH_FUNCTIONS_BASE_URL"
    )

BASE_DIR    = os.path.dirname(__file__)
SOURCE_FILE = os.path.join(BASE_DIR, "web", "liff", "index.html")
REMOTE_DIR  = f"{STORE_REMOTE_PATH}/liff"
SSH_TARGET  = f"{SFTP_USER}@{SFTP_HOST}"

_SYSNATIVE = r"C:\Windows\Sysnative\OpenSSH"
SSH_EXE = os.path.join(_SYSNATIVE, "ssh.exe") if os.path.exists(_SYSNATIVE) else "ssh"
SCP_EXE = os.path.join(_SYSNATIVE, "scp.exe") if os.path.exists(_SYSNATIVE) else "scp"

SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]


def run_ssh(args, check=True):
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"指令失敗（exit {result.returncode}）: {' '.join(args)}\n{result.stderr}")
    return result


if not os.path.exists(SOURCE_FILE):
    raise SystemExit(f"找不到 {SOURCE_FILE}")

with open(SOURCE_FILE, "r", encoding="utf-8") as f:
    html = f.read()

for placeholder in ("__LIFF_ID__", "__FUNCTIONS_BASE_URL__"):
    if placeholder not in html:
        raise SystemExit(f"{SOURCE_FILE} 裡找不到 {placeholder} 佔位字串，請確認檔案內容")

html = html.replace("__LIFF_ID__", LIFF_ID).replace("__FUNCTIONS_BASE_URL__", FUNCTIONS_BASE_URL)

with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp:
    tmp.write(html)
    tmp_path = tmp.name

try:
    run_ssh([SSH_EXE, "-i", SFTP_KEY_PATH, "-p", SFTP_PORT, *SSH_OPTS, SSH_TARGET, f"mkdir -p {REMOTE_DIR}"])

    scp_cmd = [SCP_EXE, "-i", SFTP_KEY_PATH, "-P", SFTP_PORT, *SSH_OPTS,
               tmp_path, f"{SSH_TARGET}:{REMOTE_DIR}/index.html"]
    result = run_ssh(scp_cmd, check=False)
    if result.returncode != 0:
        print(f"上傳失敗，重試一次...\n{result.stderr}")
        run_ssh(scp_cmd)
    print(f"已部署到 {REMOTE_DIR}/index.html")
finally:
    os.remove(tmp_path)
