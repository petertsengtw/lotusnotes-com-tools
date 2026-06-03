import win32com.client
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

SERVER     = "hladmin2/medicine/Tzuchi"
DB_PATH    = r"moghuman\hmsign.nsf"
DB_ARCHIVE = r"moghuman/hmsignfile.nsf"
USER       = "曾建瑋/medicine/Tzuchi"

DATE_FROM = datetime(2026, 5, 25, 0, 0, 0)
DATE_TO   = datetime(2026, 5, 31, 23, 59, 59)

STATUS_LABEL = {"1": "簽到", "0": "簽退"}
TYPE_LABEL   = {"N": "正常班", "A": "加班", "C": "OnCall", "S": "交接班"}

notes = win32com.client.Dispatch("Lotus.NotesSession")
notes.Initialize(os.getenv("NOTES_PASSWORD", ""))

print(f"查詢期間：{DATE_FROM:%Y/%m/%d} ~ {DATE_TO:%Y/%m/%d}")
print(f"人員：{USER}")
print("=" * 55)


def search_via_view(db, db_label):
    """用 View 索引查詢，避免全表掃描"""
    results = []
    # 先列出此資料庫有哪些 View 可用
    view = None
    for vname in ["所有簽到退卡", "(簽到退清單測試)"]:
        v = db.GetView(vname)
        if v:
            view = v
            print(f"  [{db_label}] 使用 View: {vname}")
            break

    if not view:
        print(f"  [{db_label}] 找不到可用 View，略過")
        return results

    # 用 EleSign 作為 key 直接跳到該使用者的資料
    entry = view.GetEntryByKey(USER, True)
    if not entry:
        # 嘗試簡短姓名
        short = USER.split("/")[0]
        entry = view.GetEntryByKey(short, True)

    if entry:
        print(f"  [{db_label}] 找到使用者紀錄，讀取中...")
        col = view.GetAllEntriesByKey(USER, True)
        if not col:
            col = view.GetAllEntriesByKey(USER.split("/")[0], True)
        if col:
            e = col.GetFirstEntry()
            while e:
                if e.IsDocument:
                    doc = e.Document
                    sign_time = doc.GetItemValue("fd_SignTime")
                    if sign_time:
                        t = sign_time[0]
                        if hasattr(t, "year"):
                            dt = datetime(t.year, t.month, t.day,
                                          t.hour, t.minute, t.second) + timedelta(hours=8)
                            if DATE_FROM <= dt <= DATE_TO:
                                status = doc.GetItemValue("fd_SignStatus")
                                stype  = doc.GetItemValue("fd_SignType")
                                results.append({
                                    "time":   dt,
                                    "status": STATUS_LABEL.get(status[0] if status else "", "?"),
                                    "type":   TYPE_LABEL.get(stype[0] if stype else "", "?"),
                                })
                e = col.GetNextEntry(e)
    else:
        print(f"  [{db_label}] 此 View 找不到 {USER}")

    return results


records = []
for path, label in [(DB_PATH, "當前"), (DB_ARCHIVE, "歸檔")]:
    print(f"  開啟 {label} 資料庫...")
    db = notes.GetDatabase(SERVER, path)
    if db and db.IsOpen:
        records += search_via_view(db, label)
    else:
        print(f"  [{label}] 無法開啟")

records.sort(key=lambda r: r["time"])
print()

if records:
    for r in records:
        print(f"  {r['time']:%Y/%m/%d %H:%M:%S}  {r['type']:6s}  {r['status']}")
else:
    print("  此期間無紀錄")

print("=" * 55)
print(f"共 {len(records)} 筆")
