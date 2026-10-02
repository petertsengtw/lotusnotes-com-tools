"""
產生「特約商店新增」全院公告圖檔（PNG）。
用法:
    # Notes 新增店家後，直接用店名關鍵字從 Notes 讀資料（執行前要先關閉 Notes 用戶端）
    python make_announcement.py --from-notes 鴻道

    # 或手動指定（Notes 開著、或想改公告上的文字時）
    python make_announcement.py --name "煙牧大飯店有限公司" --subname "煙波花蓮太魯閣館" \
        --address "花蓮縣新城鄉順安村草林10之6號" --tel "03-8612000 #1454" --expire 2026-12-31

--from-notes 讀到的欄位也可以再用 --subname/--address/--tel/--offer/--expire 覆蓋。
優惠方案預設寫「詳見花蓮慈院特約商店平臺」（Notes 裡的優惠內容通常太長，放不進圖）。
輸出到 store/output/公告_店名_YYYYMMDD.png。
"""
import argparse
import os
from datetime import date, datetime

from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
FONT_BOLD = r"C:\Windows\Fonts\msjhbd.ttc"
FONT_REGULAR = r"C:\Windows\Fonts\msjh.ttc"
DEFAULT_OFFER = "詳見花蓮慈院特約商店平臺"
SIGNATURE = "職工福利行政小組 敬發"

W, H = 1450, 792
PINK = (247, 184, 192)
FRAME_BG = (200, 214, 240)
WHITE = (255, 255, 255)
BLACK = (25, 25, 25)
TITLE_BLUE = (20, 20, 230)
NAVY = (30, 40, 90)
TEAL = (72, 190, 175)
SIGN_TEAL = (60, 120, 150)
YELLOW = (255, 245, 0)
RING_BLUE = (30, 140, 200)
RING_WHITE = (235, 245, 250)
LEAF = (60, 175, 160)


def font(path, size):
    return ImageFont.truetype(path, size)


def fit_font(draw, text, path, size, max_width, min_size=20):
    """字太長就縮小字級，直到放得進 max_width。"""
    while size > min_size:
        f = font(path, size)
        if draw.textlength(text, font=f) <= max_width:
            return f
        size -= 2
    return font(path, min_size)


def roc_expire(iso_date: str) -> str:
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}止"


def draw_ring(draw, cx, cy, r):
    """救生圈圖示：藍白相間的外環 + 粉紅內圓。"""
    box = (cx - r, cy - r, cx + r, cy + r)
    draw.ellipse((cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6), fill=WHITE)
    for i in range(8):
        draw.pieslice(box, i * 45 + 22.5, i * 45 + 67.5, fill=RING_BLUE if i % 2 == 0 else RING_WHITE)
    inner = r * 0.55
    draw.ellipse((cx - inner - 5, cy - inner - 5, cx + inner + 5, cy + inner + 5), fill=WHITE)
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=PINK)


def draw_frond(draw, x0, y0, x1, y1, leaflet=70, count=9):
    """棕櫚葉（裝飾用）：從 (x0,y0) 到 (x1,y1) 的葉柄，兩側長出越往尖端越短的細長葉片。"""
    import math
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length          # 沿葉柄方向
    px, py = -uy, ux                           # 垂直葉柄方向
    for i in range(1, count + 1):
        t = i / (count + 1)
        bx, by = x0 + dx * t, y0 + dy * t
        size = leaflet * (1.15 - t * 0.7)
        for side in (1, -1):
            tip = (bx + (px * side * 0.9 + ux * 0.45) * size, by + (py * side * 0.9 + uy * 0.45) * size)
            base_a = (bx - ux * size * 0.12, by - uy * size * 0.12)
            base_b = (bx + ux * size * 0.12, by + uy * size * 0.12)
            draw.polygon([base_a, tip, base_b], fill=LEAF)
    draw.line([(x0, y0), (x1, y1)], fill=(40, 140, 125), width=6)


