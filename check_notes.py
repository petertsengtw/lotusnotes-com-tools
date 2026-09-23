import win32com.client
from dotenv import load_dotenv
import os

load_dotenv()

notes = win32com.client.Dispatch("Lotus.NotesSession")
# HCL Notes 12 不會沿用用戶端的登入狀態，Initialize("") 會卡在主控台等密碼，
# 所以跟其他腳本一樣帶 .env 的密碼；Notes 用戶端開著時 ID 檔會被鎖住，需先關閉
notes.Initialize(os.getenv("NOTES_PASSWORD", ""))

# ↓↓ 修改這兩行 ↓↓
SERVER  = "hladmin2/medicine/Tzuchi"               # 本機留空；遠端填 "TWSERVER01/TW"
DB_PATH = r"moghuman\hmsign.nsf"  # 改成你剛查到的 File 路徑

db = notes.GetDatabase(SERVER, DB_PATH)

print("=== 所有 View 列表 ===")
views = db.Views
for v in views:
    print(f"  View: {v.Name}")
