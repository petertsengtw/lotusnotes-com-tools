"""
本機腳本 -> Cloud Functions 的 admin-only 端點共用密鑰驗證。

密鑰放在 Cloud Functions 的 secret（firebase functions:secrets:set ADMIN_SHARED_SECRET），
不是本機 .env 直接持有 Firebase 憑證——本機腳本只知道這把共用密鑰，見 sdd3.md §5 實作計畫。
"""
from __future__ import annotations

import hmac
import os


def check_secret(expected: str, got: str) -> bool:
    """常數時間比對，避免 timing attack。純函式，方便測試。"""
    return bool(expected) and hmac.compare_digest(got or "", expected)


def is_authorized(headers) -> bool:
    """headers 是任何支援 .get() 的物件（Flask/Cloud Functions Request.headers 皆可）。"""
    expected = os.environ.get("ADMIN_SHARED_SECRET", "")
    got = headers.get("X-Admin-Secret", "")
    return check_secret(expected, got)
