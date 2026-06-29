import io
import math
import os
import textwrap

import matplotlib
matplotlib.use("Agg")
_MPL_FONT_DIR = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
_LOCAL_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")

from PIL import Image, ImageDraw, ImageFont

CW, CH = 320, 500

BG      = (11,  6,  6)
GOLD    = (200, 168, 75)
GOLD_D  = (154, 122, 53)
GOLD_DK = ( 90,  58, 16)
CREAM   = (224, 224, 224)
AV_BG   = ( 42,  18, 18)
RED     = (180,  20, 20)

FACTION_COLOR = {
    "reds":        (160,  20,  20),
    "capitalists": ( 20,  70, 150),
    "conquerors":  (110,  70,  15),
    "strongmen":   ( 70,  20,  80),
    "philosophers":( 15,  90,  80),
    "wildcards":   ( 80,  80,  15),
}

FACTION_LABEL = {
    "reds":        "THE REDS",
    "capitalists": "THE CAPITALISTS",
    "conquerors":  "THE CONQUERORS",
    "strongmen":   "THE STRONGMEN",
    "philosophers":"PHILOSOPHERS",
    "wildcards":   "WILDCARDS",
}

RARITY_STARS = {
    "common":    1,
    "uncommon":  2,
    "rare":      3,
    "epic":      4,
    "legendary": 5,
}

