import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import applications


def _valid_fields(**overrides):
    data = {
        "storeName": "阿美小吃",
        "ownerName": "王小明",
        "taxId": "12345678",
        "address": "花蓮市中華路1號",
        "phone": "03-1234567",
        "email": "test@example.com",
        "businessCategory": "餐飲",
        "discountContent": "消費滿百送飲料",
        "contractSource": applications.CONTRACT_SOURCE_HOSPITAL,
        "validityType": applications.VALIDITY_OPEN_ENDED,
        "consentPersonalData": True,
    }
    data.update(overrides)
    return data


def test_validate_application_fields_accepts_valid_data():
    assert applications.validate_application_fields(_valid_fields()) is None


def test_validate_application_fields_rejects_missing_required_field():
    data = _valid_fields()
    data["storeName"] = ""
    assert applications.validate_application_fields(data) == "missing_storeName"


def test_validate_application_fields_rejects_bad_tax_id():
    assert applications.validate_application_fields(_valid_fields(taxId="1234567")) == "invalid_tax_id"
    assert applications.validate_application_fields(_valid_fields(taxId="1234567a")) == "invalid_tax_id"


def test_validate_application_fields_rejects_bad_contract_source():
    assert applications.validate_application_fields(_valid_fields(contractSource="other")) == "invalid_contract_source"


TODAY = date(2026, 10, 14)


def test_validate_application_fields_requires_validity_type_for_hospital_template():
    assert applications.validate_application_fields(_valid_fields(validityType=None), TODAY) == "invalid_validity_type"
    assert applications.validate_application_fields(_valid_fields(validityType="forever"), TODAY) == "invalid_validity_type"


def test_validate_application_fields_until_date_needs_valid_future_date():
    until = _valid_fields(validityType=applications.VALIDITY_UNTIL_DATE)
    assert applications.validate_application_fields(until, TODAY) == "invalid_valid_until"
    assert applications.validate_application_fields({**until, "validUntil": "2027/10/13"}, TODAY) == "invalid_valid_until"
    assert applications.validate_application_fields({**until, "validUntil": "2027-02-30"}, TODAY) == "invalid_valid_until"
    assert applications.validate_application_fields({**until, "validUntil": "2026-10-14"}, TODAY) == "valid_until_not_future"
    assert applications.validate_application_fields({**until, "validUntil": "2027-10-13"}, TODAY) is None


def test_validate_application_fields_own_template_skips_validity():
    data = _valid_fields(contractSource=applications.CONTRACT_SOURCE_OWN, validityType=None)
    assert applications.validate_application_fields(data, TODAY) is None


def test_consent_period():
    open_ended = {"validityType": applications.VALIDITY_OPEN_ENDED}
    assert applications.consent_period(open_ended, TODAY) == ("2026-10-14", None)
    until = {"validityType": applications.VALIDITY_UNTIL_DATE, "validUntil": "2027-10-13"}
    assert applications.consent_period(until, TODAY) == ("2026-10-14", "2027-10-13")
    # 改同意書之前送出的申請沒有 validityType，當長期有效
    assert applications.consent_period({}, TODAY) == ("2026-10-14", None)


def test_validate_application_fields_requires_explicit_consent():
    assert applications.validate_application_fields(_valid_fields(consentPersonalData=False)) == "consent_required"
    assert applications.validate_application_fields(_valid_fields(consentPersonalData="true")) == "consent_required"


def test_validate_application_fields_rejects_overlong_field():
    assert applications.validate_application_fields(_valid_fields(storeName="a" * 201)) == "storeName_too_long"


def test_is_honeypot_triggered():
    assert applications.is_honeypot_triggered({applications.HONEYPOT_FIELD: "http://spam.example"}) is True
    assert applications.is_honeypot_triggered({applications.HONEYPOT_FIELD: "  "}) is False
    assert applications.is_honeypot_triggered({}) is False


