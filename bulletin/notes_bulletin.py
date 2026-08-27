"""
共用模組：讀取花蓮慈院公佈欄（mdabulletin.nsf）裡「職工福利行政小組」發的、
未過期的公告，含內嵌圖片擷取（沿用 query_news.py 的 DXL 匯出手法）。
"""
import base64
import os
import re
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

import win32com.client
from dotenv import load_dotenv

load_dotenv()

SERVER     = "mda/medicine/Tzuchi"
DB_PATH    = r"OAuse\mdabulletin.nsf"
VIEW       = "花蓮慈院"
DEPARTMENT = "職工福利行政小組"

DXL_NS = "{http://www.lotus.com/dxl}"
IMAGE_TAGS = [("jpeg", ".jpg"), ("gif", ".gif"), ("png", ".png")]


def fetch_active_bulletins(image_dir: str) -> list:
    """
    回傳「職工福利行政小組」發的、未過期公告清單（依公告日新到舊排序）。
    圖片會存到 image_dir，每筆公告的 images 是存進去的檔名列表（相對檔名，不含路徑）。
    """
    notes = win32com.client.Dispatch("Lotus.NotesSession")
    notes.Initialize(os.getenv("NOTES_PASSWORD", ""))
    db = notes.GetDatabase(SERVER, DB_PATH)
    view = db.GetView(VIEW)

    exporter = notes.CreateDXLExporter()
    exporter.ConvertNotesbitmapsToGIF = False
    exporter.OutputDOCTYPE = False

    os.makedirs(image_dir, exist_ok=True)

    today = datetime.now().date()
    bulletins = []

    col = view.AllEntries
    e = col.GetFirstEntry()
    while e:
        if e.IsDocument:
            doc = e.Document

            department = doc.GetItemValue("fd_AncDepartment")
            if not department or department[0] != DEPARTMENT:
                e = col.GetNextEntry(e)
                continue

            expire_raw = doc.GetItemValue("fd_AncExpDate")
            expire_date = None
            if expire_raw and hasattr(expire_raw[0], "year"):
                t = expire_raw[0]
                expire_date = (datetime(t.year, t.month, t.day) + timedelta(hours=8)).date()
                if expire_date < today:
                    e = col.GetNextEntry(e)
                    continue

            date_raw = doc.GetItemValue("fd_AncDate")
            ann_date = None
            if date_raw and hasattr(date_raw[0], "year"):
                t = date_raw[0]
                ann_date = (datetime(t.year, t.month, t.day) + timedelta(hours=8)).date()

            subject = doc.GetItemValue("fd_Subject")

            body = doc.GetFirstItem("fd_Contain")
            text = ""
            if body:
                try:
                    text = body.Text or ""
                except Exception:
                    pass
            text = re.sub(r"\n{3,}", "\n\n", text.strip())

            unid = doc.UniversalID
            images = []
            try:
                dxl = exporter.Export(doc)
                root = ET.fromstring(dxl)
                img_count = 0
                for tag, ext in IMAGE_TAGS:
                    for node in root.iter(f"{DXL_NS}{tag}"):
                        if node.text:
                            filename = f"{unid}_{img_count:03d}{ext}"
                            with open(os.path.join(image_dir, filename), "wb") as f:
                                f.write(base64.b64decode(node.text.strip()))
                            images.append(filename)
                            img_count += 1
            except Exception:
                pass

            # 只記錄檔名，不下載內容——同仁若需要附件本身，請自行到院內公佈欄下載。
            attachments = []
            for item in doc.Items:
                if item.Name == "$FILE":
                    try:
                        values = item.Values
                        if values and values[0]:
                            attachments.append(str(values[0]))
                    except Exception:
                        pass

            bulletins.append({
                "id":          unid,
                "subject":     subject[0] if subject else "",
                "content":     text,
                "date":        ann_date.isoformat() if ann_date else None,
                "expire":      expire_date.isoformat() if expire_date else None,
                "images":      images,
                "attachments": attachments,
            })

        e = col.GetNextEntry(e)

    bulletins.sort(key=lambda b: b["date"] or "", reverse=True)
    return bulletins
