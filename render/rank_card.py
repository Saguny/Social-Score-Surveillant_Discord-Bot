import io
import math
import os
import unicodedata

import matplotlib
matplotlib.use("Agg")
_MPL_FONT_DIR = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
_LOCAL_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")

from PIL import Image, ImageDraw, ImageFont

W, H = 900, 280

# colours matching SVG exactly
BG       = (11,  6,  6)
LEFT_BG  = (19, 10, 10)
AV_BG    = (42, 18, 18)
GOLD     = (200, 168,  75)
GOLD_D   = (154, 122,  53)   # #9A7A35
GOLD_D2  = (106,  74,  24)   # #6A4A18
GOLD_DK  = ( 90,  58,  16)   # #5A3A10
GOLD_DK2 = ( 58,  32,   8)   # #3A2008
BADGE_C  = (122,  90,  32)   # #7A5A20
GREY_RK  = (136, 136, 136)   # #888
GOLD_RK  = (232, 192,  96)   # #E8C060
CREAM    = (224, 224, 224)
GREEN    = ( 92, 184,  92)


def _ascii_badge(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label)
    return "".join(c for c in normalized if c.isascii() and c.isprintable())


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    if name == "cjk":
        paths = [
            os.path.join(_LOCAL_FONT_DIR, "NotoSansSC-Regular.otf"),
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simsun.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]
    elif name == "mono-bold":
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


def _at_baseline(draw, x, y_baseline, text, font, color):
    """Draw text so its baseline sits at y_baseline (mirrors SVG text y)."""
    b = _bb(draw, text, font)
    draw.text((x, y_baseline - b[3]), text, fill=color, font=font)


def _centered_baseline(draw, cx, y_baseline, text, font, color):
    b = _bb(draw, text, font)
    x = cx - (b[2] - b[0]) // 2
    draw.text((x, y_baseline - b[3]), text, fill=color, font=font)


def _dashed_ring(draw, cx, cy, r, color, n=20):
    step = 2 * math.pi / n
    for i in range(n):
        if i % 2 == 0:
            a0 = i * step - math.pi / 2
            a1 = a0 + step * 0.7
            pts = [(cx + r * math.cos(a0 + (a1 - a0) * t / 11),
                    cy + r * math.sin(a0 + (a1 - a0) * t / 11)) for t in range(12)]
            draw.line(pts, fill=color, width=2)


