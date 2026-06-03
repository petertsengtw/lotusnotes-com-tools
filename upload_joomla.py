"""
Joomla 新聞稿上傳工具
用法: python upload_joomla.py
- 從 checklist.json 找出尚未上傳的文章
- 圖片上傳至 Joomla 媒體庫
- 建立草稿文章（需至後台審核後手動發佈）
"""
import os, json, base64, re, urllib3
import requests
from datetime import datetime
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

JOOMLA_URL   = os.getenv("JOOMLA_URL", "").rstrip("/")
JOOMLA_TOKEN = os.getenv("JOOMLA_TOKEN", "")
CATEGORY_ID  = int(os.getenv("JOOMLA_CATEGORY_ID", "8"))
MEDIA_FOLDER = os.getenv("JOOMLA_MEDIA_FOLDER", "images/news").strip("/")
OUTPUT_DIR   = r"c:\Users\peter\Desktop\autoRPA2-lotusNotesAPI\output"
CHECKLIST    = os.path.join(OUTPUT_DIR, "checklist.json")

API_BASE = f"{JOOMLA_URL}/api/index.php/v1"
HEADERS  = {
    "Authorization": f"Bearer {JOOMLA_TOKEN}",
    "Content-Type":  "application/json",
    "Accept":        "application/vnd.api+json",
}


def load_checklist():
    if os.path.exists(CHECKLIST):
        with open(CHECKLIST, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_checklist(data):
    with open(CHECKLIST, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def text_to_html(content_txt):
    """content.txt → HTML（略過標題行與分隔線）"""
    lines = content_txt.split("\n")
    # 格式: 第1行=標題, 第2行=====, 第3行空白, 之後=內文
    body_text = "\n".join(lines[3:]).strip() if len(lines) > 3 else content_txt
    paragraphs = re.split(r'\n{2,}', body_text)
    return "\n".join(
        f"<p>{p.strip().replace(chr(10), '<br>')}</p>"
        for p in paragraphs if p.strip()
    )


def upload_image(local_path, media_path):
    """上傳圖片到 Joomla 媒體庫
    media_path: 相對於 Joomla 根目錄，例如 images/01news/2026/05/0513/img_000.jpg
    回傳完整圖片 URL
    """
    with open(local_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()
    payload = {
        "path":     media_path,
        "content":  encoded,
        "override": True,
    }
    r = requests.post(f"{API_BASE}/media/files", headers=HEADERS, json=payload, timeout=30, verify=False)
    r.raise_for_status()
    return f"{JOOMLA_URL}/{media_path}"


def create_article(title, html_body, pub_date_str):
    """在 Joomla 建立草稿文章，回傳文章 ID"""
    try:
        pub_dt = datetime.strptime(pub_date_str, "%Y/%m/%d")
        pub_up = pub_dt.strftime("%Y-%m-%dT08:00:00")
    except Exception:
        pub_up = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    payload = {
        "title":       title,
        "articletext": html_body,
        "catid":       CATEGORY_ID,
        "state":       0,          # 草稿，手動審核後再發佈
        "language":    "*",
        "publish_up":  pub_up,
    }
    r = requests.post(f"{API_BASE}/content/articles", headers=HEADERS, json=payload, timeout=30, verify=False)
    r.raise_for_status()
    return r.json()["data"]["id"]


# ── 連線測試 ───────────────────────────────────────────
print("測試 Joomla API 連線...")
print(f"  URL  : {API_BASE}")
print(f"  Token: {JOOMLA_TOKEN[:10]}...（前10碼）")
try:
    r = requests.get(f"{API_BASE}/content/articles?page[limit]=1",
                     headers=HEADERS, timeout=10, verify=False,
                     allow_redirects=True)
    print(f"  HTTP : {r.status_code}  最終URL: {r.url}")
    print(f"  回應 : {r.text[:400]}")
    r.raise_for_status()
    print(f"\n  連線成功！\n")
except requests.exceptions.HTTPError as ex:
    print(f"\n  連線失敗: {ex}")
    print("  請確認 JOOMLA_URL / JOOMLA_TOKEN 是否正確，以及 Joomla API 是否已啟用")
    exit(1)
except Exception as ex:
    print(f"\n  連線失敗: {ex}")
    exit(1)

# ── 主程式 ─────────────────────────────────────────────
checklist = load_checklist()

if not checklist:
    print("checklist.json 不存在或為空，請先執行 query_news.py 下載文章。")
    exit()

pending = [(unid, e) for unid, e in checklist.items() if "joomla_id" not in e]

print(f"Checklist 共 {len(checklist)} 篇")
print(f"已上傳: {len(checklist) - len(pending)} 篇  /  待上傳: {len(pending)} 篇")
print("=" * 60)

if not pending:
    print("沒有待上傳的文章。")
    exit()

success_count = 0
fail_count    = 0

for unid, entry in pending:
    subject = entry["subject"]
    folder  = os.path.join(OUTPUT_DIR, entry["folder"])
    print(f"\n{'─'*60}")
    print(f"上傳：{entry['date']}  {subject}")

    if not os.path.isdir(folder):
        print(f"  [錯誤] 找不到資料夾: {folder}，略過")
        fail_count += 1
        continue

    # ── 1. 上傳圖片 ──────────────────────────────────
    # 依日期 + UNID 前8碼組合子目錄：images/01news/2026/05/0513/BCE1730B
    d               = entry["date"]      # "2026/05/13"
    year, mon, day  = d[:4], d[5:7], d[8:10]
    unid_short      = unid[:8].upper()
    img_subdir      = f"{MEDIA_FOLDER}/{year}/{mon}/{mon}{day}/{unid_short}"

    img_urls  = []
    img_files = sorted(
        f for f in os.listdir(folder)
        if re.match(r'img_\d+\.(jpg|gif|png)$', f, re.IGNORECASE)
    )
    for img_file in img_files:
        media_path = f"{img_subdir}/{img_file}"   # e.g. images/01news/2026/05/0513/img_000.jpg
        local_path = os.path.join(folder, img_file)
        try:
            url = upload_image(local_path, media_path)
            img_urls.append(url)
            print(f"  圖片: {media_path} → 上傳成功")
        except Exception as ex:
            print(f"  圖片: {img_file} → 上傳失敗: {ex}")

    # ── 2. 讀取文字並轉 HTML ─────────────────────────
    txt_path  = os.path.join(folder, "content.txt")
    html_body = ""
    if os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            html_body = text_to_html(f.read())

    # 圖片附加在文章末尾
    if img_urls:
        html_body += '\n<div class="news-images" style="margin-top:1.5em;">\n'
        for url in img_urls:
            html_body += f'  <img src="{url}" alt="" style="max-width:100%;margin:4px 0;">\n'
        html_body += '</div>'

    # ── 3. 建立草稿文章 ──────────────────────────────
    try:
        article_id = create_article(subject, html_body, entry["date"])
        print(f"  文章建立成功  Joomla ID={article_id}  （草稿）")
        checklist[unid]["joomla_id"]          = article_id
        checklist[unid]["joomla_uploaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_checklist(checklist)
        success_count += 1
    except Exception as ex:
        print(f"  文章建立失敗: {ex}")
        if hasattr(ex, "response") and ex.response is not None:
            print(f"  回應內容: {ex.response.text[:300]}")
        fail_count += 1

print("\n" + "=" * 60)
print(f"完成！成功 {success_count} 篇，失敗 {fail_count} 篇")
if success_count > 0:
    print(f"請至 Joomla 後台 → 文章管理 → 審核草稿後發佈")
