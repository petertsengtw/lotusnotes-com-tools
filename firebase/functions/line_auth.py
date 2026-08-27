"""
LINE ID token 驗證（sdd3.md §5.3）。

用 LINE 官方的 POST /oauth2/v2.1/verify endpoint 做伺服器端驗證，不用本地 JWKS
簽章驗證——這個規模（院內同仁，偶發查詢）換不回本地驗證省下的那趟網路請求所增加
的複雜度（key 快取、輪替），先用這個簡單做法，有需要再優化。

安全性重點：lineUserId 只能來自這裡驗證過的 claims["sub"]，絕不能信任任何前端
自己宣稱的使用者 ID。
"""
from __future__ import annotations

import os

import requests

LINE_VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"
LINE_ISSUER = "https://access.line.me"


class LineVerifyError(Exception):
    pass


def verify_line_id_token(id_token: str) -> dict:
    """驗證成功回傳 LINE 的 claims dict（至少含 sub/iss/aud/exp）；失敗丟 LineVerifyError。"""
    if not id_token:
        raise LineVerifyError("missing id_token")

    # 僅供 firebase emulator 本機測試用：不打真的 LINE API，直接把 token 字串當 sub。
    # 正式環境不會設這個環境變數，見 sdd3.md §5 實作計畫「驗證方式」。
    if os.environ.get("LINE_AUTH_STUB") == "1":
        return {"iss": LINE_ISSUER, "aud": "stub", "sub": f"stub-{id_token}"}

    channel_id = os.environ.get("LINE_LOGIN_CHANNEL_ID", "")
    if not channel_id:
        raise LineVerifyError("server misconfigured: LINE_LOGIN_CHANNEL_ID not set")

    resp = requests.post(
        LINE_VERIFY_URL,
        data={"id_token": id_token, "client_id": channel_id},
        timeout=5,
    )
    if resp.status_code != 200:
        raise LineVerifyError(f"line verify failed: {resp.status_code} {resp.text}")

    claims = resp.json()
    # /verify 本身就會檢查 audience，這裡是防禦性再確認一次，不信任任何單一檢查點。
    if claims.get("iss") != LINE_ISSUER or claims.get("aud") != channel_id:
        raise LineVerifyError("claim mismatch")
    if not claims.get("sub"):
        raise LineVerifyError("missing sub claim")

    return claims
