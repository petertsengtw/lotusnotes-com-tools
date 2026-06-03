"""
Lotus Notes 自動簽到退
用法:
  python auto_checkin.py in    # 簽到
  python auto_checkin.py out   # 簽退
"""
import sys
import logging
from datetime import datetime, timedelta
import win32com.client
from dotenv import load_dotenv
import os

load_dotenv()

# ── 設定區 ──────────────────────────────────────────
SERVER    = "hladmin2/medicine/Tzuchi"
DB_PATH   = r"moghuman\hmsign.nsf"
USER      = "曾建瑋/medicine/Tzuchi"
LOCATION  = "花蓮慈院"
SIGN_TYPE = "N"   # N=正常班, A=加班, C=OnCall, S=交接班
# ────────────────────────────────────────────────────

LOG_FILE = r"c:\Users\peter\Desktop\autoRPA2-lotusNotesAPI\checkin.log"

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


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("in", "out"):
        print("用法: python auto_checkin.py in|out")
        sys.exit(1)

    checkin("1" if sys.argv[1] == "in" else "0")
