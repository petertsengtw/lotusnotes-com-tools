"""
Joomla 新聞稿上傳工具
用法: python upload_joomla.py [--dry-run]
      python upload_joomla.py --resolve <UNID前8碼> new|<Joomla文章ID>
- 從 checklist.json 找出尚未上傳的文章（略過標了 joomla_skip、或待確認 joomla_review 的）
- 先用標題查官網，已經有的（例如人工上稿過）只記下文章 ID，不重複上傳
- 標題不同但很像官網近期文章的（人工上稿時改過標題），標成待確認 joomla_review，不上傳
- 圖片上傳至 Joomla 媒體庫，任一張失敗就不建立文章，下次重跑
- 建立草稿文章（需至後台審核後手動發佈）
- 結果摘要寫到 output/last_upload.json，給 news_daily.py 發 LINE 通知
--dry-run：只查重、列出會做什麼，不上傳也不改 checklist
--resolve：處理待確認的文章；new＝確定是新文章，下次照常上傳；文章 ID＝跟官網那篇是同一篇，記下 ID 不上傳
"""
import os, sys, json, base64, re, html, difflib, argparse, urllib3
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
SUMMARY      = os.path.join(OUTPUT_DIR, "last_upload.json")

# 相似標題門檻（2026-10-12 用實際資料校正）：人工改過標題的同一篇約 0.83，
# 無關文章多在 0.42 以下；但「○○節門診停診訊息」這類套版標題不同節日也有 0.69，所以再加日期條件
SIMILAR_RATIO = 0.6
SIMILAR_DAYS  = 30

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


# 人工上稿不放進內文的行：標題（另外比對）、Notes 表頭的「紀錄:」、文末的撰文者／報導
SKIP_LINE = re.compile(r'^(紀錄[:：]|撰文者?[:：]|報\s*導[:：])')


def layout_to_html(blocks, title, img_tags):
    """layout.json → HTML，排版比照人工上稿：
    圖片照 Notes 原本的位置放、同一段的圖片放同一個 <p>；圖說（緊接在圖片後的文字段）用 <br /> 合併在圖片下方；
    空行分段、去掉段首全形空白；略過標題、紀錄、撰文者、報導
    img_tags: {檔名: <img> 標籤}"""
    paras, cur = [], []

    def flush():
        if cur:
            paras.append("<p>" + "<br />".join(cur) + "</p>")
            cur.clear()

    for b in blocks:
        if b["type"] == "images":
            flush()
            tags = [img_tags[f] for f in b["files"] if f in img_tags]
            if tags:
                paras.append("<p>" + "".join(tags) + "</p>")
            continue
        for line in b["text"].split("\n"):
            line = line.strip()          # str.strip() 會一併去掉全形空白
            if not line:
                flush()
            elif SKIP_LINE.match(line) or re.sub(r'\s+', '', line) == re.sub(r'\s+', '', title):
                continue
            else:
                cur.append(html.escape(line, quote=False))
    flush()
    return "\n".join(paras)


def text_to_html(content_txt):
    """content.txt → HTML（略過標題行與分隔線）；舊的下載沒有 layout.json 時才用"""
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


