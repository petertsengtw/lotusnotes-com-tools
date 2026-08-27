"""
驗證碼產生與比對（sdd3.md §5.2、§5.5）。

codeAttempts 的鎖定邏輯用 Firestore transaction，避免同時間多個請求繞過鎖定次數
上限——這是 sdd3.md §8.6 明確點名「若沒做好會是整條存取控制單點弱點」的地方，
所以這裡不省成本。相對地 generate_and_activate_code() 換碼是季度、單一操作者手動
觸發的動作，不需要同等的嚴謹度（見 sdd3.md §5.6）。
"""
from __future__ import annotations

import secrets as pysecrets
import string
from datetime import datetime, timedelta, timezone

from google.cloud import firestore

# 排除容易看錯/唸錯的字元：0/O、1/I/L
CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1IL")
CODE_LENGTH = 8

MAX_FAIL_COUNT = 5
LOCK_MINUTES = 15
DEFAULT_VALID_DAYS = 90


def generate_and_activate_code(db: firestore.Client, days_valid: int = DEFAULT_VALID_DAYS) -> dict:
    """停用目前所有 active 的驗證碼，產生一組新碼並設為 active。回傳新碼與效期。"""
    code = "".join(pysecrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    now = datetime.now(timezone.utc)
    valid_until = now + timedelta(days=days_valid)

    batch = db.batch()
    for doc in db.collection("verificationCodes").where("active", "==", True).stream():
        batch.update(doc.reference, {"active": False})
    batch.set(
        db.collection("verificationCodes").document(code),
        {"validFrom": now, "validUntil": valid_until, "active": True},
    )
    batch.commit()

    return {"code": code, "validFrom": now, "validUntil": valid_until}


def check_and_consume_code(db: firestore.Client, line_user_id: str, notes_id: str, code: str) -> dict:
    """
    驗證碼比對 + codeAttempts 鎖定，全部包在一個 transaction 裡。

    回傳:
      {"ok": True}                                    碼正確，已寫入 lineAuth
      {"ok": False, "locked": True}                   已被鎖定中，這次連比對都不做
      {"ok": False, "locked": False}                  碼錯誤，還沒到鎖定次數
      {"ok": False, "locked": True, "justLocked": True}  這次錯誤剛好觸發鎖定
    """
    attempts_ref = db.collection("codeAttempts").document(line_user_id)
    auth_ref = db.collection("lineAuth").document(line_user_id)
    codes_ref = db.collection("verificationCodes")

    transaction = db.transaction()

    @firestore.transactional
    def _run(transaction: firestore.Transaction) -> dict:
        now = datetime.now(timezone.utc)

        attempts_snap = attempts_ref.get(transaction=transaction)
        attempts_data = attempts_snap.to_dict() if attempts_snap.exists else {}
        locked_until = attempts_data.get("lockedUntil")
        if locked_until and locked_until > now:
            return {"ok": False, "locked": True}

        active_docs = list(
            codes_ref.where("active", "==", True)
            .where("validFrom", "<=", now)
            .where("validUntil", ">=", now)
            .limit(1)
            .stream(transaction=transaction)
        )
        code_matches = bool(active_docs) and active_docs[0].id == code

        if code_matches:
            transaction.set(
                auth_ref,
                {"notesId": notes_id, "status": "verified", "verifiedAt": now, "revokedAt": None},
                merge=True,
            )
            transaction.set(attempts_ref, {"failCount": 0, "lockedUntil": None})
            return {"ok": True}

        fail_count = attempts_data.get("failCount", 0) + 1
        just_locked = fail_count >= MAX_FAIL_COUNT
        update = {"failCount": fail_count}
        if just_locked:
            update["lockedUntil"] = now + timedelta(minutes=LOCK_MINUTES)
        transaction.set(attempts_ref, update, merge=True)
        return {"ok": False, "locked": just_locked, "justLocked": just_locked}

    return _run(transaction)
