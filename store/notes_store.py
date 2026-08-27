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


def send_broadcast_mail(subject: str, body: str, group_recipient: str):
    """
    透過福委會共用 Notes 帳號寄送院內群組信（sdd3.md §5.3、§5.6）。

    沿用 fetch_active_stores() 一樣的 Lotus.NotesSession 連線寫法。GetDatabase("", "")
    開啟目前這組 Notes ID 對應的預設郵件檔——Send() 是否成功繫於這組帳號本身有沒有
    寄信權限，跟被開啟的是哪個資料庫無關，這點 sdd3.md §5.6 已確認可行，但用 COM API
    程式化觸發寄送這個動作本身還沒有實機測試過，第一次呼叫時要留意。

    group_recipient: 院內同仁群組信箱位址（.env 的 NOTES_BROADCAST_GROUP）
    """
    notes = win32com.client.Dispatch("Lotus.NotesSession")
    notes.Initialize(os.getenv("NOTES_PASSWORD", ""))
    db = notes.GetDatabase("", "")

    doc = db.CreateDocument()
    doc.Form = "Memo"
    doc.SendTo = group_recipient
    doc.Subject = subject
    rt = doc.CreateRichTextItem("Body")
    rt.AppendText(body)
    doc.Send(False)
