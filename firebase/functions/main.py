"""
Cloud Functions（2nd gen, Python）進入點。sdd3.md §5 存取控制的後端。

每個 @https_fn.on_request 是各自獨立網址的 function（不是同一支底下的路由）：
  verify               公開，LIFF 頁呼叫，輸入姓名/Notes ID + 驗證碼
  stores                公開，LIFF 頁呼叫，帶 LINE ID token 取商店清單
  admin_push_stores    admin-only，本機 sync_stores_to_firestore.py 呼叫
  admin_rotate_code    admin-only，本機 broadcast_code.py 呼叫
  admin_import_roster  admin-only，本機 import_roster.py 呼叫

安全模型（見 sdd3.md §5 實作計畫「架構總覽」）：
- 這裡是唯一會碰 Firestore 的地方，前端/本機都不直接用 Firestore SDK。
- /verify、/stores 給瀏覽器（LIFF webview）呼叫，需要 CORS；/admin/* 只給本機腳本
  用 requests 打，不會有瀏覽器呼叫，不需要 CORS。
"""
from __future__ import annotations

import json
import os

from firebase_admin import firestore, initialize_app
from firebase_functions import https_fn, options

from admin_auth import is_authorized
from codes import check_and_consume_code, generate_and_activate_code
from line_auth import LineVerifyError, verify_line_id_token
from roster_match import compute_revocations

initialize_app()

# 部署時把 ALLOWED_ORIGIN 設成正式站網域（例如 https://hlm.tzuchi.com.tw），
# 不要用 "*"——/stores 就是要擋掉「任何人都能拿網址直接抓」，來源限制才有意義。
_PUBLIC_CORS = options.CorsOptions(
    cors_origins=[os.environ.get("ALLOWED_ORIGIN", "https://REPLACE_WITH_REAL_DOMAIN")],
    cors_methods=["get", "post"],
)


def _json_response(payload: dict, status: int = 200) -> https_fn.Response:
    return https_fn.Response(json.dumps(payload, default=str), status=status, mimetype="application/json")


def _db():
    return firestore.client()


@https_fn.on_request(cors=_PUBLIC_CORS, secrets=["LINE_LOGIN_CHANNEL_ID"])
def verify(req: https_fn.Request) -> https_fn.Response:
    if req.method != "POST":
        return _json_response({"ok": False, "error": "method_not_allowed"}, 405)

    body = req.get_json(silent=True) or {}
    id_token = body.get("idToken", "")
    notes_id = (body.get("notesId") or "").strip()
    code = (body.get("code") or "").strip()

    if not notes_id or not code:
        return _json_response({"ok": False, "error": "missing_fields"}, 400)

    try:
        claims = verify_line_id_token(id_token)
    except LineVerifyError as e:
        print(f"verify: LINE token rejected: {e}")
        return _json_response({"ok": False, "error": "invalid_id_token"}, 401)

    result = check_and_consume_code(_db(), claims["sub"], notes_id, code)
    status = 200 if result["ok"] else (423 if result.get("locked") else 401)
    return _json_response(result, status)


@https_fn.on_request(cors=_PUBLIC_CORS, secrets=["LINE_LOGIN_CHANNEL_ID"])
def stores(req: https_fn.Request) -> https_fn.Response:
    auth_header = req.headers.get("Authorization", "")
    id_token = auth_header[7:] if auth_header.startswith("Bearer ") else ""

    try:
        claims = verify_line_id_token(id_token)
    except LineVerifyError as e:
        print(f"stores: LINE token rejected: {e}")
        return _json_response({"ok": False, "error": "invalid_id_token"}, 401)

    db = _db()
    auth_doc = db.collection("lineAuth").document(claims["sub"]).get()
    if not auth_doc.exists or auth_doc.to_dict().get("status") != "verified":
        return _json_response({"ok": False, "error": "not_verified"}, 403)

    data_doc = db.collection("storeData").document("current").get()
    payload = data_doc.to_dict() if data_doc.exists else {"generated_at": None, "stores": []}
    return _json_response(payload)


@https_fn.on_request(secrets=["ADMIN_SHARED_SECRET"])
def admin_push_stores(req: https_fn.Request) -> https_fn.Response:
    if not is_authorized(req.headers):
        return _json_response({"ok": False, "error": "unauthorized"}, 401)

    body = req.get_json(silent=True) or {}
    stores_list = body.get("stores")
    if not isinstance(stores_list, list):
        return _json_response({"ok": False, "error": "bad_payload"}, 400)

    _db().collection("storeData").document("current").set(
        {"generated_at": body.get("generated_at"), "stores": stores_list}
    )
    return _json_response({"ok": True, "count": len(stores_list)})


@https_fn.on_request(secrets=["ADMIN_SHARED_SECRET"])
def admin_rotate_code(req: https_fn.Request) -> https_fn.Response:
    if not is_authorized(req.headers):
        return _json_response({"ok": False, "error": "unauthorized"}, 401)

    body = req.get_json(silent=True) or {}
    label = (body.get("label") or "").strip()
    if not label:
        return _json_response({"ok": False, "error": "missing_label"}, 400)
    days_valid = body.get("daysValid", 90)
    result = generate_and_activate_code(_db(), label=label, days_valid=days_valid)
    return _json_response({"ok": True, **result})


@https_fn.on_request(secrets=["ADMIN_SHARED_SECRET"])
def admin_import_roster(req: https_fn.Request) -> https_fn.Response:
    if not is_authorized(req.headers):
        return _json_response({"ok": False, "error": "unauthorized"}, 401)

    body = req.get_json(silent=True) or {}
    roster = body.get("roster")
    force = bool(body.get("force", False))
    commit = bool(body.get("commit", False))

    if not isinstance(roster, list):
        return _json_response({"ok": False, "error": "bad_payload"}, 400)

    db = _db()
    verified_docs = db.collection("lineAuth").where("status", "==", "verified").stream()
    verified_users = [
        {"lineUserId": doc.id, "notesId": doc.to_dict().get("notesId", "")} for doc in verified_docs
    ]

    result = compute_revocations(verified_users, roster, force=force)

    if result["ok"] and commit and result["toRevoke"]:
        now = firestore.SERVER_TIMESTAMP
        batch = db.batch()
        for user in result["toRevoke"]:
            ref = db.collection("lineAuth").document(user["lineUserId"])
            batch.set(ref, {"status": "revoked", "revokedAt": now}, merge=True)
        batch.commit()
        result["committed"] = True
    else:
        result["committed"] = False

    return _json_response(result, 200 if result["ok"] else 400)