STAT_COLOR = {
    "authority": (200,  50,  50),
    "military":  ( 50, 150, 200),
    "charisma":  (200, 168,  75),
}


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    if name == "cjk":
        paths = [
            os.path.join(_LOCAL_FONT_DIR, "NotoSansSC-Regular.otf"),
            "C:/Windows/Fonts/msyh.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]
    elif name == "bold":
        paths = [
            os.path.join(_MPL_FONT_DIR, "DejaVuSansMono-Bold.ttf"),
            "C:/Windows/Fonts/consolab.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        ]
    else:
        paths = [
            os.path.join(_MPL_FONT_DIR, "DejaVuSansMono.ttf"),
            "C:/Windows/Fonts/consola.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _bb(draw, text, font):
    return draw.textbbox((0, 0), text, font=font)


def _cx(draw, text, font, cx, y):
    b = _bb(draw, text, font)
    draw.text((cx - (b[2] - b[0]) // 2, y), text, fill=None)


def _draw_centered(draw, text, font, cx, y, color):
    b = _bb(draw, text, font)
    draw.text((cx - (b[2] - b[0]) // 2, y), text, fill=color, font=font)


def _draw_right(draw, text, font, rx, y, color):
    b = _bb(draw, text, font)
    draw.text((rx - (b[2] - b[0]), y), text, fill=color, font=font)


def _dashed_ring(draw, cx, cy, r, color, n=24):
    step = 2 * math.pi / n
    for i in range(n):
        if i % 2 == 0:
            a0 = i * step - math.pi / 2
            a1 = a0 + step * 0.7
            pts = [(cx + r * math.cos(a0 + (a1 - a0) * t / 11),
                    cy + r * math.sin(a0 + (a1 - a0) * t / 11)) for t in range(12)]
            draw.line(pts, fill=color, width=2)


def _paste_circle(card, img_bytes, cx, cy, r):
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top  = max(0, (h - side) // 4)
        img = img.crop((left, top, left + side, top + side))
        d = r * 2
        img = img.resize((d, d), Image.LANCZOS)
        mask = Image.new("L", (d, d), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
        card.paste(img, (cx - r, cy - r), mask)
    except Exception:
        pass


def _stat_bar(draw, x, y, w, h, value, color, label, font_sm):
    draw.rectangle([x, y, x + w, y + h], fill=(30, 15, 15))
    fill_w = int(w * min(value, 100) / 100)
    if fill_w > 0:
        draw.rectangle([x, y, x + fill_w, y + h], fill=color)
    draw.rectangle([x, y, x + w, y + h], outline=(*GOLD, 60), width=1)
    draw.text((x + w + 6, y - 1), f"{value}", fill=CREAM, font=font_sm)
    draw.text((x - _bb(draw, label, font_sm)[2] - 6, y - 1), label, fill=GOLD_D, font=font_sm)


def render_personality_card(
    *,
    name: str,
    title: str,
    faction: str,
    rarity: str,
    quote: str,
    stats: dict,
    img_bytes: bytes | None,
) -> bytes:
    cx = CW // 2

    card = Image.new("RGB", (CW, CH), BG)

    tex = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    tex_draw = ImageDraw.Draw(tex)
    f_star_tex = _font("mono", 12)
    star_c = (*GOLD, 18)
    for row in range(0, CH, 38):
        for col in range(0, CW, 38):
            tex_draw.text((col + 4,  row + 4),  "★", fill=star_c, font=f_star_tex)
            tex_draw.text((col + 22, row + 22), "★", fill=star_c, font=f_star_tex)
    card = Image.alpha_composite(card.convert("RGBA"), tex).convert("RGB")
    draw = ImageDraw.Draw(card)

    # outer + inner border
    draw.rectangle([5, 5, CW - 5, CH - 5], outline=GOLD, width=3)
    draw.rectangle([10, 10, CW - 10, CH - 10], outline=(*GOLD, 80), width=1)

    # faction header bar
    fc = FACTION_COLOR.get(faction, RED)
    draw.rectangle([5, 5, CW - 5, 42], fill=fc)
    draw.rectangle([5, 5, CW - 5, 42], outline=GOLD, width=3)

    f_mono8  = _font("mono",  8)
    f_mono9  = _font("mono",  9)
    f_mono10 = _font("mono", 10)
    f_mono11 = _font("mono", 11)
    f_mono13 = _font("mono", 13)
    f_bold16 = _font("bold", 16)
    f_bold20 = _font("bold", 20)
    f_cjk11  = _font("cjk",  11)

    faction_label = FACTION_LABEL.get(faction, faction.upper())
    draw.text((18, 14), faction_label, fill=GOLD, font=f_mono10)

    stars_filled = RARITY_STARS.get(rarity, 1)
    stars_str = "★" * stars_filled + "☆" * (5 - stars_filled)
    b = _bb(draw, stars_str, f_mono10)
    draw.text((CW - 18 - (b[2] - b[0]), 14), stars_str, fill=GOLD, font=f_mono10)

    # portrait circle
    AV_CY, AV_R = 148, 82
    _dashed_ring(draw, cx, AV_CY, AV_R + 6, GOLD)
    draw.ellipse([cx - AV_R, AV_CY - AV_R, cx + AV_R, AV_CY + AV_R], fill=AV_BG)
    if img_bytes:
        _paste_circle(card, img_bytes, cx, AV_CY, AV_R)
        draw = ImageDraw.Draw(card)

    # name
    _draw_centered(draw, name.upper(), f_bold20, cx, 245, CREAM)
    _draw_centered(draw, title, f_mono9, cx, 270, GOLD_D)

    # divider
    draw.line([(30, 285), (CW - 30, 285)], fill=(*GOLD, 100), width=1)

    # quote — word wrap to ~36 chars
    wrapped = textwrap.fill(f'"{quote}"', width=36)
    quote_lines = wrapped.split("\n")
    qy = 292
    for line in quote_lines:
        _draw_centered(draw, line, f_mono8, cx, qy, GOLD_DK)
        qy += 13

    # divider
    div2_y = max(qy + 4, 330)
    draw.line([(30, div2_y), (CW - 30, div2_y)], fill=(*GOLD, 100), width=1)

    # stat bars
    BAR_W = 110
    BAR_H = 10
    BAR_X = cx - BAR_W // 2
    stat_y = div2_y + 14

    stat_order = [
        ("AUTH", "authority", STAT_COLOR["authority"]),
        ("MIL",  "military",  STAT_COLOR["military"]),
        ("CHA",  "charisma",  STAT_COLOR["charisma"]),
    ]
    for label, key, color in stat_order:
        val = stats.get(key, 0)
        _stat_bar(draw, BAR_X, stat_y, BAR_W, BAR_H, val, color, label, f_mono9)
        stat_y += 20

    # footer
    foot_y = CH - 36
    draw.line([(10, foot_y), (CW - 10, foot_y)], fill=(*GOLD, 60), width=1)
    _draw_centered(draw, "GLORY TO THE CCP!", f_mono9, cx, foot_y + 6, GOLD_D)
    _draw_centered(draw, "中华人民共和国社会信用局", f_cjk11, cx, foot_y + 20, GOLD_DK)

    buf = io.BytesIO()
    card.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
