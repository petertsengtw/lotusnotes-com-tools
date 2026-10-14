"""
特約商店線上申請（sdd5.md）核心邏輯：驗證表單欄位、產生申請編號/查詢碼、
建立/查詢/審核 storeApplications 文件。main.py 的 apply／application_status／
admin_list_applications／admin_review_application 端點都呼叫這裡，不直接操作
Firestore，好讓這些邏輯可以脫離 Cloud Functions 環境單獨測試（比照 codes.py）。

狀態機（sdd5.md §4.2）：
    pending -> approved -> contract_ready -> merchant_signed -> completed
            -> rejected
核准後，hospital_template 停在 approved，等本機 generate_contracts.py 套版產生
同意書 PDF 後轉 contract_ready（sdd5.md §4.5.1）；own_template（改同意書之前的
舊選項，見 sdd5.md §4.5.2）核准當下直接進 contract_ready。

2026-10 起特約商店改簽「同意書」：店家在同意書蓋商店印鑑、代表人簽章回傳即完成，
本院不再用印回傳。Firestore 欄位沿用原本「contract」的命名，不另外搬資料。
"""
from __future__ import annotations

import hmac
import re
import secrets as pysecrets
import string
from datetime import date, datetime, timedelta, timezone

from google.cloud import firestore

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CONTRACT_READY = "contract_ready"
STATUS_MERCHANT_SIGNED = "merchant_signed"
STATUS_COMPLETED = "completed"
STATUS_ABANDONED = "abandoned"

CONTRACT_SOURCE_HOSPITAL = "hospital_template"
CONTRACT_SOURCE_OWN = "own_template"
CONTRACT_SOURCES = (CONTRACT_SOURCE_HOSPITAL, CONTRACT_SOURCE_OWN)

# 同意書「三、適用期間」二選一（sdd5.md §4.5.1）：長期有效，或至指定日期止。
VALIDITY_OPEN_ENDED = "open_ended"
VALIDITY_UNTIL_DATE = "until_date"
VALIDITY_TYPES = (VALIDITY_OPEN_ENDED, VALIDITY_UNTIL_DATE)

TAIPEI_TZ = timezone(timedelta(hours=8))

TAX_ID_RE = re.compile(r"^\d{8}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHORT_FIELD_MAX = 200
LONG_FIELD_MAX = 2000

REQUIRED_SHORT_FIELDS = ("storeName", "ownerName", "address", "phone", "email", "businessCategory")
OPTIONAL_SHORT_FIELDS = ("contactPerson",)
REQUIRED_LONG_FIELDS = ("discountContent",)
OPTIONAL_LONG_FIELDS = ("note",)

# 蜜罐欄位：一般使用者在 apply.html 上看不到，只有機器人爬蟲填表機會填。收到非空值
# 直接當成濫用，回傳假的成功結果但不寫入 Firestore（見 main.py apply()）。
HONEYPOT_FIELD = "website"

# 店家自有合約書上傳限制（sdd5.md §4.5.2、§5、§6#14，暫定值，之後可視實務調整）。
ALLOWED_OWN_TEMPLATE_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_OWN_TEMPLATE_BYTES = 10 * 1024 * 1024

_OWN_TEMPLATE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}

# 店家透過 LINE 傳回的用印掃描檔限制（sdd5.md §4.7、§5），比自有合約書上傳寬鬆一點
# （多接受圖片格式、大小上限也比較大，因為手機直接拍照上傳很常見）。
ALLOWED_MERCHANT_FILE_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_MERCHANT_FILE_BYTES = 20 * 1024 * 1024

# 查詢碼：排除容易看錯/唸錯的字元（0/O、1/I/L），跟 codes.py 的驗證碼同一套考量。
QUERY_CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1IL")
QUERY_CODE_LENGTH = 8


def is_honeypot_triggered(data: dict) -> bool:
    return bool((data.get(HONEYPOT_FIELD) or "").strip())


def extension_for_content_type(content_type: str) -> str:
    return _OWN_TEMPLATE_EXTENSIONS.get(content_type, "")


def validate_own_template_file(content_type: str, size: int) -> str | None:
    """回傳 None 表示通過，否則回傳錯誤代碼。"""
    if content_type not in ALLOWED_OWN_TEMPLATE_CONTENT_TYPES:
        return "invalid_file_type"
    if size <= 0 or size > MAX_OWN_TEMPLATE_BYTES:
        return "file_too_large"
    return None