def wrap_text(draw, text, path, size, max_width, max_lines=2, min_size=24):
    """先縮小字級（到 28）試著排成一行，還放不下才換行（最多 max_lines 行）、再繼續縮小。
    回傳 (font, lines)。"""
    one_line = fit_font(draw, text, path, size, max_width, min_size=28)
    if draw.textlength(text, font=one_line) <= max_width:
        return one_line, [text]
    while True:
        f = font(path, size)
        lines, cur = [], ""
        for ch in text:
            if draw.textlength(cur + ch, font=f) <= max_width:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
        if len(lines) <= max_lines or size <= min_size:
            return f, lines[:max_lines]
        size -= 2


def draw_card(img, x, y, w, h, label, value):
    """白色圓角卡片：左側救生圈圖示，右側標籤 + 內容（內容太長會自動換行）。"""
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x + 6, y + 8, x + w + 6, y + h + 8), 28, fill=(190, 110, 130, 90))
    img.alpha_composite(shadow)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((x, y, x + w, y + h), 28, fill=(255, 255, 255, 240))
    draw_ring(d, x + 62, y + h // 2, 38)
    tx = x + 120
    d.text((tx, y + 22), label, font=font(FONT_BOLD, 40), fill=TEAL)
    vf, lines = wrap_text(d, value, FONT_REGULAR, 34, w - 140)
    line_h = vf.size + 8
    vy = y + 80 if len(lines) == 1 else y + 72
    for i, line in enumerate(lines):
        d.text((tx, vy + i * line_h), line, font=vf, fill=BLACK)


def draw_star(draw, cx, cy, r_out, r_in, points, fill):
    import math
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.pi * i / points - math.pi / 2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    draw.polygon(pts, fill=fill)


def render(name, subname, address, tel, offer, expire_text, out_path):
    import random
    rnd = random.Random(name)  # 同一家店每次產生的裝飾位置都一樣

    # 背景：上粉紅、下蜜桃的直向漸層
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    top, bottom = (250, 196, 206), (255, 222, 200)
    for yy in range(H):
        t = yy / H
        d.line([(0, yy), (W, yy)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))

    # 彩色圓點（避開中間主要內容區）
    colors = [(255, 255, 255), (120, 200, 230), (255, 240, 120), (120, 210, 190)]
    for _ in range(60):
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        if 120 < x < W - 120 and 60 < y < H - 60:
            continue
        r = rnd.randint(4, 11)
        d.ellipse((x - r, y - r, x + r, y + r), fill=rnd.choice(colors))

    # 角落棕櫚葉
    draw_frond(d, W + 10, -10, W - 170, 300)
    draw_frond(d, -10, H + 10, 150, 470, leaflet=65, count=8)

    # 白色外框
    d.rounded_rectangle((18, 18, W - 18, H - 18), 36, outline=WHITE, width=8)

    # 標題：「特約商店」+「新增」，白色描邊
    tf = font(FONT_BOLD, 96)
    t1, t2 = "特約商店", "新增"
    w1, w2 = d.textlength(t1, font=tf), d.textlength(t2, font=tf)
    tx = (W - w1 - w2) / 2
    d.text((tx, 28), t1, font=tf, fill=BLACK, stroke_width=6, stroke_fill=WHITE)
    d.text((tx + w1, 28), t2, font=tf, fill=TITLE_BLUE, stroke_width=6, stroke_fill=WHITE)

    # NEW! 星形徽章
    bx, by = tx + w1 + w2 + 85, 90
    draw_star(d, bx, by, 70, 52, 14, (255, 90, 90))
    nf_ = font(FONT_BOLD, 36)
    d.text((bx - d.textlength("NEW!", font=nf_) / 2, by - 24), "NEW!", font=nf_, fill=WHITE)

    # 「好康快報!」對話框（左上）
    d.rounded_rectangle((80, 52, 300, 132), 40, fill=WHITE, outline=NAVY, width=4)
    d.polygon([(232, 128), (262, 152), (255, 128)], fill=WHITE)
    d.line([(232, 130), (262, 152), (255, 130)], fill=NAVY, width=4)
    bf = font(FONT_BOLD, 36)
    d.text((190 - d.textlength("好康快報!", font=bf) / 2, 68), "好康快報!", font=bf, fill=(230, 70, 90))

    # 店名：黃色螢光筆底 + 描邊
    nf = fit_font(d, name, FONT_BOLD, 62, W - 360)
    nw = d.textlength(name, font=nf)
    ny = 158
    d.rounded_rectangle(((W - nw) / 2 - 30, ny + nf.size * 0.55, (W + nw) / 2 + 30, ny + nf.size + 14), 10, fill=YELLOW)
    d.text(((W - nw) / 2, ny), name, font=nf, fill=NAVY, stroke_width=3, stroke_fill=WHITE)
    if subname:
        sub = f"（{subname}）"
        sf = fit_font(d, sub, FONT_BOLD, 40, W - 500)
        d.text(((W - d.textlength(sub, font=sf)) / 2, ny + nf.size + 22), sub, font=sf, fill=NAVY)

    # 四張資訊卡片（2×2）
    card_w, card_h, gap = 600, 165, 40
    left = (W - card_w * 2 - gap) // 2
    top_y = 330 if subname else 300
    draw_card(img, left, top_y, card_w, card_h, "店址", address)
    draw_card(img, left + card_w + gap, top_y, card_w, card_h, "電話", tel)
    draw_card(img, left, top_y + card_h + 30, card_w, card_h, "優惠方案", offer)
    draw_card(img, left + card_w + gap, top_y + card_h + 30, card_w, card_h, "優惠期限", expire_text)

    # 右下署名
    d = ImageDraw.Draw(img)
    gf = font(FONT_BOLD, 38)
    d.text((W - 60 - d.textlength(SIGNATURE, font=gf), H - 82), SIGNATURE, font=gf, fill=SIGN_TEAL,
           stroke_width=3, stroke_fill=WHITE)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.convert("RGB").save(out_path)


def find_in_notes(keyword: str) -> dict:
    from notes_store import fetch_active_stores
    matches = [s for s in fetch_active_stores() if keyword in s["name"]]
    if not matches:
        raise SystemExit(f"Notes 有效特約商店裡找不到名稱含「{keyword}」的店家（已作廢或已過期的不會列出）")
    if len(matches) > 1:
        names = "、".join(s["name"] for s in matches)
        raise SystemExit(f"符合「{keyword}」的店家不只一家：{names}，請把關鍵字打得更完整")
    return matches[0]


def main():
    p = argparse.ArgumentParser(description="產生「特約商店新增」全院公告圖檔")
    p.add_argument("--from-notes", metavar="店名關鍵字", help="從 Notes 特約商店資料庫讀取（需先關閉 Notes 用戶端）")
    p.add_argument("--name")
    p.add_argument("--subname", default="", help="店名下方括號內的分館/品牌名（選填）")
    p.add_argument("--address")
    p.add_argument("--tel")
    p.add_argument("--offer", help=f"優惠方案文字（預設：{DEFAULT_OFFER}）")
    p.add_argument("--expire", help="優惠期限，YYYY-MM-DD（會轉成民國年）")
    p.add_argument("--out", help="輸出檔案路徑（預設 store/output/公告_店名_今天日期.png）")
    args = p.parse_args()

    data = {}
    if args.from_notes:
        s = find_in_notes(args.from_notes)
        data = {"name": s["name"], "address": s["address"], "tel": s["tel"], "expire": s["expire"]}
    for key in ("name", "address", "tel", "expire"):
        if getattr(args, key):
            data[key] = getattr(args, key)
    missing = [k for k in ("name", "address", "tel", "expire") if not data.get(k)]
    if missing:
        raise SystemExit(f"缺少欄位：{', '.join(missing)}（用 --from-notes 或手動指定）")

    out = args.out or os.path.join(OUTPUT_DIR, f"公告_{data['name']}_{date.today():%Y%m%d}.png")
    render(data["name"], args.subname, data["address"], data["tel"],
           args.offer or DEFAULT_OFFER, roc_expire(data["expire"]), out)
    print(f"已產生：{out}")
    print(f"  店名：{data['name']}{'（' + args.subname + '）' if args.subname else ''}")
    print(f"  店址：{data['address']}　電話：{data['tel']}　期限：{roc_expire(data['expire'])}")


if __name__ == "__main__":
    main()
