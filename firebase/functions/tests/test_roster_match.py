import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from roster_match import compute_revocations, normalize_name, validate_roster


def test_normalize_name_strips_region_prefix():
    assert normalize_name("花蓮陳麗玉") == "陳麗玉"
    assert normalize_name("臺北王小明") == "王小明"


def test_normalize_name_no_prefix_unchanged():
    assert normalize_name("陳麗玉") == "陳麗玉"


def test_normalize_name_strips_whitespace():
    assert normalize_name("  花蓮陳麗玉  ") == "陳麗玉"


def test_normalize_name_empty():
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


def test_validate_roster_rejects_empty():
    assert validate_roster([]) != []
    assert validate_roster(None) != []


def test_validate_roster_rejects_missing_name():
    errors = validate_roster([{"name": "陳麗玉"}, {"name": ""}, {}])
    assert len(errors) == 2


def test_validate_roster_passes_good_data():
    assert validate_roster([{"name": "花蓮陳麗玉"}, {"name": "王小明"}]) == []


def test_compute_revocations_matches_with_normalization():
    verified = [
        {"lineUserId": "U1", "notesId": "花蓮陳麗玉"},
        {"lineUserId": "U2", "notesId": "王小明"},
    ]
    roster = [{"name": "陳麗玉"}, {"name": "王小明"}]
    result = compute_revocations(verified, roster)
    assert result["ok"] is True
    assert result["toRevoke"] == []
    assert len(result["matched"]) == 2


def test_compute_revocations_flags_unmatched_for_revoke():
    verified = [
        {"lineUserId": "U1", "notesId": "花蓮陳麗玉"},
        {"lineUserId": "U2", "notesId": "已離職張三"},
    ]
    roster = [{"name": "陳麗玉"}]
    result = compute_revocations(verified, roster)
    assert result["ok"] is True
    assert [u["lineUserId"] for u in result["toRevoke"]] == ["U2"]
    assert [u["lineUserId"] for u in result["matched"]] == ["U1"]


def test_compute_revocations_blocks_on_empty_roster():
    verified = [{"lineUserId": "U1", "notesId": "陳麗玉"}]
    result = compute_revocations(verified, [])
    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["toRevoke"] == []


def test_compute_revocations_blocks_on_suspiciously_small_roster():
    verified = [{"lineUserId": f"U{i}", "notesId": f"人{i}"} for i in range(10)]
    roster = [{"name": "人0"}, {"name": "人1"}]  # 只有 2 筆，遠少於 10 筆已驗證人數的一半
    result = compute_revocations(verified, roster)
    assert result["ok"] is False
    assert result["blocked"] is True
    assert "force" in result["reason"]


def test_compute_revocations_force_bypasses_small_roster_guard():
    verified = [{"lineUserId": f"U{i}", "notesId": f"人{i}"} for i in range(10)]
    roster = [{"name": "人0"}, {"name": "人1"}]
    result = compute_revocations(verified, roster, force=True)
    assert result["ok"] is True
    assert result["blocked"] is False
    assert len(result["toRevoke"]) == 8


def test_compute_revocations_no_guard_when_nobody_verified_yet():
    result = compute_revocations([], [{"name": "陳麗玉"}])
    assert result["ok"] is True
    assert result["toRevoke"] == []
    assert result["matched"] == []
