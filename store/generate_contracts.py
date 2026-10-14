"""
特約商店同意書套版與 PDF 產生（sdd5.md §4.5.1）。
用法: python generate_contracts.py

2026-10 起特約商店改簽「同意書」（原本是雙方用印的合約書），店家在同意書上蓋商店
印鑑、代表人簽章後回傳即完成，本院不再用印回傳。檔名、Firestore 欄位（contractUrl
等）沿用原本「合約」的命名，避免改動已上線的資料結構。

撈出 status=approved 且來源為「使用慈濟醫院範本」的申請（「使用店家制式範本」是
改同意書之前的舊選項，核准當下就直接轉 contract_ready，不會走到這裡），逐筆套版
產生 PDF：

  1. 用 Word COM 開啟已經準備好佔位符的範本（store/templates/consent_template.docx，
     需要先跑過一次 prepare_consent_template.py，見那支腳本的說明），對每個
     {{...}} 佔位符做全文件取代（同一個欄位在文件裡出現兩次，例如店名，也是「兩處都
     要換成同一個值」）。
  2. 同一個 Word COM session 直接匯出 PDF，不落地存中繼檔。
  3. 用既有 SSH 金鑰把 PDF 上傳到 Ubuntu 網站伺服器一個隨機路徑（每筆申請各自一組
     token，目錄列表沿用既有伺服器設定回 403）。
  4. 呼叫 admin_mark_contract_ready 把下載網址寫回 Firestore，狀態轉 contract_ready。

套版用的範本檔案處理完一律 Close(SaveChanges=False)，讓範本母片保持乾淨，下一筆
申請可以重複拿來套版。
"""
import os
import secrets
import subprocess
import tempfile

import requests
import urllib3
import win32com.client as win32
from dotenv import load_dotenv

load_dotenv()

# 院內網路對外 HTTPS 會被自簽憑證攔截，略過憑證驗證，見 README.md「注意事項」。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FUNCTIONS_BASE_URL   = os.getenv("STORE_AUTH_FUNCTIONS_BASE_URL")
ADMIN_SHARED_SECRET  = os.getenv("ADMIN_SHARED_SECRET")
SFTP_HOST            = os.getenv("SFTP_HOST")
SFTP_PORT            = os.getenv("SFTP_PORT", "22")
SFTP_USER            = os.getenv("SFTP_USER")
SFTP_KEY_PATH        = os.getenv("SFTP_KEY_PATH")
STORE_REMOTE_PATH    = os.getenv("STORE_REMOTE_PATH")
STORE_PUBLIC_BASE_URL = os.getenv("STORE_PUBLIC_BASE_URL")

_REQUIRED_ENV = (
    "STORE_AUTH_FUNCTIONS_BASE_URL", "ADMIN_SHARED_SECRET", "SFTP_HOST", "SFTP_USER",
    "SFTP_KEY_PATH", "STORE_REMOTE_PATH", "STORE_PUBLIC_BASE_URL",
)
if not all(os.getenv(name) for name in _REQUIRED_ENV):
    raise SystemExit(f"請確認 .env 已填寫：{' / '.join(_REQUIRED_ENV)}")

HEADERS = {"X-Admin-Secret": ADMIN_SHARED_SECRET}

BASE_DIR = os.path.dirname(__file__)
TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "consent_template.docx")

_SYSNATIVE = r"C:\Windows\Sysnative\OpenSSH"
SSH_EXE = os.path.join(_SYSNATIVE, "ssh.exe") if os.path.exists(_SYSNATIVE) else "ssh"
SCP_EXE = os.path.join(_SYSNATIVE, "scp.exe") if os.path.exists(_SYSNATIVE) else "scp"
SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
SSH_TARGET = f"{SFTP_USER}@{SFTP_HOST}"

WD_EXPORT_FORMAT_PDF = 17  # wdExportFormatPDF

CHECKED_BOX = "☑"
UNCHECKED_BOX = "□"
# 長期有效時「至中華民國　年　月　日止」那行沒有勾，年月日套回原稿的底線空白。
BLANK_DATE_PART = "＿＿＿"


def run_ssh(args, check=True):
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"指令失敗（exit {result.returncode}）: {' '.join(args)}\n{result.stderr}")
    return result


def fetch_approved_applications() -> list:
    resp = requests.get(
        f"{FUNCTIONS_BASE_URL}/admin_list_applications",
        params={"status": "approved"},
        headers=HEADERS,
        timeout=30,
        verify=False,
    )
    if resp.status_code != 200:
        raise SystemExit(f"查詢失敗（HTTP {resp.status_code}）：{resp.text}")
    apps = resp.json().get("applications", [])
    # own_template 核准後會直接轉 contract_ready，理論上不會出現在這裡；多一層篩選
    # 純粹是防呆，避免資料異常時誤套版。
    return [a for a in apps if a.get("contractSource") == "hospital_template"]


def roc_date_parts(iso_date: str) -> tuple[str, str, str]:
    """西元日期字串（YYYY-MM-DD）轉民國年/月/日，月/日不補零，符合公文書慣用寫法。"""
    year, month, day = iso_date.split("-")
    return str(int(year) - 1911), str(int(month)), str(int(day))


