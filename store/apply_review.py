"""
互動式審核特約商店線上申請（sdd5.md §3、§4.4、§4.7、§4.8、§4.10）。
用法:
    python apply_review.py                     # 審核 status=pending 的申請
    python apply_review.py --status merchant_signed  # 核對店家回傳的同意書（商店印鑑、代表人簽章），確認後結案
    python apply_review.py --status approved   # 純瀏覽（例如看目前卡在等套版的申請）
    python apply_review.py --abandon 20260909-03     # 把指定申請標記為放棄/不予受理
    python apply_review.py --find 統編或店名或電話      # 店家忘了申請編號/查詢碼時，搜尋並顯示

`--find` 會在所有狀態的申請裡搜尋（店名、負責人、聯絡人、統編、電話、Email、申請
編號，部分符合即可，電話可帶或不帶橫線），列出符合申請的完整表單內容、狀態、同意書期間、
處理進度（台灣時間）以及**查詢碼**。
查詢碼是店家下載同意書的唯一憑證，告訴對方之前請先核對身分（例如對方能說出統編、
留的電話跟申請資料相符）。

`--status pending` 時逐筆審核；`--status merchant_signed` 時逐筆提示是否要
下載檢查店家回傳的同意書，確認商店印鑑、代表人簽章都蓋好後標記完成；其他狀態
單純列出清單，不出現互動提示。

2026-10 起特約商店改簽「同意書」（sdd5.md §4.5.1）：店家申請時就選好適用期間
（長期有效／至指定日期止），核准時不用再輸入起訖日，同意日自動填核准當天；店家
在同意書蓋章回傳後，本院不用再用印、不用回傳最終檔案，核對無誤直接結案。核准後
這筆申請會停在 approved，等 generate_contracts.py 套版產生同意書 PDF。

「使用店家制式範本」是改同意書之前的舊選項（申請表已不再提供），核准前會先下載
店家上傳的合約書並用作業系統預設的關聯程式開啟，讓你人工看內容；核准後直接變成
contract_ready，沒有套版這個動作。

店家在網頁或 LINE 官方帳號傳回用印掃描檔後（sdd5.md §4.7、§4.7.1），狀態會自動
變成 merchant_signed，不需要在這裡手動標記。
"""
import argparse
import os
import tempfile
from datetime import datetime, timedelta

import requests
import urllib3
from dotenv import load_dotenv

from tax_id_lookup import describe as describe_tax_id

load_dotenv()

# 院內網路對外 HTTPS 會被自簽憑證攔截（跟 broadcast_code.py/import_roster.py 遇到的
# 是同一個環境限制），略過憑證驗證，見 README.md「注意事項」。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FUNCTIONS_BASE_URL = os.getenv("STORE_AUTH_FUNCTIONS_BASE_URL")
ADMIN_SHARED_SECRET = os.getenv("ADMIN_SHARED_SECRET")

if not all([FUNCTIONS_BASE_URL, ADMIN_SHARED_SECRET]):
    raise SystemExit("請確認 .env 已填寫 STORE_AUTH_FUNCTIONS_BASE_URL / ADMIN_SHARED_SECRET")

HEADERS = {"X-Admin-Secret": ADMIN_SHARED_SECRET}

CONTENT_TYPE_EXT = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def fetch_applications(status: str) -> list:
    resp = requests.get(
        f"{FUNCTIONS_BASE_URL}/admin_list_applications",
        params={"status": status} if status else {},
        headers=HEADERS,
        timeout=30,
        verify=False,
    )
    if resp.status_code != 200:
        raise SystemExit(f"查詢失敗（HTTP {resp.status_code}）：{resp.text}")
    return resp.json().get("applications", [])


def submit_review(application_id: str, decision: str, review_note: str) -> dict:
    body = {"applicationId": application_id, "decision": decision, "reviewNote": review_note}
    resp = requests.post(
        f"{FUNCTIONS_BASE_URL}/admin_review_application",
        json=body,
        headers=HEADERS,
        timeout=30,
        verify=False,
    )
    try:
        result = resp.json()
    except ValueError:
        result = {"ok": False, "error": resp.text}
    if resp.status_code != 200:
        print(f"審核送出失敗（HTTP {resp.status_code}）：{result}")
    return result


