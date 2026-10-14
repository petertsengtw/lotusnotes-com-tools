"""
一次性範本準備（sdd5.md §4.5.1）：把 store/template-consent.docx（特約商店同意書
原稿）裡的空白欄位換成 {{...}} 佔位符，另存成 store/templates/consent_template.docx，
供 generate_contracts.py 套版使用。

同意書是 .docx，直接改 word/document.xml 的文字即可，不需要開 Word（舊版合約書是
.doc，才需要用 Word COM 鎖定段落做 Find/Replace）。每一處替換都要求「原文剛好出現
一次」，找不到或出現多次就直接中止並說明，不會默默改錯地方。

替換對照（對照 2026-10-02 草稿版，用 python 讀出 document.xml 核對過）：
    前言「本公司（機構、商號）＿＿…＿，」  → 店名（加底線，維持填空的樣子）
    一、優惠 三行底線空白                   → 第一行換成優惠內容，其餘兩行刪除
    三、適用期間 兩個「□」                  → {{box_open}}／{{box_until}}，套版時勾選其一
    三、「至中華民國＿＿＿年＿＿＿月＿＿＿日止」→ 到期日（長期有效時套回底線）
    三、「※ 建議勾選第一項…」提示          → 刪除（已在 apply.html 讓店家選好，印出來的同意書不需要）
    立同意書人表格 商店名稱／統一編號／代表人／地址／電話／聯絡人／電子郵件 → 對應欄位
    文末「中華民國　年　月　日」           → 同意日期
    頁首「草稿（送法務室審閱用，非正式版本）」→ 刪除

**只需要執行一次**（`python prepare_consent_template.py`），`template-consent.docx`
改版（例如法務定稿）後再重跑；文字有變動導致對不到時會中止並印出對不到的原文，
照新版內容調整下面的對照即可。
"""
import os
import re
import zipfile

BASE_DIR = os.path.dirname(__file__)
SOURCE_PATH = os.path.join(BASE_DIR, "template-consent.docx")
OUTPUT_DIR = os.path.join(BASE_DIR, "templates")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "consent_template.docx")

# 原稿內文 run 的格式（新細明體/標楷體由樣式決定，這裡只有 eastAsia hint）。
_RUN_PROPS = '<w:rPr><w:rFonts w:hint="eastAsia"/></w:rPr>'
_RUN_PROPS_UNDERLINE = '<w:rPr><w:rFonts w:hint="eastAsia"/><w:u w:val="single"/></w:rPr>'

BLANK_17 = "＿" * 17
BLANK_29 = "＿" * 29
BLANK_3 = "＿" * 3


def _replace_once(xml: str, target: str, replacement: str) -> str:
    count = xml.count(target)
    if count != 1:
        raise SystemExit(
            f"範本裡 {target!r} 出現 {count} 次（預期剛好 1 次），template-consent.docx 可能已改版，"
            f"請對照新版內容調整 prepare_consent_template.py 的替換對照。"
        )
    return xml.replace(target, replacement)


def _remove_paragraphs_containing(xml: str, text: str, expected: int = 1) -> str:
    """刪除包含 text 的整個段落（<w:p>…</w:p>）。段落之間沒有巢狀，用非貪婪比對即可；
    限定符合的段落數必須剛好是 expected，避免誤刪。"""
    matches = [m for m in re.finditer(r"<w:p[ >].*?</w:p>", xml, re.S) if text in m.group(0)]
    if len(matches) != expected:
        raise SystemExit(f"找到 {len(matches)} 個包含 {text!r} 的段落（預期 {expected} 個），範本可能已改版。")
    for m in reversed(matches):
        xml = xml[:m.start()] + xml[m.end():]
    return xml


def build_document_xml(xml: str) -> str:
    # 前言店名：把底線空白拆成獨立一個加底線的 run，套版後店名底下有底線，像是填好的空格。
    xml = _replace_once(
        xml,
        f"本公司（機構、商號）{BLANK_17}，",
        f"本公司（機構、商號）</w:t></w:r><w:r>{_RUN_PROPS_UNDERLINE}"
        f'<w:t xml:space="preserve">　{{{{store_name}}}}　</w:t></w:r><w:r>{_RUN_PROPS}<w:t>，',
    )

    # 優惠內容：三行底線空白，第一行換成佔位符，其餘兩行刪掉（優惠內容本身會用段落內
    # 換行逐行呈現，見 generate_contracts.replace_all）。
    if xml.count(f"<w:t>{BLANK_29}</w:t>") != 3:
        raise SystemExit("優惠內容的三行底線空白對不到，範本可能已改版。")
    xml = xml.replace(f"<w:t>{BLANK_29}</w:t>", "<w:t>{{discount_content}}</w:t>", 1)
    xml = _remove_paragraphs_containing(xml, f"<w:t>{BLANK_29}</w:t>", expected=2)

    xml = _replace_once(xml, "□ 優惠方案自同意日起適用", "{{box_open}} 優惠方案自同意日起適用")
    xml = _replace_once(
        xml,
        f"□ 優惠方案自同意日起至中華民國{BLANK_3}年{BLANK_3}月{BLANK_3}日止。",
        "{{box_until}} 優惠方案自同意日起至中華民國{{until_y}}年{{until_m}}月{{until_d}}日止。",
    )
    xml = _remove_paragraphs_containing(xml, "※ 建議勾選第一項")

    for label, field in (
        ("商店名稱：", "store_name"),
        ("統一編號：", "tax_id"),
        ("代 表 人：", "owner_name"),
        ("地　　址：", "address"),
        ("電　　話：", "phone"),
        ("聯 絡 人：", "contact_person"),
        ("電子郵件：", "email"),
    ):
        xml = _replace_once(xml, f"<w:t>{label}</w:t>", f"<w:t>{label}{{{{{field}}}}}</w:t>")

    xml = _replace_once(
        xml,
        "中　華　民　國　　　　　年　　　　　月　　　　　日",
        "中　華　民　國　　{{sign_y}}　　年　　{{sign_m}}　　月　　{{sign_d}}　　日",
    )
    return xml


def strip_draft_header(xml: str) -> str:
    return re.sub(r"<w:t>[^<]*草稿[^<]*</w:t>", "<w:t></w:t>", xml)


def main():
    if not os.path.exists(SOURCE_PATH):
        raise SystemExit(f"找不到 {SOURCE_PATH}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with zipfile.ZipFile(SOURCE_PATH) as src, zipfile.ZipFile(OUTPUT_PATH, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/document.xml":
                data = build_document_xml(data.decode("utf-8")).encode("utf-8")
            elif re.fullmatch(r"word/header\d+\.xml", item.filename):
                text = data.decode("utf-8")
                if "草稿" in text:
                    print(f"已移除頁首的草稿標示（{item.filename}）")
                    data = strip_draft_header(text).encode("utf-8")
            dst.writestr(item, data)

    print(f"已產生範本：{OUTPUT_PATH}")


if __name__ == "__main__":
    main()
