"""
新聞稿每日自動上稿（排程用）
用法: python news_daily.py [--days 7] [--always-notify]
1. query_news.py --days N：從 Notes 擷取最近 N 天的新聞稿（已下載的自動跳過）
2. upload_joomla.py：官網沒有的建成草稿；官網已有的只記 ID；標題相似的列為待確認
3. 有新草稿、待確認、失敗或錯誤時，用 LINE 推播通知（沒事就不發，--always-notify 則每次都發）
執行過程完整寫入 news_daily.log
注意：HCL Notes 用戶端開著時 Notes 會被鎖住，排程時間要避開有人使用這台電腦的時段
"""
import os, sys, json, argparse, subprocess
from datetime import datetime

import requests
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
PYTHON         = sys.executable
LOG_FILE       = os.path.join(BASE_DIR, "news_daily.log")
SUMMARY        = os.path.join(BASE_DIR, "output", "last_upload.json")
LINE_MAX_CHARS = 4800  # LINE 單則文字上限 5000，留一點餘裕

load_dotenv(os.path.join(BASE_DIR, ".env"))


def log(text):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_step(name, cmd, timeout):
    """執行子程式，輸出完整寫入 log，回傳 (exit code, 輸出文字)"""
    log(f"── {name}：{' '.join(cmd)}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run([PYTHON] + cmd, cwd=BASE_DIR, env=env, timeout=timeout,
                           stdin=subprocess.DEVNULL, capture_output=True)
        out = (p.stdout + p.stderr).decode("utf-8", errors="replace")
        code = p.returncode
    except subprocess.TimeoutExpired:
        out, code = f"執行超過 {timeout // 60} 分鐘，已中止", -1
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(out.rstrip() + "\n")
    log(f"── {name} 結束，exit code {code}")
    return code, out


def send_line(text):
    """比照 store/expiry_report.py：推播給 .env 的 LINE_USER_ID"""
    token   = os.getenv("LINE_CHANNEL_TOKEN", "")
    user_id = os.getenv("LINE_USER_ID", "")
    if not token or not user_id:
        raise RuntimeError(".env 缺少 LINE_CHANNEL_TOKEN／LINE_USER_ID")
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"to": user_id, "messages": [{"type": "text", "text": text[:LINE_MAX_CHARS]}]},
        timeout=15,
        verify=False,  # 院內網路 SSL 攔截，比照 auto_checkin.py
    )
    if resp.status_code != 200:
        raise RuntimeError(f"LINE push HTTP {resp.status_code}: {resp.text}")


def build_message(s):
    parts = [f"[新聞稿自動上稿] {datetime.now():%Y-%m-%d %H:%M}"]
    if s.get("error"):
        parts.append(f"\n❌ 執行錯誤：{s['error']}")
    if s["created"]:
        parts.append(f"\n✅ 新建草稿 {len(s['created'])} 篇，請到後台審核發佈：")
        parts += [f"・{a['id']} {a['title']}" for a in s["created"]]
    if s["review"]:
        parts.append(f"\n⚠️ 待確認 {len(s['review'])} 篇（官網有相似標題，先不上傳）：")
        for a in s["review"]:
            parts.append(f"・{a['date'][5:]} {a['title']}")
            parts += [f"   ≈ {c[0]} {c[1]}（相似度 {c[2]}）" for c in a["candidates"]]
            parts.append(f"   不同篇: upload_joomla.py --resolve {a['unid8']} new")
            parts.append(f"   同一篇: upload_joomla.py --resolve {a['unid8']} {a['candidates'][0][0]}")
    if s["failed"]:
        parts.append(f"\n❌ 失敗 {len(s['failed'])} 篇（下次排程會自動重試）：")
        parts += [f"・{a['title']}：{a['reason']}" for a in s["failed"]]
    older = s.get("review_open", 0) - len(s["review"])
    if older > 0:
        parts.append(f"\n另有 {older} 篇之前的待確認還沒處理")
    if not (s.get("error") or s["created"] or s["review"] or s["failed"]):
        parts.append("\n今天沒有新的新聞稿需要上傳")
    parts.append("\n詳細記錄：news_daily.log")
    return "\n".join(parts)


def notify(text):
    try:
        send_line(text)
        log("LINE 通知已送出")
    except Exception as ex:
        log(f"LINE 通知失敗: {ex}")


def main():
    parser = argparse.ArgumentParser(description="新聞稿每日自動上稿（排程用）")
    parser.add_argument("--days", type=int, default=7, help="擷取最近幾天的新聞稿（預設 7，含今天）")
    parser.add_argument("--always-notify", action="store_true", help="沒有新文章也發 LINE 通知")
    args = parser.parse_args()

    log(f"===== 新聞稿每日自動上稿開始（最近 {args.days} 天）=====")

    # 1. 從 Notes 擷取
    code, out = run_step("擷取新聞稿", ["query_news.py", "--days", str(args.days)], timeout=30 * 60)
    if code != 0:
        hint = "請關閉 HCL Notes 用戶端後再執行" if "鎖住" in out else "請查看 news_daily.log"
        notify(f"[新聞稿自動上稿] {datetime.now():%Y-%m-%d %H:%M}\n\n❌ 從 Notes 擷取新聞稿失敗，本次沒有上傳。\n{hint}")
        sys.exit(1)

    # 2. 上傳 Joomla（先刪掉舊摘要，避免讀到上一次的結果）
    if os.path.exists(SUMMARY):
        os.remove(SUMMARY)
    code, out = run_step("上傳 Joomla", ["upload_joomla.py"], timeout=30 * 60)
    try:
        with open(SUMMARY, encoding="utf-8") as f:
            summary = json.load(f)
    except Exception:
        summary = {"error": f"upload_joomla.py 沒有產生結果摘要（exit code {code}），請查看 news_daily.log",
                   "created": [], "existing": [], "review": [], "failed": [], "review_open": 0}

    # 3. 通知
    has_news = summary.get("error") or summary["created"] or summary["review"] or summary["failed"]
    if has_news or args.always_notify:
        notify(build_message(summary))
    else:
        log("沒有新草稿、待確認或錯誤，不發 LINE 通知")

    log("===== 結束 =====")
    sys.exit(1 if summary.get("error") or summary["failed"] else 0)


if __name__ == "__main__":
    main()