def validate_merchant_signed_file(content_type: str, size: int) -> str | None:
    """回傳 None 表示通過，否則回傳錯誤代碼。"""
    if content_type not in ALLOWED_MERCHANT_FILE_CONTENT_TYPES:
        return "invalid_file_type"
    if size <= 0 or size > MAX_MERCHANT_FILE_BYTES:
        return "file_too_large"
    return None


# 網頁上傳用印檔（sdd5.md §4.7.1）：只有「合約已備妥」（第一次上傳）跟「店家已回傳」
# （傳錯檔案想換掉重傳）這兩個狀態接受上傳；審核中、被婉拒、已結案等狀態上傳沒有
# 意義，也不該讓匿名呼叫者去改動已經走完流程的申請。
UPLOAD_ACCEPTING_STATUSES = (STATUS_CONTRACT_READY, STATUS_MERCHANT_SIGNED)

# multipart 的 Content-Type 是瀏覽器/呼叫者自己填的，可以亂寫，所以另外檢查檔案開頭
# 的位元組（magic bytes）是否跟宣稱的類型相符。
_FILE_SIGNATURES = {
    "application/pdf": b"%PDF",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}


def can_upload_merchant_signed(status: str | None) -> bool:
    return status in UPLOAD_ACCEPTING_STATUSES


def file_signature_matches(content_type: str, file_bytes: bytes) -> bool:
    signature = _FILE_SIGNATURES.get(content_type)
    return bool(signature) and file_bytes.startswith(signature)


def taipei_today() -> date:
    return datetime.now(TAIPEI_TZ).date()


def _validate_validity(data: dict, today: date) -> str | None:
    validity_type = data.get("validityType")
    if validity_type not in VALIDITY_TYPES:
        return "invalid_validity_type"
    if validity_type == VALIDITY_OPEN_ENDED:
        return None
    valid_until = (data.get("validUntil") or "").strip()
    if not ISO_DATE_RE.match(valid_until):
        return "invalid_valid_until"
    try:
        until = date.fromisoformat(valid_until)
    except ValueError:
        return "invalid_valid_until"
    if until <= today:
        return "valid_until_not_future"
    return None


def validate_application_fields(data: dict, today: date | None = None) -> str | None:
    """回傳 None 表示通過，否則回傳一個機器可讀的錯誤代碼。前端/後端都要驗證一次
    （sdd5.md §5：apply 是完全公開的端點，不能只信任前端）。today 只給測試用，
    預設取台灣時間今天。"""
    for field in REQUIRED_SHORT_FIELDS:
        value = (data.get(field) or "").strip()
        if not value:
            return f"missing_{field}"
        if len(value) > SHORT_FIELD_MAX:
            return f"{field}_too_long"

    for field in OPTIONAL_SHORT_FIELDS:
        if len(data.get(field) or "") > SHORT_FIELD_MAX:
            return f"{field}_too_long"

    for field in REQUIRED_LONG_FIELDS:
        value = (data.get(field) or "").strip()
        if not value:
            return f"missing_{field}"
        if len(value) > LONG_FIELD_MAX:
            return f"{field}_too_long"

    for field in OPTIONAL_LONG_FIELDS:
        if len(data.get(field) or "") > LONG_FIELD_MAX:
            return f"{field}_too_long"

    if not TAX_ID_RE.match((data.get("taxId") or "").strip()):
        return "invalid_tax_id"

    if data.get("contractSource") not in CONTRACT_SOURCES:
        return "invalid_contract_source"

    if data.get("contractSource") == CONTRACT_SOURCE_HOSPITAL:
        error = _validate_validity(data, today or taipei_today())
        if error:
            return error

    if data.get("consentPersonalData") is not True:
        return "consent_required"

    return None


def generate_query_code() -> str:
    return "".join(pysecrets.choice(QUERY_CODE_ALPHABET) for _ in range(QUERY_CODE_LENGTH))