def test_generate_query_code_length_and_alphabet():
    code = applications.generate_query_code()
    assert len(code) == applications.QUERY_CODE_LENGTH
    assert all(c in applications.QUERY_CODE_ALPHABET for c in code)


def test_check_query_code():
    application = {"queryCode": "ABCD1234"}
    assert applications.check_query_code(application, "ABCD1234") is True
    assert applications.check_query_code(application, "wrong") is False
    assert applications.check_query_code({}, "anything") is False


def test_validate_own_template_file():
    assert applications.validate_own_template_file("application/pdf", 1024) is None
    assert applications.validate_own_template_file("image/png", 1024) == "invalid_file_type"
    assert applications.validate_own_template_file("application/pdf", 0) == "file_too_large"
    assert applications.validate_own_template_file("application/pdf", applications.MAX_OWN_TEMPLATE_BYTES + 1) == "file_too_large"


def test_extension_for_content_type():
    assert applications.extension_for_content_type("application/pdf") == ".pdf"
    assert applications.extension_for_content_type("application/msword") == ".doc"
    assert applications.extension_for_content_type("image/jpeg") == ".jpg"
    assert applications.extension_for_content_type("unknown/type") == ""


def test_validate_merchant_signed_file():
    assert applications.validate_merchant_signed_file("application/pdf", 1024) is None
    assert applications.validate_merchant_signed_file("image/jpeg", 1024) is None
    assert applications.validate_merchant_signed_file("image/png", 1024) is None
    assert applications.validate_merchant_signed_file("application/msword", 1024) == "invalid_file_type"
    assert applications.validate_merchant_signed_file("application/pdf", 0) == "file_too_large"
    assert applications.validate_merchant_signed_file("application/pdf", applications.MAX_MERCHANT_FILE_BYTES + 1) == "file_too_large"


def test_can_upload_merchant_signed_only_when_contract_ready_or_already_signed():
    assert applications.can_upload_merchant_signed(applications.STATUS_CONTRACT_READY) is True
    assert applications.can_upload_merchant_signed(applications.STATUS_MERCHANT_SIGNED) is True
    for status in (
        applications.STATUS_PENDING,
        applications.STATUS_APPROVED,
        applications.STATUS_REJECTED,
        applications.STATUS_COMPLETED,
        applications.STATUS_ABANDONED,
        None,
        "",
    ):
        assert applications.can_upload_merchant_signed(status) is False


def test_file_signature_matches_real_headers():
    assert applications.file_signature_matches("application/pdf", b"%PDF-1.7\n...")
    assert applications.file_signature_matches("image/jpeg", b"\xff\xd8\xff\xe0\x00\x10JFIF")
    assert applications.file_signature_matches("image/png", b"\x89PNG\r\n\x1a\n\x00\x00")


def test_file_signature_rejects_spoofed_content_type():
    # 宣稱是 PDF，實際是別的東西（例如改副檔名的執行檔、純文字）
    assert not applications.file_signature_matches("application/pdf", b"MZ\x90\x00 fake exe")
    assert not applications.file_signature_matches("application/pdf", b"hello world")
    # 類型跟內容對不上
    assert not applications.file_signature_matches("image/png", b"%PDF-1.7")
    # 不在允許清單的類型一律不通過
    assert not applications.file_signature_matches("application/msword", b"\xd0\xcf\x11\xe0")
    assert not applications.file_signature_matches("application/pdf", b"")


def test_is_consent():
    hospital = applications.CONTRACT_SOURCE_HOSPITAL
    assert applications.is_consent({"contractSource": hospital, "status": "contract_ready", "documentType": "consent"})
    assert applications.is_consent({"contractSource": hospital, "status": "approved"})
    assert applications.is_consent({"contractSource": hospital, "status": "pending"})
    # 改制前已產生的合約
    assert not applications.is_consent({"contractSource": hospital, "status": "contract_ready"})
    assert not applications.is_consent({"contractSource": hospital, "status": "completed"})
    assert not applications.is_consent({"contractSource": applications.CONTRACT_SOURCE_OWN, "status": "contract_ready"})
