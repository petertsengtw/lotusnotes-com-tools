import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from line_auth import LINE_ISSUER, LineVerifyError, verify_line_id_token


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_missing_token_raises(monkeypatch):
    monkeypatch.setenv("LINE_LOGIN_CHANNEL_ID", "chan123")
    with pytest.raises(LineVerifyError):
        verify_line_id_token("")


def test_missing_channel_id_raises(monkeypatch):
    monkeypatch.delenv("LINE_LOGIN_CHANNEL_ID", raising=False)
    with pytest.raises(LineVerifyError):
        verify_line_id_token("some-token")


def test_success_returns_claims(monkeypatch):
    monkeypatch.setenv("LINE_LOGIN_CHANNEL_ID", "chan123")

    def fake_post(url, data, timeout):
        assert data["client_id"] == "chan123"
        return _FakeResponse(200, {"iss": LINE_ISSUER, "aud": "chan123", "sub": "U123", "exp": 9999999999})

    monkeypatch.setattr("line_auth.requests.post", fake_post)
    claims = verify_line_id_token("valid-token")
    assert claims["sub"] == "U123"


def test_non_200_raises(monkeypatch):
    monkeypatch.setenv("LINE_LOGIN_CHANNEL_ID", "chan123")
    monkeypatch.setattr("line_auth.requests.post", lambda url, data, timeout: _FakeResponse(400, {"error": "invalid_request"}))
    with pytest.raises(LineVerifyError):
        verify_line_id_token("bad-token")


def test_audience_mismatch_raises(monkeypatch):
    monkeypatch.setenv("LINE_LOGIN_CHANNEL_ID", "chan123")
    monkeypatch.setattr(
        "line_auth.requests.post",
        lambda url, data, timeout: _FakeResponse(200, {"iss": LINE_ISSUER, "aud": "OTHER_CHANNEL", "sub": "U123"}),
    )
    with pytest.raises(LineVerifyError):
        verify_line_id_token("token-for-another-app")


def test_stub_mode_bypasses_real_call(monkeypatch):
    monkeypatch.setenv("LINE_AUTH_STUB", "1")
    monkeypatch.delenv("LINE_LOGIN_CHANNEL_ID", raising=False)
    claims = verify_line_id_token("fake-token-abc")
    assert claims["sub"] == "stub-fake-token-abc"
    monkeypatch.delenv("LINE_AUTH_STUB", raising=False)


def test_missing_sub_raises(monkeypatch):
    monkeypatch.setenv("LINE_LOGIN_CHANNEL_ID", "chan123")
    monkeypatch.setattr(
        "line_auth.requests.post",
        lambda url, data, timeout: _FakeResponse(200, {"iss": LINE_ISSUER, "aud": "chan123"}),
    )
    with pytest.raises(LineVerifyError):
        verify_line_id_token("weird-token")
