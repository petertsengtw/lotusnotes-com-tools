import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from admin_auth import check_secret, is_authorized


def test_check_secret_matches():
    assert check_secret("s3cret", "s3cret") is True


def test_check_secret_mismatch():
    assert check_secret("s3cret", "wrong") is False


def test_check_secret_empty_expected_always_fails():
    # 伺服器端沒設定密鑰時，不能讓「空字串比空字串」意外放行。
    assert check_secret("", "") is False
    assert check_secret("", "anything") is False


def test_check_secret_none_got():
    assert check_secret("s3cret", None) is False


class _FakeHeaders(dict):
    pass


def test_is_authorized_reads_header_and_env(monkeypatch):
    monkeypatch.setenv("ADMIN_SHARED_SECRET", "topsecret")
    assert is_authorized(_FakeHeaders({"X-Admin-Secret": "topsecret"})) is True
    assert is_authorized(_FakeHeaders({"X-Admin-Secret": "nope"})) is False
    assert is_authorized(_FakeHeaders({})) is False
