"""
從 DXL 解析並儲存圖片
"""
import os, base64, re
from xml.etree import ElementTree as ET

DXL_FILE   = r"c:\Users\peter\Desktop\autoRPA2-lotusNotesAPI\output\test_images\export_doc.dxl"
OUTPUT_DIR = r"c:\Users\peter\Desktop\autoRPA2-lotusNotesAPI\output\test_images"

with open(DXL_FILE, "r", encoding="utf-8") as f:
    dxl = f.read()

print(f"DXL 長度: {len(dxl):,} 字元")

# 先看 DXL 有哪些 tag（不解析整棵樹，避免太慢）
print("\n=== DXL 中出現的 tag（取樣）===")
tags = set(re.findall(r'<([a-zA-Z][a-zA-Z0-9:]*)', dxl))
for t in sorted(tags):
    print(f"  <{t}>")

# 解析圖片
print("\n=== 擷取圖片 ===")
try:
    root = ET.fromstring(dxl)
    count = 0
    for tag, ext in [("gif", ".gif"), ("jpeg", ".jpg"), ("png", ".png")]:
        for node in root.iter(f"{{http://www.lotus.com/dxl}}{tag}"):
            data = node.text
            if data:
                path = os.path.join(OUTPUT_DIR, f"img_{count:03d}{ext}")
                with open(path, "wb") as f:
                    f.write(base64.b64decode(data.strip()))
                size = os.path.getsize(path)
                print(f"  ✓ img_{count:03d}{ext}  ({size:,} bytes)")
                count += 1
    print(f"\n共擷取 {count} 張圖片")
    if count == 0:
        # 顯示 DXL 片段供診斷
        idx = dxl.find("picture")
        if idx > 0:
            print(f"\n找到 'picture' 關鍵字，附近內容：\n{dxl[idx-50:idx+200]}")
except ET.ParseError as ex:
    print(f"XML 解析失敗: {ex}")
    # 用 regex 直接抓 base64 圖片資料
    print("\n改用 regex 搜尋...")
    for tag, ext in [("gif", ".gif"), ("jpeg", ".jpg"), ("png", ".png")]:
        matches = re.findall(rf'<{tag}[^>]*>([A-Za-z0-9+/=\s]+)</{tag}>', dxl)
        for i, data in enumerate(matches):
            path = os.path.join(OUTPUT_DIR, f"img_r{i:03d}{ext}")
            with open(path, "wb") as f:
                f.write(base64.b64decode(data.strip()))
            print(f"  ✓ img_r{i:03d}{ext}")
