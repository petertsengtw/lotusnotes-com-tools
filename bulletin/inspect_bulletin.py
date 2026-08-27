"""
列出花蓮慈院公佈欄（mdabulletin.nsf）「花蓮慈院」View 裡，第一筆公告人為
「花蓮慈院職工福利小組」的文件所有欄位（維護用，摸清楚欄位內部名稱）。
"""
import win32com.client
from dotenv import load_dotenv
import os

load_dotenv()

SERVER  = "mda/medicine/Tzuchi"
DB_PATH = r"OAuse\mdabulletin.nsf"
VIEW    = "(all)"
TARGET_AUTHOR = "職工福利"

notes = win32com.client.Dispatch("Lotus.NotesSession")
notes.Initialize(os.getenv("NOTES_PASSWORD", ""))
db = notes.GetDatabase(SERVER, DB_PATH)

print("=== 所有 View ===")
for v in db.Views:
    print(f"  {v.Name}")

view = db.GetView(VIEW)
print(f"\n=== 在 View '{VIEW}' 裡找公告人 = '{TARGET_AUTHOR}' 的文件 ===")

col = view.AllEntries
e = col.GetFirstEntry()
found = 0
while e:
    if e.IsDocument:
        doc = e.Document
        for item in doc.Items:
            if TARGET_AUTHOR in str(item.Values):
                print(f"\n--- 命中文件（欄位 {item.Name} 含目標字串）---")
                for it in doc.Items:
                    print(f"  [{it.Name}] = {str(it.Values)[:150]}")
                found += 1
                break
    if found >= 3:
        break
    e = col.GetNextEntry(e)

if found == 0:
    print("沒找到符合的文件，改印前 3 筆文件的欄位供比對：")
    e = col.GetFirstEntry()
    n = 0
    while e and n < 3:
        if e.IsDocument:
            doc = e.Document
            print(f"\n--- 第 {n + 1} 筆 ---")
            for it in doc.Items:
                print(f"  [{it.Name}] = {str(it.Values)[:150]}")
            n += 1
        e = col.GetNextEntry(e)
