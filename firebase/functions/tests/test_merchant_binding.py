import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merchant_binding import looks_like_binding_attempt, parse_bind_text


def test_parse_bind_text_normal():
    assert parse_bind_text("20260909-03 AB12CD34") == ("20260909-03", "AB12CD34")


def test_parse_bind_text_extra_whitespace():
    assert parse_bind_text("  20260909-03   AB12CD34  ") == ("20260909-03", "AB12CD34")


def test_parse_bind_text_fullwidth_space():
    # LINE 手機輸入法有時候會打出全形空白，Python str.split() 預設就能處理。
    assert parse_bind_text("20260909-03　AB12CD34") == ("20260909-03", "AB12CD34")


def test_parse_bind_text_missing_parts():
    assert parse_bind_text("20260909-03") is None
    assert parse_bind_text("") is None


def test_parse_bind_text_too_many_parts():
    assert parse_bind_text("20260909-03 AB12CD34 extra") is None


def test_looks_like_binding_attempt_normal():
    assert looks_like_binding_attempt("20260909-03 AB12CD34") is True


def test_looks_like_binding_attempt_id_only():
    assert looks_like_binding_attempt("20260909-03") is True


def test_looks_like_binding_attempt_embedded_in_sentence():
    assert looks_like_binding_attempt("我的申請編號是20260909-03，查詢碼AB12CD34") is True


def test_looks_like_binding_attempt_unrelated_chat():
    assert looks_like_binding_attempt("你好") is False
    assert looks_like_binding_attempt("請問特約商店清單在哪裡查") is False
    assert looks_like_binding_attempt("") is False


def test_looks_like_binding_attempt_plain_numbers_not_enough():
    # 沒有「8碼-數字」的樣子（例如純粹一串數字、或格式不完整），不算像申請編號
    assert looks_like_binding_attempt("20260909") is False
    assert looks_like_binding_attempt("1234") is False
