"""
Lotus Notes 自動簽到退
用法:
  python auto_checkin.py in    # 簽到
  python auto_checkin.py out   # 簽退
"""
import sys
import logging
import ssl
from datetime import datetime, timedelta
import win32com.client
from dotenv import load_dotenv
import os
import requests
import urllib3
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class _LegacySSLAdapter(HTTPAdapter):
    """允許舊版 TLS cipher（院內 portal 常見）。"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)

load_dotenv()

# ── 設定區 ──────────────────────────────────────────
SERVER    = "hladmin2/medicine/Tzuchi"
DB_PATH   = r"moghuman\hmsign.nsf"
USER      = "曾建瑋/medicine/Tzuchi"
LOCATION  = "花蓮慈院"
SIGN_TYPE = "N"   # N=正常班, A=加班, C=OnCall, S=交接班
# ────────────────────────────────────────────────────

LOG_FILE = os.path.join(os.path.dirname(__file__), "checkin.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)


def checkin(status: str):
    """status: '1'=簽到  '0'=簽退"""
    label = "簽到" if status == "1" else "簽退"
    try:
        notes = win32com.client.Dispatch("Lotus.NotesSession")
        notes.Initialize(os.getenv("NOTES_PASSWORD", ""))
        db = notes.GetDatabase(SERVER, DB_PATH)
        if not db.IsOpen:
            raise RuntimeError("無法開啟資料庫")

        doc = db.CreateDocument()
        doc.ReplaceItemValue("Form",         "簽到退卡")
        doc.ReplaceItemValue("fd_EleSign",   USER)
        # win32com 存入時會自動轉 UTC，+8h 補回台灣時間
        doc.ReplaceItemValue("fd_SignTime",  datetime.now() + timedelta(hours=8))
        doc.ReplaceItemValue("fd_SignType",  SIGN_TYPE)
        doc.ReplaceItemValue("fd_SignStatus", status)
        doc.ReplaceItemValue("fd_location",  LOCATION)
        doc.Save(True, False)

        logging.info(f"{label} 成功  UNID={doc.UniversalID}")
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {label} 成功")

    except Exception as e:
        logging.error(f"{label} 失敗: {e}")
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {label} 失敗: {e}")
        sys.exit(1)


_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _new_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", _LegacySSLAdapter())
    s.headers.update(_BROWSER_HEADERS)
    return s


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def portal_login() -> bool:
    """POST 登入院內 portal，取得對外上網權限。
    使用 http.client 繞過 urllib3 的 ALPN/h2 協商（pfSense portal 不相容）。
    """
    import http.client
    import urllib.parse
    from bs4 import BeautifulSoup

    host     = "hltchnet.tzuchi.com.tw"
    port     = 1003
    username = os.getenv("PORTAL_USERNAME", "")
    password = os.getenv("PORTAL_PASSWORD", "")
    hdrs     = {"Host": f"{host}:{port}", "Connection": "close",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        # GET 登入頁面，取出 magic token
        conn = http.client.HTTPSConnection(host, port, context=_ssl_ctx(), timeout=10)
        conn.request("GET", "/portal?", headers=hdrs)
        r = conn.getresponse()
        html = r.read().decode("utf-8", errors="replace")
        conn.close()
    except Exception as e:
        logging.error(f"portal_login GET 失敗: {e}")
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] portal GET 失敗: {e}")
        return False

    try:
        soup  = BeautifulSoup(html, "html.parser")
        magic = (soup.find("input", {"name": "magic"})  or {}).get("value", "")
        redir = (soup.find("input", {"name": "4Tredir"}) or {}).get("value", "")

        if not magic:
            logging.info("portal 已登入，跳過 POST")
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] portal 已登入")
            return True

        # POST 登入
        body = urllib.parse.urlencode(
            {"username": username, "password": password, "magic": magic, "4Tredir": redir}
        ).encode()
        conn2 = http.client.HTTPSConnection(host, port, context=_ssl_ctx(), timeout=10)
        conn2.request("POST", "/", body=body, headers={
            **hdrs,
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body)),
        })
        r2 = conn2.getresponse()
        r2.read()
        conn2.close()

        logging.info(f"portal_login HTTP {r2.status} magic={'ok' if magic else 'missing'}")
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] portal 登入 HTTP {r2.status}")
        return r2.status == 200
    except Exception as e:
        logging.error(f"portal_login POST 失敗: {e}")
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] portal POST 失敗: {e}")
        return False


def send_line_message(text: str):
    """透過 LINE Messaging API 推播訊息給自己。"""
    token   = os.getenv("LINE_CHANNEL_TOKEN", "")
    user_id = os.getenv("LINE_USER_ID", "")
    try:
        session = _new_session()
        resp = session.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"to": user_id, "messages": [{"type": "text", "text": text}]},
            timeout=10,
            verify=False,
        )
        logging.info(f"LINE push HTTP {resp.status_code}")
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] LINE 通知 HTTP {resp.status_code}")
    except Exception as e:
        logging.error(f"LINE push 失敗: {e}")
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] LINE 通知失敗: {e}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("in", "out"):
        print("用法: python auto_checkin.py in|out")
        sys.exit(1)

    action = sys.argv[1]
    label  = "簽到" if action == "in" else "簽退"

    checkin("1" if action == "in" else "0")
    portal_login()
    send_line_message(f"[自動簽到退] {label} 完成 {datetime.now():%Y-%m-%d %H:%M:%S}")
