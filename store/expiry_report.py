"""
特約商店到期提醒（續約管理第一階段，只讀 Notes，不會修改任何資料）。
用法:
    python expiry_report.py            # 列出「已過期」與「60 天內到期」的店家
    python expiry_report.py --notify   # 同上，並把「還沒通知過」的店家用 LINE 推播（排程用）
    python expiry_report.py --days 90  # 改用 90 天的提醒範圍

為什麼要提前 60 天：合約第六條規定期限屆滿前一個月未以書面通知不續約，就自動延長
一年。提前 60 天提醒，才有時間在「屆滿前一個月」這個期限之前決定要不要續約。

--notify 會記錄已通知過哪些店家（store/output/expiry_notified.json），同一家店、同一個
到期日只會在「進入 60 天範圍」與「到期後」各通知一次，每天排程執行也不會重複洗版；
某天執行失敗（例如 Notes 開著），隔天會一併補通知。到期日在 Notes 改過（續約展延）
的店家視為新的一輪，下次進入 60 天範圍時會再通知。

執行前要先關閉 HCL Notes 用戶端（開著時 ID 檔會被鎖住）。
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

import requests
import urllib3
from dotenv import load_dotenv

from notes_store import fetch_active_stores

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
STATE_FILE = os.path.join(OUTPUT_DIR, "expiry_notified.json")
LINE_MAX_CHARS = 4800  # LINE 單則文字上限 5000，留一點餘裕


def classify(stores, today, days, expired_days):
    """回傳 (expired, expiring, stale_count)。
    expired：最近 expired_days 天內到期、尚未作廢的店家（同仁查詢頁已看不到）
    expiring：今天起 days 天內到期的店家
    stale_count：過期超過 expired_days 天仍未作廢的店家數（多半是早就不合作、Notes 沒標作廢）"""
    expired, expiring, stale = [], [], 0
    for s in stores:
        if not s["expire"]:
            continue
        exp = date.fromisoformat(s["expire"])
        left = (exp - today).days
        if left < 0:
            if -left <= expired_days:
                expired.append({**s, "days": left})
            else:
                stale += 1
        elif left <= days:
            expiring.append({**s, "days": left})
    expired.sort(key=lambda s: s["expire"])
    expiring.sort(key=lambda s: (s["expire"], s["name"]))
    return expired, expiring, stale


def one_line(text):
    """Notes 欄位常有多行（例如電話寫了好幾支），報表裡壓成一行。"""
    return " / ".join(part.strip() for part in (text or "").splitlines() if part.strip())


def line_of(s):
    if s["days"] < 0:
        return f"・{s['name']}（{s['kind']}）{s['expire']} 到期，已過 {-s['days']} 天"
    return f"・{s['name']}（{s['kind']}）{s['expire']} 到期，剩 {s['days']} 天"


def print_report(expired, expiring, stale, today, days, expired_days):
    print(f"特約商店到期檢查（{today}，提醒範圍 {days} 天）")
    print("=" * 60)
    print(f"\n【已過期，同仁查詢頁已看不到】{len(expired)} 家（最近 {expired_days} 天內到期）")
    for s in expired:
        print("  " + line_of(s) + f"　電話：{one_line(s['tel']) or '（未填）'}")
    print(f"\n【{days} 天內到期】{len(expiring)} 家")
    for s in expiring:
        print("  " + line_of(s) + f"　電話：{one_line(s['tel']) or '（未填）'}")
    if stale:
        print(f"\n另有 {stale} 家過期超過 {expired_days} 天仍未在 Notes 標記作廢（可用 --expired-days 調大範圍列出）")
    print("\n提醒：合約第六條規定屆滿前一個月未書面通知不續約即自動延長一年；"
          "決定續約的店家記得到 Notes 延長到期日並同步，否則到期後會從查詢頁消失。")


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def state_key(s, kind):
    # 帶上到期日：Notes 裡到期日延長（續約）後就是新的一輪，會重新提醒
    return f"{kind}|{s['name']}|{s['expire']}"


def send_line(text):
    token = os.getenv("LINE_CHANNEL_TOKEN", "")
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


def build_message(new_expired, new_expiring, today, days):
    parts = [f"[特約商店到期提醒] {today}"]
    if new_expired:
        parts.append(f"\n⚠️ 已到期（查詢頁已看不到）{len(new_expired)} 家：")
        parts += [line_of(s) for s in new_expired]
    if new_expiring:
        parts.append(f"\n⏰ {days} 天內到期 {len(new_expiring)} 家：")
        parts += [line_of(s) for s in new_expiring]
    parts.append("\n續約請到 Notes 延長到期日並同步；不續約請於到期前一個月書面通知店家。"
                 "完整清單：menu.py →「特約商店到期檢查」")
    return "\n".join(parts)


def main():
    p = argparse.ArgumentParser(description="特約商店到期提醒（只讀）")
    p.add_argument("--days", type=int, default=60, help="提前幾天提醒（預設 60）")
    p.add_argument("--expired-days", type=int, default=180, help="已過期的店家列出最近幾天內的（預設 180）")
    p.add_argument("--notify", action="store_true", help="把還沒通知過的店家用 LINE 推播（排程用）")
    args = p.parse_args()

    today = date.today()
    try:
        stores = fetch_active_stores(include_expired=True)
    except Exception as e:
        msg = f"讀取 Notes 失敗：{e}"
        print(msg)
        if args.notify:
            hint = "請關閉 HCL Notes 用戶端，明天排程會自動補通知" if "鎖住" in str(e) else "請查看執行紀錄"
            try:
                send_line(f"[特約商店到期提醒] ⚠️ {today} 檢查失敗\n{e}\n{hint}")
            except Exception as e2:
                print(f"LINE 通知也失敗：{e2}")
        sys.exit(1)

    expired, expiring, stale = classify(stores, today, args.days, args.expired_days)
    print_report(expired, expiring, stale, today, args.days, args.expired_days)

    if not args.notify:
        return

    state = load_state()
    new_expired = [s for s in expired if state_key(s, "expired") not in state]
    new_expiring = [s for s in expiring if state_key(s, "expiring") not in state]
    if not new_expired and not new_expiring:
        print("\n沒有新的需要通知的店家，不發 LINE")
        return

    send_line(build_message(new_expired, new_expiring, today, args.days))
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    for s in new_expired:
        state[state_key(s, "expired")] = stamp
    for s in new_expiring:
        state[state_key(s, "expiring")] = stamp
    save_state(state)
    print(f"\n已發 LINE 通知：新到期 {len(new_expired)} 家、新進入 {args.days} 天範圍 {len(new_expiring)} 家")


if __name__ == "__main__":
    main()
