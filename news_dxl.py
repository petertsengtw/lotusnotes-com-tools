"""
新聞稿 DXL 解析：依 Notes 文件原本的順序取出段落文字與內嵌圖片
- 圖片依文件中出現的順序存成 img_000.jpg、img_001.jpg…
- layout.json 記錄段落與圖片的先後順序，upload_joomla.py 用它把圖片放回原位、圖說接在圖片下方
被 query_news.py 匯入使用
"""
import os, json, base64
from xml.etree import ElementTree as ET

DXL_NS   = "{http://www.lotus.com/dxl}"
IMG_EXTS = {"jpeg": ".jpg", "gif": ".gif", "png": ".png"}


def _tag(el):
    return el.tag.replace(DXL_NS, "")


def extract_body(dxl, doc_dir):
    """解析 DXL 的 Body 欄位，把圖片寫進 doc_dir、段落順序寫進 layout.json，回傳圖片張數

    layout.json 是 block 清單，每個 <par> 一筆：
      {"type": "text",   "text": "第一行\\n第二行"}   # <break/> 轉成 \\n，空段落 text 為 ""
      {"type": "images", "files": ["img_000.jpg", ...]}
    """
    root   = ET.fromstring(dxl)
    body   = next((it for it in root.iter(f"{DXL_NS}item") if it.get("name") == "Body"), None)
    blocks = []
    count  = 0

    def save_image(pic):
        nonlocal count
        for child in pic:
            ext = IMG_EXTS.get(_tag(child))
            if ext and child.text:
                name = f"img_{count:03d}{ext}"
                with open(os.path.join(doc_dir, name), "wb") as f:
                    f.write(base64.b64decode(child.text.strip()))
                count += 1
                return name
        return None   # 連結圖、Notes bitmap 等非內嵌格式略過

    def walk_par(par):
        texts, files = [], []

        def visit(el):
            t = _tag(el)
            if t == "picture":
                name = save_image(el)
                if name:
                    files.append(name)
            elif t == "break":
                texts.append("\n")
            elif t not in ("font", "pardef"):
                if el.text:
                    texts.append(el.text)
                for child in el:
                    visit(child)
            if el is not par and el.tail:
                texts.append(el.tail)

        visit(par)
        if files:
            blocks.append({"type": "images", "files": files})
        text = "".join(texts).strip("\n")
        if text.strip() or not files:
            blocks.append({"type": "text", "text": text})

    def walk(el):
        for child in el:
            if _tag(child) == "par":
                walk_par(child)
            else:
                walk(child)          # table / tablerow / tablecell / section…

    if body is not None:
        walk(body)
    with open(os.path.join(doc_dir, "layout.json"), "w", encoding="utf-8") as f:
        json.dump(blocks, f, ensure_ascii=False, indent=1)
    return count
