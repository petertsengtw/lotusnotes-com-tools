"""
純邏輯模組：季度在職名單比對（sdd3.md §5.7）。

刻意不 import 任何 firebase/google 套件，方便單獨用 pytest 測試。
真正的 Firestore 讀寫在 main.py 裡的 admin_import_roster 完成，
這裡只負責「輸入名單 + 目前已驗證清單 → 算出誰該被撤銷」這件事。

姓名比對邏輯是暫定方案：sdd3.md §10 標記季度名單的真實欄位格式（Notes ID／工號／
純姓名）還沒確認，這裡先用「去除常見縣市地區前綴後比對姓名」當容錯規則，等名單格式
確認後要再調整（見 sdd3.md §5.7 待確認事項 2）。
"""
from __future__ import annotations

REGION_PREFIXES = (
    "花蓮", "臺北", "台北", "新北", "臺中", "台中", "臺南", "台南",
    "高雄", "桃園", "新竹", "苗栗", "彰化", "南投", "雲林", "嘉義",
    "屏東", "宜蘭", "臺東", "台東", "澎湖", "金門", "連江",
)

# 名單筆數若少於目前已驗證人數的這個比例，視為可能是誤傳/截斷檔案，預設拒絕匯入。
MIN_ROSTER_RATIO = 0.5


def normalize_name(raw: str) -> str:
    """去除頭尾空白與常見縣市地區前綴，供比對用。"""
    name = (raw or "").strip()
    for prefix in REGION_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.strip()


def validate_roster(roster: list) -> list:
    """檢查名單基本格式（sdd3.md §9 驗收標準：筆數、必要欄位）。回傳錯誤訊息清單，空清單代表通過。"""
    errors = []
    if not isinstance(roster, list) or len(roster) == 0:
        errors.append("名單是空的，拒絕匯入")
        return errors
    for i, row in enumerate(roster):
        if not isinstance(row, dict) or not (row.get("name") or "").strip():
            errors.append(f"第 {i + 1} 筆缺少姓名欄位")
    return errors


def compute_revocations(verified_users: list, roster: list, force: bool = False) -> dict:
    """
    verified_users: [{"lineUserId": str, "notesId": str}, ...]，目前 lineAuth.status == "verified" 的名單
    roster:         [{"name": str}, ...]，本次匯入的在職名單
    force:          略過「名單筆數過少」防呆檢查

    回傳:
      {
        "ok": bool,
        "blocked": bool, "reason": str | None,   # 被防呆擋下時 ok=False, blocked=True
        "toRevoke": [{"lineUserId": str, "notesId": str}, ...],
        "matched": [{"lineUserId": str, "notesId": str}, ...],
        "rosterCount": int, "verifiedCount": int,
      }
    """
    errors = validate_roster(roster)
    if errors:
        return {
            "ok": False, "blocked": True, "reason": "；".join(errors),
            "toRevoke": [], "matched": [],
            "rosterCount": len(roster) if isinstance(roster, list) else 0,
            "verifiedCount": len(verified_users),
        }

    verified_count = len(verified_users)
    roster_count = len(roster)
    if not force and verified_count > 0 and roster_count < verified_count * MIN_ROSTER_RATIO:
        return {
            "ok": False, "blocked": True,
            "reason": (
                f"新名單只有 {roster_count} 筆，少於目前已驗證人數 {verified_count} 筆的一半，"
                "可能是誤傳或截斷檔案，已擋下。若確認名單正確，請帶 force=true 再送一次。"
            ),
            "toRevoke": [], "matched": [],
            "rosterCount": roster_count, "verifiedCount": verified_count,
        }

    roster_names = {normalize_name(row["name"]) for row in roster}

    to_revoke, matched = [], []
    for user in verified_users:
        normalized = normalize_name(user.get("notesId", ""))
        (matched if normalized in roster_names else to_revoke).append(user)

    return {
        "ok": True, "blocked": False, "reason": None,
        "toRevoke": to_revoke, "matched": matched,
        "rosterCount": roster_count, "verifiedCount": verified_count,
    }