def fetch_recent_articles(limit=200):
    """官網最新的 limit 篇文章 [(id, 標題, 建立日期 date)]，給相似標題比對用"""
    r = requests.get(f"{API_BASE}/content/articles", headers=HEADERS, timeout=30, verify=False,
                     params={"page[limit]": limit, "list[ordering]": "a.id", "list[direction]": "desc"})
    r.raise_for_status()
    result = []
    for item in r.json().get("data", []):
        a = item["attributes"]
        try:
            created = datetime.strptime(a.get("created", "")[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        result.append((int(item["id"]), a["title"], created))
    return result


def find_similar_articles(title, news_date, recent):
    """標題相似度 ≥ SIMILAR_RATIO、且建立日期在新聞稿日期前後 SIMILAR_DAYS 天內的官網文章，依相似度排序
    回傳 [(id, 標題, 相似度)]"""
    def norm(s):
        return re.sub(r'[\s\W_]+', '', s)    # 忽略空白與標點
    d = datetime.strptime(news_date, "%Y/%m/%d").date()
    hits = []
    for aid, atitle, created in recent:
        if abs((created - d).days) > SIMILAR_DAYS:
            continue
        ratio = difflib.SequenceMatcher(None, norm(title), norm(atitle)).ratio()
        if ratio >= SIMILAR_RATIO:
            hits.append((aid, atitle.strip(), round(ratio, 2)))
    return sorted(hits, key=lambda h: -h[2])


def write_summary(summary):
    with open(SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


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
    回傳 (完整圖片 URL, 摘要圖片欄位值, 內文用的 <img> 標籤)
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
    url   = f"{JOOMLA_URL}/{media_path}"
    attrs = r.json()["data"]["attributes"]
    size  = f' width="{attrs["width"]}" height="{attrs["height"]}"' if attrs.get("width") and attrs.get("height") else ""
    # 內文圖片用相對路徑，比照人工上稿
    return url, intro_image_value(url, adapter_path, attrs), f'<img src="{media_path}" alt=""{size} />'



def intro_image_value(url, adapter_path, attrs):
    """組出文章「摘要圖片」欄位值，格式比照後台人工上稿：
    完整網址#joomlaImage://local-images/路徑?width=寬&height=高"""
    value = f"{url}#joomlaImage://{adapter_path.replace(':/', '/', 1)}"
    if attrs.get("width") and attrs.get("height"):
        value += f"?width={attrs['width']}&height={attrs['height']}"
    return value


def create_article(title, html_body, pub_date_str, intro_image=""):
    """在 Joomla 建立草稿文章，回傳文章 ID
    intro_image: 摘要圖片欄位值（第一張圖），沒有圖片就留空"""
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
        # 只設摘要圖片，全文圖片留空，比照人工上稿
        "images": {
            "image_intro": intro_image, "image_intro_alt": "", "float_intro": "", "image_intro_caption": "",
            "image_fulltext": "", "image_fulltext_alt": "", "float_fulltext": "", "image_fulltext_caption": "",
        },
    }
    r = requests.post(f"{API_BASE}/content/articles", headers=HEADERS, json=payload, timeout=30, verify=False)
    r.raise_for_status()
    return r.json()["data"]["id"]


# ── 參數 ───────────────────────────────────────────────
parser = argparse.ArgumentParser(description="把 query_news.py 下載的新聞稿上傳成 Joomla 草稿")
parser.add_argument("--dry-run", action="store_true", help="只查重、列出會做什麼，不上傳也不改 checklist")
parser.add_argument("--resolve", nargs=2, metavar=("UNID前8碼", "new|文章ID"),
                    help="處理待確認文章：new＝確定是新文章，下次照常上傳；文章ID＝跟官網那篇是同一篇")
args    = parser.parse_args()
DRY_RUN = args.dry_run
NOW     = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── 處理待確認文章（--resolve）：只改本機 checklist，不連 Joomla ──
if args.resolve:
    key, target = args.resolve[0].upper(), args.resolve[1]
    checklist   = load_checklist()
    matches     = [u for u in checklist if u.upper().startswith(key)]
    if len(matches) != 1:
        print(f"找不到唯一一篇 UNID 開頭為 {key} 的文章（符合 {len(matches)} 篇）")
        sys.exit(1)
    entry = checklist[matches[0]]
    entry.pop("joomla_review", None)
    if target.lower() == "new":
        entry["joomla_force_new"] = True        # 下次上傳時略過相似標題檢查
        print(f"已標記為新文章，下次執行會上傳：{entry['subject']}")
    elif target.isdigit():
        entry["joomla_id"]          = int(target)
        entry["joomla_existing"]    = True
        entry["joomla_uploaded_at"] = NOW()
        entry["joomla_note"]        = "相似標題人工確認為同一篇（--resolve）"
        print(f"已對應到官網文章 {target}，不會上傳：{entry['subject']}")
    else:
        print("第二個參數請填 new 或 Joomla 文章 ID")
        sys.exit(1)
    save_checklist(checklist)
    sys.exit(0)

summary = {"run_at": NOW(), "dry_run": DRY_RUN, "error": None,
           "created": [], "existing": [], "review": [], "failed": [], "review_open": 0}

# ── 連線測試 ───────────────────────────────────────────
print("測試 Joomla API 連線...")
print(f"  URL  : {API_BASE}")
try:
    r = requests.get(f"{API_BASE}/content/articles?page[limit]=1",
                     headers=HEADERS, timeout=10, verify=False,
                     allow_redirects=True)
    print(f"  HTTP : {r.status_code}")
    r.raise_for_status()
    print(f"\n  連線成功！\n")
except Exception as ex:
    print(f"\n  連線失敗: {ex}")
    print("  請確認 JOOMLA_URL / JOOMLA_TOKEN、Joomla API 外掛，以及網站伺服器的 API 白名單（見 README 功能三）")
    summary["error"] = f"Joomla API 連線失敗: {ex}"
    write_summary(summary)
    sys.exit(1)

# ── 主程式 ─────────────────────────────────────────────
checklist = load_checklist()

if not checklist:
    print("checklist.json 不存在或為空，請先執行 query_news.py 下載文章。")
    write_summary(summary)
    sys.exit(0)

pending = [(unid, e) for unid, e in checklist.items()
           if "joomla_id" not in e and "joomla_skip" not in e and "joomla_review" not in e]
skipped = sum(1 for e in checklist.values() if "joomla_skip" in e)
waiting = sum(1 for e in checklist.values() if "joomla_review" in e and "joomla_id" not in e)

print(f"Checklist 共 {len(checklist)} 篇")
print(f"已上傳/官網已有: {len(checklist) - len(pending) - skipped - waiting} 篇  /  不上傳: {skipped} 篇  /  "
      f"待確認: {waiting} 篇  /  待上傳: {len(pending)} 篇")
if DRY_RUN:
    print("【--dry-run】只查重、不上傳、不改 checklist")
print("=" * 60)

recent = []
if pending:
    try:
        recent = fetch_recent_articles()
    except Exception as ex:
        # 拿不到近期文章就無法做相似標題檢查，寧可這次都不傳
        print(f"[錯誤] 讀取官網近期文章失敗，本次不上傳: {ex}")
        summary["error"] = f"讀取官網近期文章失敗: {ex}"
        pending = []

for unid, entry in pending:
    subject = entry["subject"]
    title   = clean_title(subject)
    folder  = os.path.join(OUTPUT_DIR, entry["folder"])
    brief   = {"unid8": unid[:8].upper(), "date": entry["date"], "title": title}
    print(f"\n{'─'*60}")
    print(f"上傳：{entry['date']}  {title}")

    if not os.path.isdir(folder):
        print(f"  [錯誤] 找不到資料夾: {folder}，略過")
        summary["failed"].append({**brief, "reason": "找不到本機資料夾"})
        continue

    # ── 0a. 查重：官網已有同標題文章（例如已人工上稿）就只記下 ID ──
    try:
        existing_id = find_existing_article(title)
    except Exception as ex:
        print(f"  [錯誤] 查重失敗，為避免重複建立文章先略過: {ex}")
        summary["failed"].append({**brief, "reason": f"查重失敗: {ex}"})
        continue
    if existing_id:
        print(f"  官網已有此文章  Joomla ID={existing_id}，不重複上傳")
        summary["existing"].append({**brief, "id": existing_id})
        if not DRY_RUN:
            entry["joomla_id"]          = existing_id
            entry["joomla_existing"]    = True
            entry["joomla_uploaded_at"] = NOW()
            save_checklist(checklist)
        continue

    # ── 0b. 相似標題：人工上稿時可能改過標題，交給人確認，不上傳 ──
    if not entry.get("joomla_force_new"):
        similar = find_similar_articles(title, entry["date"], recent)
        if similar:
            for aid, atitle, ratio in similar[:3]:
                print(f"  官網有相似標題（{ratio}）: {aid} {atitle}")
            print(f"  → 列為待確認，不上傳。處理方式: upload_joomla.py --resolve {brief['unid8']} new|<文章ID>")
            summary["review"].append({**brief, "candidates": [list(s) for s in similar[:3]]})
            if not DRY_RUN:
                entry["joomla_review"] = {"candidates": [list(s) for s in similar[:3]], "flagged_at": NOW()}
                save_checklist(checklist)
            continue

    if DRY_RUN:
        print("  官網沒有此文章 → 會上傳圖片並建立草稿")
        continue

    # ── 1. 上傳圖片 ──────────────────────────────────
    # 依日期 + UNID 前8碼組合子目錄：images/01news/2026/05/0513/BCE1730B
    d               = entry["date"]      # "2026/05/13"
    year, mon, day  = d[:4], d[5:7], d[8:10]
    img_subdir      = f"{MEDIA_FOLDER}/{year}/{mon}/{mon}{day}/{brief['unid8']}"

    img_urls    = []
    img_tags    = {}
    intro_image = ""
    img_files = sorted(
        f for f in os.listdir(folder)
        if re.match(r'img_\d+\.(jpg|gif|png)$', f, re.IGNORECASE)
    )
    for img_file in img_files:
        media_path = f"{img_subdir}/{img_file}"   # e.g. images/01news/2026/05/0513/img_000.jpg
        local_path = os.path.join(folder, img_file)
        try:
            url, intro_value, img_tags[img_file] = upload_image(local_path, media_path)
            img_urls.append(url)
            if not intro_image:            # 第一張圖當摘要圖片
                intro_image = intro_value
            print(f"  圖片: {media_path} → 上傳成功")
        except Exception as ex:
            print(f"  圖片: {img_file} → 上傳失敗: {ex}")

    # 有任何一張圖失敗就不建立文章，下次重跑時整篇重來（圖片以 override 覆蓋，不會重複）
    if len(img_urls) < len(img_files):
        print(f"  {len(img_files) - len(img_urls)} 張圖片上傳失敗，本篇先不建立文章，下次重跑")
        summary["failed"].append({**brief, "reason": f"{len(img_files) - len(img_urls)} 張圖片上傳失敗"})
        continue

    # ── 2. 組內文 HTML ───────────────────────────────
    # 有 layout.json（新版 query_news.py 產生）就照 Notes 原本順序放圖片與圖說；
    # 舊的下載沒有 layout.json，才退回「純文字 + 圖片放文末」
    layout_path = os.path.join(folder, "layout.json")
    txt_path    = os.path.join(folder, "content.txt")
    html_body   = ""
    if os.path.exists(layout_path):
        with open(layout_path, "r", encoding="utf-8") as f:
            html_body = layout_to_html(json.load(f), title, img_tags)
    elif os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            html_body = text_to_html(f.read())

    if img_urls and not os.path.exists(layout_path):
        html_body += '\n<div class="news-images" style="margin-top:1.5em;">\n'
        for url in img_urls:
            html_body += f'  <img src="{url}" alt="" style="max-width:100%;margin:4px 0;">\n'
        html_body += '</div>'

    # ── 3. 建立草稿文章 ──────────────────────────────
    try:
        article_id = create_article(title, html_body, entry["date"], intro_image)
        print(f"  文章建立成功  Joomla ID={article_id}  （草稿）")
        entry["joomla_id"]          = article_id
        entry["joomla_uploaded_at"] = NOW()
        save_checklist(checklist)
        summary["created"].append({**brief, "id": int(article_id)})
    except Exception as ex:
        print(f"  文章建立失敗: {ex}")
        if hasattr(ex, "response") and ex.response is not None:
            print(f"  回應內容: {ex.response.text[:300]}")
        summary["failed"].append({**brief, "reason": f"建立文章失敗: {ex}"})

summary["review_open"] = sum(1 for e in checklist.values() if "joomla_review" in e and "joomla_id" not in e)
write_summary(summary)

print("\n" + "=" * 60)
print(f"完成！新建草稿 {len(summary['created'])} 篇，官網已有 {len(summary['existing'])} 篇，"
      f"待確認 {len(summary['review'])} 篇，失敗 {len(summary['failed'])} 篇")
if summary["created"]:
    print(f"請至 Joomla 後台 → 文章管理 → 審核草稿後發佈")
