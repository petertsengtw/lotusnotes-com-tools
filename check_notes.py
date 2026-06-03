import win32com.client

notes = win32com.client.Dispatch("Lotus.NotesSession")
notes.Initialize("")  # Notes 已開啟就不需要密碼

# ↓↓ 修改這兩行 ↓↓
SERVER  = "hladmin2/medicine/Tzuchi"               # 本機留空；遠端填 "TWSERVER01/TW"
DB_PATH = "moghuman\hmsign.nsf"  # 改成你剛查到的 File 路徑

db = notes.GetDatabase(SERVER, DB_PATH)

print("=== 所有 View 列表 ===")
views = db.Views
for v in views:
    print(f"  View: {v.Name}")