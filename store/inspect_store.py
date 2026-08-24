import win32com.client
from dotenv import load_dotenv
import os

load_dotenv()

SERVER  = "mdaapa/medicine/Tzuchi"
DB_PATH = r"OAUse\ContributingStore.nsf"

notes = win32com.client.Dispatch("Lotus.NotesSession")
notes.Initialize(os.getenv("NOTES_PASSWORD", ""))
db = notes.GetDatabase(SERVER, DB_PATH)

print("=== 所有 View ===")
for v in db.Views:
    print(f"  {v.Name}")

print("\n=== 所有 Form ===")
for f in db.Forms:
    print(f"  {f.Name}")

print("\n=== 各 View 第一筆文件欄位 ===")
for v in db.Views:
    print(f"\nView: {v.Name}")
    col = v.AllEntries
    e = col.GetFirstEntry()
    while e:
        if e.IsDocument:
            doc = e.Document
            for item in doc.Items:
                print(f"  [{item.Name}] = {str(item.Values)[:80]}")
            break
        e = col.GetNextEntry(e)