def open_remote_file(application_id: str, kind: str):
    """kind 是 "own_template"（店家自有合約書）或 "merchant_signed"（店家用印回傳
    的掃描檔），見 main.py download_file 端點。"""
    resp = requests.get(
        f"{FUNCTIONS_BASE_URL}/download_file",
        params={"applicationId": application_id, "kind": kind},
        headers=HEADERS,
        timeout=30,
        verify=False,
    )
    if resp.status_code != 200:
        print(f"下載檔案失敗（HTTP {resp.status_code}）：{resp.text}")
        return

    ext = CONTENT_TYPE_EXT.get(resp.headers.get("Content-Type", ""), "")
    with tempfile.NamedTemporaryFile("wb", suffix=ext, delete=False) as tmp:
        tmp.write(resp.content)
        tmp_path = tmp.name

    print(f"已下載檔案：{tmp_path}")
    try:
        os.startfile(tmp_path)
    except OSError as e:
        print(f"無法自動開啟檔案，請自行手動開啟上面的路徑（{e}）")


def submit_update_status(application_id: str, status: str, final_doc_url: str = None) -> dict:
    body = {"applicationId": application_id, "status": status}
    if final_doc_url:
        body["finalDocUrl"] = final_doc_url
    resp = requests.post(
        f"{FUNCTIONS_BASE_URL}/admin_update_status",
        json=body,
        headers=HEADERS,
        timeout=30,
        verify=False,
    )
    try:
        result = resp.json()
    except ValueError:
        result = {"ok": False, "error": resp.text}
    if resp.status_code != 200:
        print(f"狀態更新失敗（HTTP {resp.status_code}）：{result}")
    return result


def describe_validity(app: dict) -> str:
    """店家申請時選的同意書適用期間（sdd5.md §4.5.1）。改同意書之前的申請沒有這個欄位。"""
    if app.get("validityType") == "until_date":
        return f"至 {app.get('validUntil')} 止"
    if app.get("validityType") == "open_ended":
        return "長期有效"
    return "（舊申請，未選）"


def print_application(app: dict):
    print("-" * 50)
    print(f"申請編號：{app['applicationId']}　狀態：{app['status']}")
    print(f"店名：{app['storeName']}　負責人：{app['ownerName']}　統編：{app['taxId']}")
    print(f"地址：{app['address']}　電話：{app['phone']}　Email：{app['email']}")
    print(f"聯絡人：{app.get('contactPerson') or '（同負責人）'}　營業類別：{app['businessCategory']}")
    print(f"優惠內容：{app['discountContent']}")
    if app.get("note"):
        print(f"備註：{app['note']}")
    if app["contractSource"] == "hospital_template":
        print(f"同意書適用期間：{describe_validity(app)}")
    else:
        print("來源：店家制式範本（改同意書前的舊選項）")
    print(describe_tax_id(app["taxId"]))


FIND_FIELDS = ("applicationId", "storeName", "ownerName", "contactPerson", "taxId", "phone", "email")


