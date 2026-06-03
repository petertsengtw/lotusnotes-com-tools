import win32com.client
from dotenv import load_dotenv
import os

load_dotenv()

SERVER  = "mdaapa/medicine/Tzuchi"
DB_PATH = r"OAuse\mddpdoc.nsf"

notes = win32com.client.Dispatch("Lotus.NotesSession")
notes.Initialize(os.getenv("NOTES_PASSWORD", ""))
db = notes.GetDatabase(SERVER, DB_PATH)

# 列出所有 View
print("=== 所有 View ===")
for v in db.Views:
    print(f"  {v.Name}")

# 列出所有 Form
print("\n=== 所有 Form ===")
for f in db.Forms:
    print(f"  {f.Name}")

# 找「新聞稿」相關的 View，看第一筆文件的欄位
print("\n=== 新聞稿 View 第一筆欄位 ===")
for vname in db.Views:
    if "新聞" in vname.Name:
        print(f"\nView: {vname.Name}")
        col = vname.AllEntries
        e = col.GetFirstEntry()
        while e:
            if e.IsDocument:
                doc = e.Document
                for item in doc.Items:
                    print(f"  [{item.Name}] = {str(item.Values)[:80]}")
                break
            e = col.GetNextEntry(e)
        break