def _next_application_id(db: firestore.Client, today: str) -> str:
    """每天各自獨立編號，格式 {YYYYMMDD}-{序號}（例如 20260909-03），方便電話溝通報號碼。
    用 transaction 避免同一秒內多筆申請拿到同一個序號。"""
    counter_ref = db.collection("applicationCounters").document(today)
    transaction = db.transaction()

    @firestore.transactional
    def _run(transaction: firestore.Transaction) -> int:
        snap = counter_ref.get(transaction=transaction)
        seq = (snap.to_dict().get("seq", 0) if snap.exists else 0) + 1
        transaction.set(counter_ref, {"seq": seq})
        return seq

    seq = _run(transaction)
    return f"{today}-{seq:02d}"


def create_application(db: firestore.Client, data: dict, ip: str, own_template_storage_path: str | None) -> dict:
    """呼叫前必須先通過 validate_application_fields()，這裡不重複做欄位驗證。"""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    application_id = _next_application_id(db, today)
    query_code = generate_query_code()
    valid_until = None
    if data.get("validityType") == VALIDITY_UNTIL_DATE:
        valid_until = data["validUntil"].strip()

    doc = {
        "storeName": data["storeName"].strip(),
        "ownerName": data["ownerName"].strip(),
        "taxId": data["taxId"].strip(),
        "address": data["address"].strip(),
        "phone": data["phone"].strip(),
        "email": data["email"].strip(),
        "contactPerson": (data.get("contactPerson") or "").strip(),
        "businessCategory": data["businessCategory"].strip(),
        "discountContent": data["discountContent"].strip(),
        "note": (data.get("note") or "").strip(),
        "contractSource": data["contractSource"],
        "validityType": data.get("validityType"),
        "validUntil": valid_until,
        "ownTemplateStoragePath": own_template_storage_path,
        "consentPersonalData": True,
        "queryCode": query_code,
        "status": STATUS_PENDING,
        "reviewNote": "",
        "contractUrl": None,
        "contractStartDate": None,
        "contractEndDate": None,
        "finalDocUrl": None,
        "merchantSignedFileUrl": None,
        "submittedIp": ip,
        "submittedAt": firestore.SERVER_TIMESTAMP,
        "reviewedAt": None,
        "contractGeneratedAt": None,
        "merchantSignedAt": None,
        "completedAt": None,
    }
    db.collection("storeApplications").document(application_id).set(doc)
    return {"applicationId": application_id, "queryCode": query_code}


