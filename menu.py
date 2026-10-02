"""
工具腳本選單：顯示所有工具腳本與簡述，輸入編號就執行對應腳本。
用法: python menu.py（不需要先啟動 venv，選單本身只用標準函式庫；
子腳本會自動優先用專案的 venv32 直譯器執行，找不到才退回目前這個 Python）

新增工具只要在下面 MENU 加一筆 dict 就好：
    title    選單上顯示的名稱
    desc     一行簡述
    script   相對於專案根目錄的腳本路徑
    args     固定帶的參數（選填）
    prompts  執行前要問使用者的參數（選填），格式 [(提示文字, 對應的參數前綴), ...]，
             前綴為 None 代表直接當成位置參數；留空白則略過該參數
    confirm  有副作用/需特別注意的說明（選填），有的話執行前會先要求輸入 y 確認
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(ROOT, "venv32", "Scripts", "python.exe")

MENU = [
    ("日常同步與部署", [
        {"title": "同步特約商店 + 福利公告", "desc": "Lotus 資料更新後的日常同步（Firestore + 公佈欄，一次跑完）",
         "script": "sync_all.py"},
        {"title": "部署特約查詢頁", "desc": "匯出 stores.json 並部署 index/join/qa.html 到網站伺服器",
         "script": "store/deploy_store.py",
         "confirm": "會把完整的 stores.json 公開上傳到伺服器，違反 LINE 驗證的存取控制；\n"
                    "    執行完必須立刻手動刪除遠端的 stores.json。"},
        {"title": "部署申請頁", "desc": "部署 apply.html、apply_status.html 到網站伺服器",
         "script": "store/deploy_apply.py"},
        {"title": "部署 LIFF 頁面", "desc": "部署 store/web/liff/ 底下所有頁面到網站伺服器",
         "script": "store/deploy_liff.py"},
        {"title": "部署福利公告", "desc": "匯出公告 JSON + 圖片並部署到網站伺服器",
         "script": "bulletin/deploy_bulletin.py"},
    ]),
    ("特約商店線上申請", [
        {"title": "審核待審申請", "desc": "逐筆審核 pending 的申請（核准/婉拒，含統編查證）",
         "script": "store/apply_review.py"},
        {"title": "處理店家已回傳用印檔", "desc": "檢查店家透過 LINE 回傳的用印檔案，確認後標記完成",
         "script": "store/apply_review.py", "args": ["--status", "merchant_signed"]},
        {"title": "瀏覽已核准申請", "desc": "純列出已核准、等待套版的申請，不會有任何變更",
         "script": "store/apply_review.py", "args": ["--status", "approved"]},
        {"title": "查詢申請編號與查詢碼", "desc": "店家忘了時，用店名/統編/電話搜尋，顯示申請編號與查詢碼",
         "script": "store/apply_review.py", "prompts": [("關鍵字（店名、統編、電話、負責人皆可）", "--find")]},
        {"title": "結案（放棄）指定申請", "desc": "把指定申請標記為 abandoned，不予受理",
         "script": "store/apply_review.py", "prompts": [("申請編號（例如 20260909-03）", "--abandon")],
         "confirm": "會把該申請標記為已結案。"},
        {"title": "產生合約 PDF", "desc": "把已核准申請套版產生 PDF，上傳伺服器並回寫下載網址",
         "script": "store/generate_contracts.py"},
        {"title": "預覽合約套版", "desc": "用範例資料套一次版並開啟 PDF，改範本後確認版面用",
         "script": "store/preview_contract.py"},
        {"title": "重新產生合約套版範本", "desc": "template-store.doc 改版後重跑，產出 templates/contract_template.doc",
         "script": "store/prepare_contract_template.py",
         "confirm": "會覆蓋 store/templates/contract_template.doc（手動改過的內容會遺失）。"},
    ]),
    ("查詢與維護", [
        {"title": "查詢特約商店", "desc": "互動式查詢，可依類別篩選並輸出 CSV",
         "script": "store/query_store.py"},
        {"title": "特約商店到期檢查", "desc": "列出已過期、60 天內到期的店家（只讀，需先關閉 Notes）",
         "script": "store/expiry_report.py"},
        {"title": "產生新增特約商店公告圖", "desc": "Notes 新增店家後，產生全院公告用的圖檔（store/output/，需先關閉 Notes）",
         "script": "store/make_announcement.py", "prompts": [("店名關鍵字", "--from-notes")]},
        {"title": "查詢打卡紀錄", "desc": "查詢指定日期區間的打卡紀錄",
         "script": "query_checkin.py"},
        {"title": "換新驗證碼", "desc": "換一組期效性驗證碼並印出，供張貼公佈欄",
         "script": "store/broadcast_code.py", "prompts": [("部門/情境名稱（例如 職工福利小組）", None)]},
        {"title": "覆核在職名單（試跑）", "desc": "匯入季度在職名單只產生報告（dry-run），不會真的撤銷",
         "script": "store/import_roster.py", "prompts": [("在職名單 CSV 路徑", None)]},
    ]),
    ("新聞稿", [
        {"title": "擷取新聞稿", "desc": "從 Lotus Notes 下載新聞稿（含圖片）",
         "script": "query_news.py"},
        {"title": "上傳新聞稿到 Joomla", "desc": "把尚未上傳的新聞稿建立成 Joomla 草稿文章",
         "script": "upload_joomla.py"},
    ]),
    ("打卡（會實際操作 Lotus Notes）", [
        {"title": "簽到", "desc": "在 Lotus Notes 打卡系統執行簽到",
         "script": "auto_checkin.py", "args": ["in"], "confirm": "會實際送出簽到。"},
        {"title": "簽退", "desc": "在 Lotus Notes 打卡系統執行簽退",
         "script": "auto_checkin.py", "args": ["out"], "confirm": "會實際送出簽退。"},
    ]),
]

ITEMS = [item for _, group in MENU for item in group]


def python_exe() -> str:
    return VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable


def show_menu():
    print("\n" + "=" * 60)
    print("  工具腳本選單")
    print("=" * 60)
    n = 0
    for group_name, group in MENU:
        print(f"\n【{group_name}】")
        for item in group:
            n += 1
            print(f"  {n:>2}. {item['title']}")
            print(f"      {item['desc']}")
    print("\n   0. 離開")


def build_command(item: dict):
    """回傳完整指令 list；使用者中途取消則回傳 None。"""
    if not os.path.exists(os.path.join(ROOT, item["script"])):
        print(f"找不到腳本：{item['script']}")
        return None

    if item.get("confirm"):
        print(f"\n注意：{item['confirm']}")
        if input("確定要執行嗎？(y/N) ").strip().lower() != "y":
            return None

    cmd = [python_exe(), item["script"], *item.get("args", [])]
    for label, prefix in item.get("prompts", []):
        value = input(f"{label}：").strip()
        if not value:
            print("未輸入，已取消。")
            return None
        cmd += [prefix, value] if prefix else [value]
    return cmd


def main():
    while True:
        show_menu()
        choice = input("\n請輸入編號：").strip()
        if choice == "":
            continue
        if choice in ("0", "q", "Q"):
            print("再見。")
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(ITEMS):
            print("編號不正確，請重新輸入。")
            continue

        item = ITEMS[int(choice) - 1]
        cmd = build_command(item)
        if cmd is None:
            continue

        print(f"\n▶ 執行：{item['title']}（{' '.join(cmd[1:])}）\n" + "-" * 60)
        try:
            result = subprocess.run(cmd, cwd=ROOT)
            print("-" * 60 + f"\n結束（exit code {result.returncode}）")
        except KeyboardInterrupt:
            print("\n已中斷。")
        input("\n按 Enter 回到選單…")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n再見。")
