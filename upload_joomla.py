"""
Joomla 新聞稿上傳工具
用法: python upload_joomla.py [--dry-run]
- 從 checklist.json 找出尚未上傳的文章（略過標了 joomla_skip 的）
- 先用標題查官網，已經有的（例如人工上稿過）只記下文章 ID，不重複上傳
- 圖片上傳至 Joomla 媒體庫，任一張失敗就不建立文章，下次重跑
- 建立草稿文章（需至後台審核後手動發佈）
--dry-run：只查重、列出會做什麼，不上傳也不改 checklist
"""
import os, sys, json, base64, re, html, urllib3
import requests
from datetime import datetime
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

JOOMLA_URL   = os.getenv("JOOMLA_URL", "").rstrip("/")
JOOMLA_TOKEN = os.getenv("JOOMLA_TOKEN", "")
CATEGORY_ID  = int(os.getenv("JOOMLA_CATEGORY_ID", "8"))
MEDIA_FOLDER = os.getenv("JOOMLA_MEDIA_FOLDER", "images/news").strip("/")
OUTPUT_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
CHECKLIST    = os.path.join(OUTPUT_DIR, "checklist.json")

API_BASE = f"{JOOMLA_URL}/api/index.php/v1"
HEADERS  = {
    # 不用 Authorization: Bearer，Apache 常把這個標頭擋掉導致 401；X-Joomla-Token 同樣被 Joomla Token 外掛接受
    "X-Joomla-Token": JOOMLA_TOKEN,
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
        f"<p>{html.escape(p.strip(), quote=False).replace(chr(10), '<br>')}</p>"
        for p in paragraphs if p.strip()
    )


def clean_title(subject):
    """Notes 標題 → 官網標題：去掉開頭的日期編號「17/」與結尾的作者「(曾定嘉)」，比照人工上稿的寫法"""
    title = re.sub(r'^\d+/', '', subject.strip())
    title = re.sub(r'\s*[(（][^()（）]*[)）]$', '', title)
    return title.strip()


def find_existing_article(title):
    """用標題查官網是否已有這篇（含已發佈、未發佈），有的話回傳文章 ID，否則回傳 None
    比對時忽略所有空白（含全形空白），避免人工上稿時空白數不同而漏判"""
    def norm(s):
        return re.sub(r'\s+', '', s)
    # Joomla 的 filter[search] 是 LIKE 比對，空白寫法不同會搜不到，所以取標題中最長的一段來搜
    keyword = max(re.split(r'\s+', title), key=len)
    r = requests.get(f"{API_BASE}/content/articles", headers=HEADERS, timeout=30, verify=False,
                     params={"filter[search]": keyword, "page[limit]": 20})
    r.raise_for_status()
    for item in r.json().get("data", []):
        if norm(item["attributes"]["title"]) == norm(title):
            return int(item["id"])
    return None


def upload_image(local_path, media_path):
    """上傳圖片到 Joomla 媒體庫
    media_path: 相對於 Joomla 根目錄，例如 images/01news/2026/05/0513/img_000.jpg
    回傳完整圖片 URL
    """
    # Media API 的 path 要寫成「adapter:/路徑」，local-images 的根目錄已經是 images/，
    # 直接送 images/... 會被存成 images/images/...（2026-10-12 實測）
    if not media_path.startswith("images/"):
        raise ValueError(f"JOOMLA_MEDIA_FOLDER 必須在 images/ 底下: {media_path}")
    adapter_path = "local-images:/" + media_path[len("images/"):]

    with open(local_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()
    payload = {
        "path":     adapter_path,
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
        pub_up = pub_dt.strftime("%Y-%m-%d 08:00:00")
    except Exception:
        pub_up = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

DRY_RUN = "--dry-run" in sys.argv

pending = [(unid, e) for unid, e in checklist.items()
           if "joomla_id" not in e and "joomla_skip" not in e]
skipped = sum(1 for e in checklist.values() if "joomla_skip" in e)

print(f"Checklist 共 {len(checklist)} 篇")
print(f"已上傳/官網已有: {len(checklist) - len(pending) - skipped} 篇  /  不上傳: {skipped} 篇  /  待上傳: {len(pending)} 篇")
if DRY_RUN:
    print("【--dry-run】只查重、不上傳、不改 checklist")
print("=" * 60)

if not pending:
    print("沒有待上傳的文章。")
    exit()

success_count  = 0
existing_count = 0
fail_count     = 0

for unid, entry in pending:
    subject = entry["subject"]
    title   = clean_title(subject)
    folder  = os.path.join(OUTPUT_DIR, entry["folder"])
    print(f"\n{'─'*60}")
    print(f"上傳：{entry['date']}  {title}")

    if not os.path.isdir(folder):
        print(f"  [錯誤] 找不到資料夾: {folder}，略過")
        fail_count += 1
        continue

    # ── 0. 查重：官網已有同標題文章（例如已人工上稿）就只記下 ID ──
    try:
        existing_id = find_existing_article(title)
    except Exception as ex:
        print(f"  [錯誤] 查重失敗，為避免重複建立文章先略過: {ex}")
        fail_count += 1
        continue
    if existing_id:
        print(f"  官網已有此文章  Joomla ID={existing_id}，不重複上傳")
        existing_count += 1
        if not DRY_RUN:
            checklist[unid]["joomla_id"]          = existing_id
            checklist[unid]["joomla_existing"]    = True
            checklist[unid]["joomla_uploaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_checklist(checklist)
        continue
    if DRY_RUN:
        print("  官網沒有此文章 → 會上傳圖片並建立草稿")
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

    # 有任何一張圖失敗就不建立文章，下次重跑時整篇重來（圖片以 override 覆蓋，不會重複）
    if len(img_urls) < len(img_files):
        print(f"  {len(img_files) - len(img_urls)} 張圖片上傳失敗，本篇先不建立文章，下次重跑")
        fail_count += 1
        continue

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
        article_id = create_article(title, html_body, entry["date"])
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
print(f"完成！成功 {success_count} 篇，官網已有 {existing_count} 篇，失敗 {fail_count} 篇")
if success_count > 0:
    print(f"請至 Joomla 後台 → 文章管理 → 審核草稿後發佈")