def get_application(db: firestore.Client, application_id: str) -> dict | None:
    doc = db.collection("storeApplications").document(application_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["applicationId"] = doc.id
    return data


def check_query_code(application: dict, query_code: str) -> bool:
    """常數時間比對，避免 timing attack，跟 admin_auth.check_secret 同樣考量。"""
    expected = application.get("queryCode", "")
    return bool(expected) and hmac.compare_digest(query_code or "", expected)


DOCUMENT_TYPE_CONSENT = "consent"


def is_consent(application: dict) -> bool:
    """這筆申請的文件是不是同意書（2026-10 改制後）。mark_contract_ready 會寫入
    documentType；還沒產生文件的本院範本申請（審核中／已核准）之後產生的一定是同意書；
    其餘沒有 documentType 的（改制前已產生的合約、店家制式範本）都是合約。"""
    if application.get("documentType") == DOCUMENT_TYPE_CONSENT:
        return True
    if application.get("contractSource") != CONTRACT_SOURCE_HOSPITAL:
        return False
    return application.get("status") in (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)


def mark_contract_ready(db: firestore.Client, application_id: str, contract_url: str) -> dict:
    """generate_contracts.py 套版產生同意書 PDF、上傳完成後回寫用（sdd5.md §4.5.1）。
    只有已核准（approved）的 hospital_template 申請可以轉 contract_ready；own_template
    的申請核准當下就已經直接轉 contract_ready 了（見 review_application），不會走到這裡。"""
    ref = db.collection("storeApplications").document(application_id)
    snap = ref.get()
    if not snap.exists:
        return {"ok": False, "error": "not_found"}
    if snap.to_dict().get("status") != STATUS_APPROVED:
        return {"ok": False, "error": "not_approved"}

    ref.update({
        "status": STATUS_CONTRACT_READY,
        "contractUrl": contract_url,
        "documentType": DOCUMENT_TYPE_CONSENT,
        "contractGeneratedAt": firestore.SERVER_TIMESTAMP,
    })
    return {"ok": True, "status": STATUS_CONTRACT_READY}


def update_status(
    db: firestore.Client,
    application_id: str,
    status: str,
    final_doc_url: str | None = None,
) -> dict:
    """通用狀態轉換（sdd5.md §4.8），只給 merchant_signed／completed／abandoned 這幾個
    純人工判斷（或店家不便用 LINE 時的備援管道，見 §4.8「例外情況」）的轉換用，不檢查
    狀態機合法性以外的規則——`line_webhook` 收到檔案時走 merchant_binding.receive_file()
    自動轉 merchant_signed，不會呼叫這裡。"""
    if status not in (STATUS_MERCHANT_SIGNED, STATUS_COMPLETED, STATUS_ABANDONED):
        return {"ok": False, "error": "invalid_status"}

    ref = db.collection("storeApplications").document(application_id)
    if not ref.get().exists:
        return {"ok": False, "error": "not_found"}

    update = {"status": status}
    if status == STATUS_MERCHANT_SIGNED:
        update["merchantSignedAt"] = firestore.SERVER_TIMESTAMP
    elif status == STATUS_COMPLETED:
        update["completedAt"] = firestore.SERVER_TIMESTAMP
        if final_doc_url:
            update["finalDocUrl"] = final_doc_url

    ref.update(update)
    return {"ok": True, "status": status}


def list_applications(db: firestore.Client, status: str | None = None) -> list[dict]:
    query = db.collection("storeApplications")
    if status:
        query = query.where("status", "==", status)
    results = []
    for doc in query.stream():
        data = doc.to_dict()
        data["applicationId"] = doc.id
        results.append(data)
    results.sort(key=lambda a: a.get("applicationId", ""))
    return results


def consent_period(data: dict, approved_on: date) -> tuple[str, str | None]:
    """核准時決定同意書的同意日與到期日（sdd5.md §4.5.1）。同意日＝核准當天（台灣
    時間）；到期日依店家申請時選的適用期間，長期有效為 None。改同意書之前送出的申請
    沒有 validityType，一律當長期有效。"""
    if data.get("validityType") == VALIDITY_UNTIL_DATE and data.get("validUntil"):
        return approved_on.isoformat(), data["validUntil"]
    return approved_on.isoformat(), None


def review_application(
    db: firestore.Client,
    application_id: str,
    decision: str,
    review_note: str,
) -> dict:
    """
    核准/婉拒一筆申請（sdd5.md §4.4、§4.5.2）。

    hospital_template 核准後停在 approved，等 generate_contracts.py 套版產生同意書
    後才會轉 contract_ready；同意日（contractStartDate）與到期日（contractEndDate）
    在核准當下依 consent_period() 寫入，不再由審核者輸入。own_template 核准當下就
    直接轉 contract_ready，因為 contractUrl 就是店家自己上傳的那份檔案，沒有套版這個
    動作（見 sdd5.md §4.5.2）。
    """
    if decision not in ("approved", "rejected"):
        return {"ok": False, "error": "invalid_decision"}

    ref = db.collection("storeApplications").document(application_id)
    snap = ref.get()
    if not snap.exists:
        return {"ok": False, "error": "not_found"}

    data = snap.to_dict()
    if data.get("status") != STATUS_PENDING:
        return {"ok": False, "error": "not_pending"}

    update = {"reviewNote": review_note, "reviewedAt": firestore.SERVER_TIMESTAMP}

    if decision == "rejected":
        update["status"] = STATUS_REJECTED
        ref.update(update)
        return {"ok": True, "status": STATUS_REJECTED}

    if data.get("contractSource") == CONTRACT_SOURCE_HOSPITAL:
        contract_start_date, contract_end_date = consent_period(data, taipei_today())
        update["status"] = STATUS_APPROVED
        update["contractStartDate"] = contract_start_date
        update["contractEndDate"] = contract_end_date
    else:
        storage_path = data.get("ownTemplateStoragePath")
        if not storage_path:
            return {"ok": False, "error": "missing_own_template_file"}
        update["status"] = STATUS_CONTRACT_READY
        update["contractUrl"] = storage_path
        update["contractGeneratedAt"] = firestore.SERVER_TIMESTAMP

    ref.update(update)
    return {"ok": True, "status": update["status"]}