def _paste_avatar(card, avatar_bytes, cx, cy, r):
    try:
        av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        d = r * 2
        av = av.resize((d, d), Image.LANCZOS)
        mask = Image.new("L", (d, d), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
        card.paste(av, (cx - r, cy - r), mask)
    except Exception:
        pass


def render_rank_card(
    *,
    old_rank: str,
    new_rank: str,
    username: str,
    score: float,
    yuan_label: str,
    avatar_bytes: bytes | None,
    badge_label: str | None,
    bot_name: str = "Social Credit Surveillant",
) -> bytes:
    # ── base + star texture ──────────────────────────────────────────────────────
    card = Image.new("RGB", (W, H), BG)
    tex = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tex_draw = ImageDraw.Draw(tex)
    f_star = _font("mono", 18)
    star_c = (*GOLD, 20)
    for row in range(0, H, 45):
        for col in range(0, W, 45):
            tex_draw.text((col + 6,  row + 6),  "★", fill=star_c, font=f_star)
            tex_draw.text((col + 26, row + 26), "★", fill=star_c, font=f_star)
    card = Image.alpha_composite(card.convert("RGBA"), tex).convert("RGB")
    draw = ImageDraw.Draw(card)

    # ── left panel bg ────────────────────────────────────────────────────────────
    draw.rectangle([8, 8, 228, 272], fill=LEFT_BG)   # outer rect
    draw.rectangle([14, 14, 222, 266], fill=LEFT_BG)  # inner rect (cover border overlap)

    # ── borders ──────────────────────────────────────────────────────────────────
    draw.rectangle([8, 8, 892, 272], outline=GOLD, width=3)
    draw.rectangle([14, 14, 886, 266], outline=(*GOLD, 128), width=1)

    # ── vertical divider ─────────────────────────────────────────────────────────
    draw.line([(228, 30), (228, 250)], fill=(*GOLD, 153), width=1)

    # ── fonts ────────────────────────────────────────────────────────────────────
    f_cjk13  = _font("cjk",  13)
    f_cjk11  = _font("cjk",  11)
    f_mono8  = _font("mono",  8)
    f_mono85 = _font("mono",  9)   # closest to 8.5
    f_mono10 = _font("mono", 10)
    f_mono11 = _font("mono", 11)
    f_mono18 = _font("mono", 18)
    f_mono22 = _font("mono", 22)
    f_bold20 = _font("mono-bold", 20)

    # ── left panel ───────────────────────────────────────────────────────────────
    _centered_baseline(draw, 117, 52, "中华人民共和国", f_cjk13, GOLD)
    _centered_baseline(draw, 117, 70, "社会信用局",     f_cjk11, GOLD_D)
    draw.line([(50, 78), (184, 78)], fill=(*GOLD, 100), width=1)

    # avatar: dashed ring r=48, filled circle r=42, pfp pasted
    AV_CX, AV_CY, AV_R = 117, 139, 42
    _dashed_ring(draw, AV_CX, AV_CY, AV_R + 6, GOLD)
    draw.ellipse([AV_CX - AV_R, AV_CY - AV_R, AV_CX + AV_R, AV_CY + AV_R], fill=AV_BG)
    if avatar_bytes:
        _paste_avatar(card, avatar_bytes, AV_CX, AV_CY, AV_R)
        draw = ImageDraw.Draw(card)

    draw.line([(50, 196), (184, 196)], fill=(*GOLD, 100), width=1)
    _centered_baseline(draw, 117, 214, "DEPT. OF CITIZEN AFFAIRS", f_mono85, BADGE_C)
    _centered_baseline(draw, 117, 228, "SOCIAL CREDIT BUREAU",     f_mono8,  GOLD_DK)

    # ── right panel ──────────────────────────────────────────────────────────────
    _at_baseline(draw, 256, 50, "STANDING ELEVATED", f_mono11, GOLD_D)
    draw.line([(256, 58), (875, 58)], fill=(*GOLD, 76), width=1)

    # citizen row
    _at_baseline(draw, 256, 82, "CITIZEN", f_mono10, GOLD_D)
    citizen_value = f"@{username}"
    if badge_label:
        citizen_value += f"  ·  {_ascii_badge(badge_label)}"
    _at_baseline(draw, 340, 82, citizen_value, f_mono10, CREAM)

    # previous rank
    _at_baseline(draw, 256, 111, "PREVIOUS", f_mono10, GOLD_D)
    _at_baseline(draw, 256, 138, old_rank,   f_bold20, GREY_RK)

    # arrow (fixed position matching SVG x=556)
    _at_baseline(draw, 556, 138, "->", f_mono22, GOLD)

    # current rank
    _at_baseline(draw, 594, 111, "CURRENT", f_mono10, GOLD_D)
    _at_baseline(draw, 594, 138, new_rank,  f_bold20, GOLD_RK)

    # mid divider
    draw.line([(256, 162), (875, 162)], fill=(*GOLD, 64), width=1)

    # rating + reward - use fixed top-left y so ¥ glyph height doesn't misalign them
    _at_baseline(draw, 256, 193, "RATING", f_mono10, GOLD_D)
    _at_baseline(draw, 388, 193, "REWARD", f_mono10, GOLD_D)
    draw.text((256, 196), f"{score:.2f}", fill=CREAM,        font=f_mono18)
    reward_color = GREEN if "+" in yuan_label else (200, 80, 80)
    draw.text((388, 196), yuan_label,      fill=reward_color, font=f_mono18)

    # vertical sep
    draw.line([(370, 168), (370, 230)], fill=(*GOLD, 76), width=1)

    # footer
    draw.line([(256, 234), (875, 234)], fill=(*GOLD, 51), width=1)
    f_cjk9 = _font("cjk", 9)
    latin_prefix = "GLORY TO THE CCP!  \xb7  "
    b_mono = _bb(draw, latin_prefix, f_mono85)
    b_cjk  = _bb(draw, "中华人民共和国社会信用局", f_cjk9)
    footer_y = 252 - b_mono[3]
    cjk_y   = footer_y + b_mono[1] - b_cjk[1] - 2
    draw.text((256, footer_y), latin_prefix, fill=GOLD_D, font=f_mono85)
    draw.text((256 + b_mono[2], cjk_y), "中华人民共和国社会信用局", fill=GOLD_D, font=f_cjk9)
    b = _bb(draw, bot_name, f_mono85)
    draw.text((875 - (b[2] - b[0]), footer_y), bot_name, fill=GOLD_D, font=f_mono85)

    buf = io.BytesIO()
    card.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


PW, PH = 420, 580
PAD = 22


def render_profile_card(
    *,
    username: str,
    score: float,
    yuan: int,
    rank_name: str,
    next_rank_name: str | None,
    pts_to_next: float | None,
    rank_min: int,
    rank_max: int,
    avatar_bytes: bytes | None,
    badge_label: str | None,
    bot_name: str = "Social Credit Surveillant",
) -> bytes:
    CX = PW // 2

    card = Image.new("RGB", (PW, PH), BG)
    tex = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    tex_draw = ImageDraw.Draw(tex)
    f_star = _font("mono", 14)
    star_c = (*GOLD, 20)
    for row in range(0, PH, 40):
        for col in range(0, PW, 40):
            tex_draw.text((col + 4,  row + 4),  "★", fill=star_c, font=f_star)
            tex_draw.text((col + 22, row + 22), "★", fill=star_c, font=f_star)
    card = Image.alpha_composite(card.convert("RGBA"), tex).convert("RGB")
    draw = ImageDraw.Draw(card)

    draw.rectangle([6, 6, PW - 6, PH - 6], outline=GOLD, width=3)
    draw.rectangle([12, 12, PW - 12, PH - 12], outline=(*GOLD, 100), width=1)

    f_cjk18 = _font("cjk", 18)
    f_cjk14 = _font("cjk", 14)
    f_cjk13 = _font("cjk", 13)
    f_mono9  = _font("mono",  9)
    f_mono10 = _font("mono", 10)
    f_mono11 = _font("mono", 11)
    f_mono13 = _font("mono", 13)
    f_bold26 = _font("mono-bold", 26)
    f_bold32 = _font("mono-bold", 32)
    f_bold14 = _font("mono-bold", 14)

    # CJK header
    _centered_baseline(draw, CX, 46, "中华人民共和国", f_cjk18, GOLD)
    _centered_baseline(draw, CX, 66, "社会信用局",     f_cjk14, GOLD_D)
    draw.line([(PAD, 74), (PW - PAD, 74)], fill=(*GOLD, 100), width=1)

    # avatar
    AV_CX, AV_CY, AV_R = CX, 148, 54
    _dashed_ring(draw, AV_CX, AV_CY, AV_R + 7, GOLD)
    draw.ellipse([AV_CX - AV_R, AV_CY - AV_R, AV_CX + AV_R, AV_CY + AV_R], fill=AV_BG)
    if avatar_bytes:
        _paste_avatar(card, avatar_bytes, AV_CX, AV_CY, AV_R)
        draw = ImageDraw.Draw(card)

    draw.line([(PAD, 218), (PW - PAD, 218)], fill=(*GOLD, 100), width=1)

    # username (big)
    _centered_baseline(draw, CX, 258, username, f_bold32, CREAM)

    # badge below name
    if badge_label:
        _centered_baseline(draw, CX, 278, _ascii_badge(badge_label), f_bold14, GOLD_D)

    draw.line([(PAD, 290), (PW - PAD, 290)], fill=(*GOLD, 60), width=1)

    # rank
    _centered_baseline(draw, CX, 310, "RANK", f_mono10, GOLD_D)
    _centered_baseline(draw, CX, 340, rank_name, f_bold26, GOLD_RK)

    draw.line([(PAD, 352), (PW - PAD, 352)], fill=(*GOLD, 60), width=1)

    # score + yuan
    _centered_baseline(draw, CX // 2, 372, "SOCIAL CREDIT", f_mono10, GOLD_D)
    _centered_baseline(draw, CX + CX // 2, 372, "BALANCE",       f_mono10, GOLD_D)
    draw.line([(CX, 354), (CX, 412)], fill=(*GOLD, 60), width=1)
    _centered_baseline(draw, CX // 2,       408, f"{score:.2f}",  f_bold26, CREAM)
    _centered_baseline(draw, CX + CX // 2,  408, f"\xa5{yuan:,}", f_bold26, CREAM)

    draw.line([(PAD, 414), (PW - PAD, 414)], fill=(*GOLD, 40), width=1)

    # progress bar
    BAR_X0, BAR_X1, BAR_Y0, BAR_Y1 = PAD, PW - PAD, 422, 432
    bar_w = BAR_X1 - BAR_X0
    band = max(rank_max - rank_min, 1)
    progress = min(max((score - rank_min) / band, 0.0), 1.0)
    fill_w = int(bar_w * progress)
    draw.rectangle([BAR_X0, BAR_Y0, BAR_X1, BAR_Y1], fill=(30, 20, 20))
    if fill_w > 0:
        draw.rectangle([BAR_X0, BAR_Y0, BAR_X0 + fill_w, BAR_Y1], fill=GREEN)
    draw.rectangle([BAR_X0, BAR_Y0, BAR_X1, BAR_Y1], outline=(*GOLD, 80), width=1)

    if next_rank_name and pts_to_next is not None:
        progress_label = f"{pts_to_next:.2f} TO {next_rank_name.upper()}"
    else:
        progress_label = "PEAK LOYALTY ACHIEVED"
    b = _bb(draw, progress_label, f_mono9)
    draw.text((PW - PAD - (b[2] - b[0]), 436), progress_label, fill=GOLD_D, font=f_mono9)

    # footer panel — inset so the outer gold border shows on all sides
    FOOT_Y = 462
    draw.rectangle([9, FOOT_Y, PW - 9, PH - 9], fill=LEFT_BG)
    draw.line([(9, FOOT_Y), (PW - 9, FOOT_Y)], fill=GOLD, width=2)
    # redraw inner border over the footer fill
    inner_color = (*GOLD, 100)
    draw.line([(12, FOOT_Y), (12, PH - 12)],        fill=inner_color, width=1)
    draw.line([(PW - 12, FOOT_Y), (PW - 12, PH - 12)], fill=inner_color, width=1)
    draw.line([(12, PH - 12), (PW - 12, PH - 12)],  fill=inner_color, width=1)

    _centered_baseline(draw, CX, FOOT_Y + 36, "GLORY TO THE CCP!", f_mono13, GOLD)
    _centered_baseline(draw, CX, FOOT_Y + 56, "中华人民共和国社会信用局", f_cjk13, GOLD_D)
    draw.line([(80, FOOT_Y + 62), (PW - 80, FOOT_Y + 62)], fill=(*GOLD, 60), width=1)
    _centered_baseline(draw, CX, FOOT_Y + 82, bot_name, f_mono13, GOLD_D)

    buf = io.BytesIO()
    card.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