def _digits_only(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def matches_keyword(app: dict, keyword: str) -> bool:
    kw = keyword.strip().lower()
    if not kw:
        return False
    kw_digits = _digits_only(kw)
    for field in FIND_FIELDS:
        value = str(app.get(field) or "").lower()
        if kw in value:
            return True
        # 電話這類欄位，對方可能帶橫線/空格也可能不帶，比對純數字（至少 3 碼才比，避免太短誤中）
        if len(kw_digits) >= 3 and set(kw) <= set("0123456789-() +/") and kw_digits in _digits_only(value):
            return True
    return False


PROGRESS_FIELDS = (
    ("submittedAt", "送出"),
    ("reviewedAt", "審核"),
    ("contractGeneratedAt", "產生同意書"),
    ("merchantSignedAt", "店家回傳用印"),
    ("completedAt", "結案"),
)


def to_taipei(timestamp: str) -> str:
    """後端回傳的是 UTC 時間字串（例如 2026-10-05 02:13:28.988000+00:00），轉成台灣時間顯示到分。"""
    try:
        return (datetime.fromisoformat(timestamp) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(timestamp)


def find_applications(keyword: str):
    matched = [a for a in fetch_applications(None) if matches_keyword(a, keyword)]
    if not matched:
        print(f"找不到符合「{keyword}」的申請")
        return

    print(f"共找到 {len(matched)} 筆符合「{keyword}」的申請（查詢碼是下載同意書的憑證，告知前請先核對對方身分）")
    for app in matched:
        print_application(app)
        print(f"查詢碼：{app.get('queryCode', '（無）')}")
        if app.get("contractStartDate"):
            print(f"同意日：{app['contractStartDate']}　到期日：{app.get('contractEndDate') or '長期有效'}")
        if app.get("reviewNote"):
            print(f"審核備註：{app['reviewNote']}")
        print("處理進度：" + "　".join(f"{label} {to_taipei(app.get(key))}"
                                     for key, label in PROGRESS_FIELDS if app.get(key)))
        if app.get("contractUrl"):
            print(f"同意書檔：{app['contractUrl']}")
        if app.get("finalDocUrl"):
            print(f"最終檔案：{app['finalDocUrl']}")


def review_pending(app: dict):
    print_application(app)

    if app["contractSource"] == "own_template":
        print("這筆是「使用店家制式範本」，先下載店家上傳的合約書供你人工檢查內容...")
        open_remote_file(app["applicationId"], "own_template")

    decision = input("核准請按 a，婉拒請按 r，跳過請直接按 Enter：").strip().lower()
    if decision not in ("a", "r"):
        print("已跳過")
        return

    if decision == "r":
        note = input("婉拒理由：").strip()
        print(f"已婉拒：{submit_review(app['applicationId'], 'rejected', note)}")
        return

    note = input("審核備註（選填）：").strip()
    result = submit_review(app["applicationId"], "approved", note)
    print(f"已核准：{result}")
    if result.get("ok") and result.get("status") == "approved":
        print("接著執行 generate_contracts.py（menu.py「產生同意書 PDF」）產生同意書。")


def review_merchant_signed(app: dict):
    """店家已在網頁或 LINE 傳回蓋好章的同意書，狀態自動變成 merchant_signed
    （sdd5.md §4.7、§4.7.1）。同意書只需要店家核章（sdd5.md §4.8），人工核對商店
    印鑑、代表人簽章齊全後就標記 completed，本院不用再用印、回傳最終檔案。"""
    print_application(app)

    if app.get("documentType") == "consent":
        doc_name = "同意書"
        confirm_prompt = "確認商店印鑑、代表人簽章都已蓋好，標記完成請按 c，跳過請直接按 Enter："
    else:
        # 改制前已產生的合約書仍是雙方用印，要蓋院方大小章並把最終檔案傳回店家。
        doc_name = "合約（改制前產生，需雙方用印）"
        confirm_prompt = "確認流程都做完了（列印、蓋院方大小章、掃描、已把最終檔案傳回店家）請按 c，跳過請直接按 Enter："

    action = input(f"查看店家回傳的{doc_name}請按 v，確認無誤請按 c，跳過請直接按 Enter：").strip().lower()
    if action == "v":
        open_remote_file(app["applicationId"], "merchant_signed")
        action = input(confirm_prompt).strip().lower()

    if action != "c":
        print("已跳過")
        return

    result = submit_update_status(app["applicationId"], "completed")
    print(f"已標記完成：{result}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", default="pending", help="要列出的申請狀態（預設 pending）")
    parser.add_argument("--abandon", metavar="APPLICATION_ID", help="把指定申請標記為 abandoned（放棄/不予受理），不會進入其他審核流程")
    parser.add_argument("--find", metavar="關鍵字", help="搜尋所有狀態的申請（店名/負責人/聯絡人/統編/電話/Email/申請編號），顯示申請編號與查詢碼")
    args = parser.parse_args()

    if args.find:
        find_applications(args.find)
        return

    if args.abandon:
        print(f"已標記為 abandoned：{submit_update_status(args.abandon, 'abandoned')}")
        return

    apps = fetch_applications(args.status)
    if not apps:
        print(f"目前沒有狀態為「{args.status}」的申請")
        return

    print(f"共 {len(apps)} 筆狀態為「{args.status}」的申請")

    if args.status == "pending":
        for app in apps:
            review_pending(app)
        print("審核完畢")
    elif args.status == "merchant_signed":
        for app in apps:
            review_merchant_signed(app)
        print("處理完畢")
    else:
        for app in apps:
            print_application(app)


if __name__ == "__main__":
    main()