def replace_all(doc, target: str, replacement: str):
    # 不能用 Find.Replacement.Text：Word 規定「取代為」最多 255 字元，優惠內容寫得
    # 詳細一點就會超過（2026-10-01 永諦工程行 293 字，報「字串參數太長」）。
    # 改成逐一找到佔位符後直接改寫該 Range 的文字，沒有長度限制。
    # 換行統一轉成段落內換行（\x0b），條列項目逐行呈現，且沿用同一段落的縮排。
    replacement = replacement.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\x0b")
    rng = doc.Content
    f = rng.Find
    f.ClearFormatting()
    f.Text = target
    f.Forward = True
    f.Wrap = 0  # wdFindStop：從頭找到尾就停，搭配下面的迴圈換掉「每一個」出現的地方
    f.MatchWildcards = False
    count = 0
    while f.Execute():
        rng.Text = replacement
        rng.Collapse(0)  # wdCollapseEnd：從剛換好的文字後面繼續找
        count += 1
    if count == 0:
        raise SystemExit(f"範本裡找不到佔位符 {target!r}，範本檔案可能損壞或版本不對，請重新跑 prepare_consent_template.py")


def consent_values(app: dict) -> dict:
    """申請資料轉成同意書佔位符的值。

    同意日期＝核准日（admin_review_application 核准時寫入 contractStartDate）；
    contractEndDate 有值表示店家選「至指定日期止」，沒有值表示「長期有效」（sdd5.md
    §4.5.1）。改同意書之前核准的舊申請兩個日期都有值，會當成「至指定日期止」套版。
    """
    sign_y, sign_m, sign_d = roc_date_parts(app["contractStartDate"])
    end_date = app.get("contractEndDate")
    if end_date:
        until_y, until_m, until_d = roc_date_parts(end_date)
    else:
        until_y = until_m = until_d = BLANK_DATE_PART

    return {
        "store_name": app["storeName"],
        "discount_content": app["discountContent"],
        "tax_id": app["taxId"],
        "owner_name": app["ownerName"],
        "address": app["address"],
        "phone": app["phone"],
        "contact_person": app.get("contactPerson") or app["ownerName"],
        "email": app["email"],
        "box_open": UNCHECKED_BOX if end_date else CHECKED_BOX,
        "box_until": CHECKED_BOX if end_date else UNCHECKED_BOX,
        "until_y": until_y, "until_m": until_m, "until_d": until_d,
        "sign_y": sign_y, "sign_m": sign_m, "sign_d": sign_d,
    }


def render_contract_pdf(word, app: dict, pdf_path: str):
    if not os.path.exists(TEMPLATE_PATH):
        raise SystemExit(
            f"找不到 {TEMPLATE_PATH}，需要先執行一次 prepare_consent_template.py 產生已插入佔位符的範本"
        )

    doc = word.Documents.Open(TEMPLATE_PATH)
    try:
        for field, value in consent_values(app).items():
            replace_all(doc, "{{" + field + "}}", value)

        doc.ExportAsFixedFormat(OutputFileName=pdf_path, ExportFormat=WD_EXPORT_FORMAT_PDF)
    finally:
        doc.Close(SaveChanges=False)  # 範本母片保持乾淨，不落地存修改後的檔案


def upload_and_get_url(pdf_path: str) -> str:
    token = secrets.token_hex(24)
    remote_dir = f"{STORE_REMOTE_PATH}/contracts"
    remote_path = f"{remote_dir}/{token}.pdf"

    run_ssh([SSH_EXE, "-i", SFTP_KEY_PATH, "-p", SFTP_PORT, *SSH_OPTS, SSH_TARGET, f"mkdir -p {remote_dir}"])

    scp_cmd = [SCP_EXE, "-i", SFTP_KEY_PATH, "-P", SFTP_PORT, *SSH_OPTS, pdf_path, f"{SSH_TARGET}:{remote_path}"]
    result = run_ssh(scp_cmd, check=False)
    if result.returncode != 0:
        print(f"上傳失敗，重試一次...\n{result.stderr}")
        run_ssh(scp_cmd)

    return f"{STORE_PUBLIC_BASE_URL.rstrip('/')}/contracts/{token}.pdf"


def mark_contract_ready(application_id: str, contract_url: str):
    resp = requests.post(
        f"{FUNCTIONS_BASE_URL}/admin_mark_contract_ready",
        json={"applicationId": application_id, "contractUrl": contract_url},
        headers=HEADERS,
        timeout=30,
        verify=False,
    )
    if resp.status_code != 200:
        raise SystemExit(f"回寫失敗（HTTP {resp.status_code}）：{resp.text}")


def main():
    apps = fetch_approved_applications()
    if not apps:
        print("目前沒有待套版的申請（status=approved 且來源為慈濟醫院範本）")
        return

    print(f"共 {len(apps)} 筆待套版")
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    try:
        for app in apps:
            application_id = app["applicationId"]
            print(f"套版中：{application_id}（{app['storeName']}）...")
            with tempfile.TemporaryDirectory() as tmp_dir:
                pdf_path = os.path.join(tmp_dir, f"{application_id}.pdf")
                render_contract_pdf(word, app, pdf_path)
                contract_url = upload_and_get_url(pdf_path)
            mark_contract_ready(application_id, contract_url)
            print(f"完成：{contract_url}")
    finally:
        word.Quit()

    print("全部套版完成")


if __name__ == "__main__":
    main()
