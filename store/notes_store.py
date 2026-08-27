import win32com.client
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

SERVER  = "mdaapa/medicine/Tzuchi"
DB_PATH = r"OAUse\ContributingStore.nsf"
VIEW    = "依商店"


def fetch_active_stores():
    """回傳未作廢、未過期的特約商店清單（依類別、名稱排序），expire 為 ISO 日期字串或 None"""
    notes = win32com.client.Dispatch("Lotus.NotesSession")
    notes.Initialize(os.getenv("NOTES_PASSWORD", ""))
    db = notes.GetDatabase(SERVER, DB_PATH)
    view = db.GetView(VIEW)

    today = datetime.now().date()
    stores = []

    col = view.AllEntries
    e = col.GetFirstEntry()
    while e:
        if e.IsDocument:
            doc = e.Document

            cancel = doc.GetItemValue("fd_Cancel")
            if cancel and cancel[0] == "1":
                e = col.GetNextEntry(e)
                continue

            change_date = doc.GetItemValue("fd_ChangeDate")
            expire_date = None
            if change_date and hasattr(change_date[0], "year"):
                t = change_date[0]
                expire_date = (datetime(t.year, t.month, t.day) + timedelta(hours=8)).date()
                if expire_date < today:
                    e = col.GetNextEntry(e)
                    continue

            name     = doc.GetItemValue("fd_ObjectName")
            kind     = doc.GetItemValue("fd_Kind")
            tel      = doc.GetItemValue("fd_Tel")
            address  = doc.GetItemValue("fd_Address")
            contents = doc.GetItemValue("fd_Contents")

            stores.append({
                "name":     name[0] if name else "",
                "kind":     kind[0] if kind else "",
                "tel":      tel[0] if tel else "",
                "address":  address[0] if address else "",
                "contents": contents[0] if contents else "",
                "expire":   expire_date.isoformat() if expire_date else None,
            })

        e = col.GetNextEntry(e)

    stores.sort(key=lambda s: (s["kind"], s["name"]))
    return stores
