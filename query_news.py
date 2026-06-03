"""
新聞稿查詢工具 - 含圖片擷取 + 重複下載偵測
用法: python query_news.py
"""
import win32com.client
from datetime import datetime
from dotenv import load_dotenv
import os, re, base64, json
from xml.etree import ElementTree as ET

load_dotenv()

SERVER     = "mdaapa/medicine/Tzuchi"
DB_PATH    = r"OAuse\mddpdoc.nsf"
OUTPUT_DIR = r"c:\Users\peter\Desktop\autoRPA2-lotusNotesAPI\output"
CHECKLIST  = os.path.join(OUTPUT_DIR, "checklist.json")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Checklist 讀寫 ────────────────────────────────────
def load_checklist():
    if os.path.exists(CHECKLIST):
        with open(CHECKLIST, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_checklist(data):
    with open(CHECKLIST, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── 輸入日期 ──────────────────────────────────────────
def ask_date(prompt):
    while True:
        s = input(prompt).strip()
        try:
            return datetime.strptime(s, "%Y/%m/%d")
        except ValueError:
            print("  格式錯誤，請輸入 YYYY/MM/DD")

date_from = ask_date("起始日期 (YYYY/MM/DD): ")
date_to   = ask_date("結束日期 (YYYY/MM/DD): ").replace(hour=23, minute=59, second=59)

# ── 連線 Notes ────────────────────────────────────────
notes = win32com.client.Dispatch("Lotus.NotesSession")
notes.Initialize(os.getenv("NOTES_PASSWORD", ""))
db = notes.GetDatabase(SERVER, DB_PATH)

exporter = notes.CreateDXLExporter()
exporter.ConvertNotesbitmapsToGIF = False
exporter.OutputDOCTYPE = False

checklist = load_checklist()

view = db.GetView("新聞稿")
print(f"\n查詢期間：{date_from:%Y/%m/%d} ~ {date_to:%Y/%m/%d}")
print("=" * 60)

# ── 收集符合日期的文件 ────────────────────────────────
records = []
entries = view.AllEntries
e = entries.GetFirstEntry()
while e:
    if e.IsDocument:
        doc = e.Document
        fd = doc.GetItemValue("fd_Date")
        if fd and hasattr(fd[0], "year"):
            dt = datetime(fd[0].year, fd[0].month, fd[0].day)
            if date_from <= dt <= date_to:
                subject = doc.GetItemValue("Subject")
                records.append((dt, doc, subject[0] if subject else "(無標題)"))
    e = entries.GetNextEntry(e)

total      = len(records)
skip_count = 0
new_count  = 0

print(f"找到 {total} 筆新聞稿")

# 先統計有幾篇已下載
for dt, doc, subject in records:
    if doc.UniversalID in checklist:
        skip_count += 1

print(f"已下載: {skip_count} 篇  /  待下載: {total - skip_count} 篇\n")

# ── 逐篇處理 ─────────────────────────────────────────
for i, (dt, doc, subject) in enumerate(sorted(records, key=lambda x: x[0]), 1):
    unid = doc.UniversalID
    print(f"{'─'*60}")

    # 計算資料夾路徑（用於雙重比對）
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', subject)[:50]
    doc_dir   = os.path.join(OUTPUT_DIR, f"{dt:%Y%m%d}_{safe_name}")
    folder_exists = os.path.exists(os.path.join(doc_dir, "content.txt"))

    if unid in checklist:
        entry = checklist[unid]
        print(f"[{i}/{total}] {dt:%Y/%m/%d}  {subject}")
        print(f"  [已下載] 跳過  (下載於 {entry['downloaded_at'][:10]}，"
              f"文字 {entry['chars']} 字，圖片 {entry['images']} 張)")
        print()
        continue

    if folder_exists:
        print(f"[{i}/{total}] {dt:%Y/%m/%d}  {subject}")
        print(f"  [資料夾已存在] 跳過，並補登 checklist")
        img_count = len([f for f in os.listdir(doc_dir) if f.startswith("img_")])
        checklist[unid] = {
            "date":          dt.strftime("%Y/%m/%d"),
            "subject":       subject,
            "folder":        os.path.basename(doc_dir),
            "chars":         -1,
            "images":        img_count,
            "downloaded_at": "（補登）",
        }
        save_checklist(checklist)
        skip_count += 1
        print()
        continue

    print(f"[{i}/{total}] {dt:%Y/%m/%d}  {subject}  ← 新下載")

    # 建立輸出資料夾（safe_name / doc_dir 已在上方計算）
    os.makedirs(doc_dir, exist_ok=True)

    # ── 文字內容 ──────────────────────────────────────
    body = doc.GetFirstItem("Body")
    text = ""
    if body:
        try:
            text = body.Text or ""
        except:
            pass
    if text:
        text = re.sub(r'\n{3,}', '\n\n', text.strip())
        txt_path = os.path.join(doc_dir, "content.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"{subject}\n{'='*60}\n\n{text}")
        print(f"  文字: {len(text)} 字 → content.txt")

    # ── 圖片（DXL 匯出）──────────────────────────────
    img_count = 0
    try:
        dxl  = exporter.Export(doc)
        root = ET.fromstring(dxl)
        for tag, ext in [("jpeg", ".jpg"), ("gif", ".gif"), ("png", ".png")]:
            for node in root.iter(f"{{http://www.lotus.com/dxl}}{tag}"):
                if node.text:
                    img_path = os.path.join(doc_dir, f"img_{img_count:03d}{ext}")
                    with open(img_path, "wb") as f:
                        f.write(base64.b64decode(node.text.strip()))
                    img_count += 1
        if img_count > 0:
            print(f"  圖片: {img_count} 張 → {doc_dir}")
        else:
            print(f"  圖片: 無")
    except Exception as ex:
        print(f"  圖片擷取失敗: {ex}")

    # ── 寫入 checklist ────────────────────────────────
    checklist[unid] = {
        "date":          dt.strftime("%Y/%m/%d"),
        "subject":       subject,
        "folder":        os.path.basename(doc_dir),
        "chars":         len(text),
        "images":        img_count,
        "downloaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_checklist(checklist)
    new_count += 1
    print()

print("=" * 60)
print(f"本次新下載 {new_count} 篇，略過 {skip_count} 篇（已下載）")
print(f"輸出資料夾: {OUTPUT_DIR}")
print(f"Checklist:  {CHECKLIST}")
