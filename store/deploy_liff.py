"""
把 store/web/liff/ 底下所有 LIFF 頁面部署到 Ubuntu 主機的 {STORE_REMOTE_PATH}/liff/ 子目錄。
用法: python deploy_liff.py

跟 deploy_store.py 完全獨立、不共用也不修改它——這支只管 LIFF 驗證頁這一個檔案。
部署前會把檔案裡的佔位字串換成 .env 對應的值，換完寫到暫存檔再 scp 上去，原始檔案
（含佔位字串）保持不動，這樣就不用為了不同環境手動改 HTML。

index.html 跟 bulletin.html 是掛在同一個 LINE Login Channel 底下的兩個獨立 LIFF app
（各自有自己的 LIFF ID 跟 Endpoint URL），所以用兩個不同的佔位字串 __LIFF_ID__／
__BULLETIN_LIFF_ID__，不能共用同一組——見 sdd3.md 的說明，這是因為單一 LIFF ID
只能登記一個 Endpoint URL，直接用完整網址繞過短網址存取另一個頁面時，LIFF SDK
會判斷成「外部瀏覽器」（liff.isInClient() 為 false），沒辦法沿用 LINE App 本身的
登入狀態，之前就是共用一組 LIFF ID 才會一直卡在「LINE 登入狀態已失效」。

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
BULLETIN_LIFF_ID  = os.getenv("BULLETIN_LIFF_ID")
FUNCTIONS_BASE_URL = os.getenv("STORE_AUTH_FUNCTIONS_BASE_URL")

if not all([SFTP_HOST, SFTP_USER, SFTP_KEY_PATH, STORE_REMOTE_PATH, LIFF_ID, BULLETIN_LIFF_ID, FUNCTIONS_BASE_URL]):
    raise SystemExit(
        "請確認 .env 已填寫 SFTP_HOST / SFTP_USER / SFTP_KEY_PATH / STORE_REMOTE_PATH / "
        "LIFF_ID / BULLETIN_LIFF_ID / STORE_AUTH_FUNCTIONS_BASE_URL"
    )

BASE_DIR    = os.path.dirname(__file__)
LIFF_DIR    = os.path.join(BASE_DIR, "web", "liff")
REMOTE_DIR  = f"{STORE_REMOTE_PATH}/liff"
SSH_TARGET  = f"{SFTP_USER}@{SFTP_HOST}"

# 各頁面各自的佔位字串換值對照——index.html／bulletin.html 是兩個獨立的 LIFF app，
# 不能共用同一組 LIFF ID（見上方模組說明）。
PAGE_PLACEHOLDERS = {
    "index.html": {
        "__LIFF_ID__": LIFF_ID,
        "__FUNCTIONS_BASE_URL__": FUNCTIONS_BASE_URL,
    },
    "bulletin.html": {
        "__BULLETIN_LIFF_ID__": BULLETIN_LIFF_ID,
        "__FUNCTIONS_BASE_URL__": FUNCTIONS_BASE_URL,
    },
}

_SYSNATIVE = r"C:\Windows\Sysnative\OpenSSH"
SSH_EXE = os.path.join(_SYSNATIVE, "ssh.exe") if os.path.exists(_SYSNATIVE) else "ssh"
SCP_EXE = os.path.join(_SYSNATIVE, "scp.exe") if os.path.exists(_SYSNATIVE) else "scp"

SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]


def run_ssh(args, check=True):
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"指令失敗（exit {result.returncode}）: {' '.join(args)}\n{result.stderr}")
    return result


run_ssh([SSH_EXE, "-i", SFTP_KEY_PATH, "-p", SFTP_PORT, *SSH_OPTS, SSH_TARGET, f"mkdir -p {REMOTE_DIR}"])

for page, replacements in PAGE_PLACEHOLDERS.items():
    source_file = os.path.join(LIFF_DIR, page)
    if not os.path.exists(source_file):
        raise SystemExit(f"找不到 {source_file}")

    with open(source_file, "r", encoding="utf-8") as f:
        html = f.read()

    for placeholder in replacements:
        if placeholder not in html:
            raise SystemExit(f"{source_file} 裡找不到 {placeholder} 佔位字串，請確認檔案內容")

    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp:
        tmp.write(html)
        tmp_path = tmp.name

    try:
        scp_cmd = [SCP_EXE, "-i", SFTP_KEY_PATH, "-P", SFTP_PORT, *SSH_OPTS,
                   tmp_path, f"{SSH_TARGET}:{REMOTE_DIR}/{page}"]
        result = run_ssh(scp_cmd, check=False)
        if result.returncode != 0:
            print(f"上傳 {page} 失敗，重試一次...\n{result.stderr}")
            run_ssh(scp_cmd)
        print(f"已部署到 {REMOTE_DIR}/{page}")
    finally:
        os.remove(tmp_path)
