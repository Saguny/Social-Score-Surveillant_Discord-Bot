"""
Renders a 1080x1080 share card for /serverrank card.
Synchronous — call via loop.run_in_executor(None, render_card, ...).
"""

import io
import math
import os

import matplotlib
matplotlib.use("Agg")
_MPL_FONT_DIR = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
_LOCAL_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")

from PIL import Image, ImageDraw, ImageFont

# ── Palette ────────────────────────────────────────────────────────────────────
BG        = "#7A1F1F"
BG_INNER  = "#5C1414"
GOLD      = "#D4AF37"
GOLD_DIM  = "#9C7A40"
GOLD_DARK = "#8A6A38"
CREAM     = "#F0DDC0"
WARM      = "#C9A86A"
WHITE     = "#FFFFFF"
DARK_RED  = "#7A1F1F"

W = H = 1080
_NAME_MARGIN = 90   # px from each side for server name
_NAME_MAX_W  = W - _NAME_MARGIN * 2


# ── Font loading ───────────────────────────────────────────────────────────────
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates: list[str] = []
    if name == "cjk":
        candidates = [
            os.path.join(_LOCAL_FONT_DIR, "NotoSansSC-Regular.otf"),
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simsun.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]
    elif name == "serif":
        candidates = [
            os.path.join(_MPL_FONT_DIR, "DejaVuSerif.ttf"),
            "C:/Windows/Fonts/georgia.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        ]
    elif name == "mono-bold":
        candidates = [
            os.path.join(_MPL_FONT_DIR, "DejaVuSansMono-Bold.ttf"),
            "C:/Windows/Fonts/consolab.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        ]
    else:
        candidates = [
            os.path.join(_MPL_FONT_DIR, "DejaVuSansMono.ttf"),
            "C:/Windows/Fonts/consola.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _color(hex_str: str) -> tuple:
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


# ── Drawing helpers ────────────────────────────────────────────────────────────
def _visual_box(draw: ImageDraw.Draw, text: str, font: ImageFont.FreeTypeFont) -> tuple:
    """Returns (left, top, right, bottom) visual bounding box when drawn at origin."""
    return draw.textbbox((0, 0), text, font=font)


def _text_at(draw: ImageDraw.Draw, cx: int, cy: int, text: str,
              font: ImageFont.FreeTypeFont, color: str):
    """Draw text with its visual center at (cx, cy)."""
    b = _visual_box(draw, text, font)
    x = cx - (b[0] + b[2]) // 2
    y = cy - (b[1] + b[3]) // 2
    draw.text((x, y), text, fill=_color(color), font=font)


def _text_center(draw: ImageDraw.Draw, cy: int, text: str,
                 font: ImageFont.FreeTypeFont, color: str):
    _text_at(draw, W // 2, cy, text, font, color)


def _text_left(draw: ImageDraw.Draw, x: int, cy: int, text: str,
               font: ImageFont.FreeTypeFont, color: str):
    b = _visual_box(draw, text, font)
    draw.text((x, cy - (b[1] + b[3]) // 2), text, fill=_color(color), font=font)


def _text_right(draw: ImageDraw.Draw, rx: int, cy: int, text: str,
                font: ImageFont.FreeTypeFont, color: str):
    b = _visual_box(draw, text, font)
    x = rx - (b[2] - b[0]) - b[0]
    draw.text((x, cy - (b[1] + b[3]) // 2), text, fill=_color(color), font=font)


def _text_width(draw: ImageDraw.Draw, text: str, font: ImageFont.FreeTypeFont) -> int:
    b = _visual_box(draw, text, font)
    return b[2] - b[0]


def _text_height(draw: ImageDraw.Draw, text: str, font: ImageFont.FreeTypeFont) -> int:
    b = _visual_box(draw, text, font)
    return b[3] - b[1]


def _draw_server_name(draw: ImageDraw.Draw, name: str, zone_top: int, zone_bottom: int):
    """
    Render guild name auto-sized to fill zone_top..zone_bottom with max 2 lines.
    Tries font sizes from 30 down to 13. Finds the largest size where either:
      - the whole name fits on one line within _NAME_MAX_W, or
      - the name wraps cleanly to 2 lines each within _NAME_MAX_W,
        and the total block height fits in the zone.
    """
    available_h = zone_bottom - zone_top
    cy = (zone_top + zone_bottom) // 2

    words = name.split()

    for size in range(30, 12, -1):
        font = _font("mono-bold", size)
        line_h = _text_height(draw, "Ag", font)
        gap = max(4, size // 5)

        # try single line
        if _text_width(draw, name, font) <= _NAME_MAX_W and line_h <= available_h:
            _text_center(draw, cy, name, font, WHITE)
            return

        # try 2-line wrap — find best balanced split
        if len(words) < 2:
            continue
        best_split: tuple[str, str] | None = None
        best_balance = float("inf")
        for i in range(1, len(words)):
            l1 = " ".join(words[:i])
            l2 = " ".join(words[i:])
            w1 = _text_width(draw, l1, font)
            w2 = _text_width(draw, l2, font)
            if w1 <= _NAME_MAX_W and w2 <= _NAME_MAX_W:
                balance = abs(w1 - w2)
                if balance < best_balance:
                    best_balance = balance
                    best_split = (l1, l2)

        if best_split:
            total_h = line_h * 2 + gap
            if total_h <= available_h:
                l1, l2 = best_split
                y1 = cy - total_h // 2 + line_h // 2
                y2 = y1 + line_h + gap
                _text_center(draw, y1, l1, font, WHITE)
                _text_center(draw, y2, l2, font, WHITE)
                return

    # absolute fallback at min size — just draw, may clip
    font = _font("mono-bold", 13)
    _text_center(draw, cy, name, font, WHITE)


def _star_polygon(cx: int, cy: int) -> list[tuple[int, int]]:
    return [
        (cx +  0, cy - 95),
        (cx + 28, cy - 30),
        (cx + 98, cy - 30),
        (cx + 42, cy + 12),
        (cx + 62, cy + 80),
        (cx +  0, cy + 38),
        (cx - 62, cy + 80),
        (cx - 42, cy + 12),
        (cx - 98, cy - 30),
        (cx - 28, cy - 30),
    ]


def _paste_icon(card: Image.Image, icon_bytes: bytes, cx: int, cy: int, radius: int):
    try:
        icon = Image.open(io.BytesIO(icon_bytes)).convert("RGBA")
        d = radius * 2
        icon = icon.resize((d, d), Image.LANCZOS)
        mask = Image.new("L", (d, d), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
        card.paste(icon, (cx - radius, cy - radius), mask)
    except Exception:
        pass


def _draw_dashed_circle(draw: ImageDraw.Draw, cx: int, cy: int, r: int,
                        color: str, n_dashes: int = 20):
    step = 2 * math.pi / n_dashes
    c = _color(color)
    for i in range(n_dashes):
        if i % 2 == 0:
            a0 = i * step - math.pi / 2
            a1 = a0 + step * 0.7
            pts = [(cx + r * math.cos(a0 + (a1 - a0) * t / 11),
                    cy + r * math.sin(a0 + (a1 - a0) * t / 11)) for t in range(12)]
            draw.line(pts, fill=c, width=3)


# ── Public API ─────────────────────────────────────────────────────────────────
def render_card(
    *,
    guild_name: str,
    rank: int,
    bracket: str,
    metric: str,
    metric_label: str,
    metric_value: str,
    trend_arrow: str,
    trend_delta: str,
    percentile: float,
    rivals_line: str,
    icon_bytes: bytes | None,
    date_str: str,
) -> bytes:
    card = Image.new("RGB", (W, H), _color(BG))
    draw = ImageDraw.Draw(card)

    # star texture
    tex = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tex_draw = ImageDraw.Draw(tex)
    f_tex = _font("mono", 22)
    star_c = (*_color(GOLD), 15)
    for row in range(0, H, 120):
        for col in range(0, W, 120):
            tex_draw.text((col + 10, row + 10), "★", fill=star_c, font=f_tex)
            tex_draw.text((col + 70, row + 70), "★", fill=star_c, font=f_tex)
    card = Image.alpha_composite(card.convert("RGBA"), tex).convert("RGB")
    draw = ImageDraw.Draw(card)

    # double border
    gold = _color(GOLD)
    draw.rectangle([28, 28, W - 28, H - 28], outline=gold, width=4)
    draw.rectangle([44, 44, W - 44, H - 44], outline=gold, width=2)

    # fixed-size fonts
    f_cjk     = _font("cjk",       28)
    f_serif   = _font("serif",     18)
    f_mono_s  = _font("mono",      16)
    f_mono_m  = _font("mono",      20)
    f_mono_l  = _font("mono",      30)
    f_mono_xl = _font("mono",      44)
    f_mono_b  = _font("mono-bold", 34)
    f_footer  = _font("mono",      14)

    # header
    _text_center(draw, 100, "中华人民共和国", f_cjk, GOLD)
    _text_center(draw, 136, "SOCIAL CREDIT ALMANAC", f_serif, CREAM)
    draw.line([(160, 162), (920, 162)], fill=gold, width=2)

    # server icon
    icon_cx, icon_cy, icon_r = 540, 240, 58
    icon_bottom = icon_cy + icon_r          # 298
    draw.ellipse(
        [icon_cx - icon_r, icon_cy - icon_r, icon_cx + icon_r, icon_cy + icon_r],
        fill=_color(BG_INNER),
    )
    _draw_dashed_circle(draw, icon_cx, icon_cy, icon_r + 3, GOLD)
    if icon_bytes:
        _paste_icon(card, icon_bytes, icon_cx, icon_cy, icon_r)
        draw = ImageDraw.Draw(card)

    # server name — auto-sized, max 2 lines, no overlap with star
    star_cx, star_cy = 540, 490
    star_top = star_cy - 95             # 395
    name_zone_top    = icon_bottom + 14 # 312
    name_zone_bottom = star_top  - 10  # 385
    _draw_server_name(draw, guild_name, name_zone_top, name_zone_bottom)

    # star medallion
    star_pts = _star_polygon(star_cx, star_cy)
    draw.polygon(star_pts, fill=gold)
    draw.polygon(star_pts, outline=_color(DARK_RED), width=3)

    # rank inside star — visual center of star body is at (star_cx, star_cy)
    _text_at(draw, star_cx, star_cy, f"#{rank}", f_mono_b, DARK_RED)

    # bracket
    _text_center(draw, 615, bracket, f_mono_m, CREAM)

    # metric section
    draw.line([(220, 660), (860, 660)], fill=(*gold, 128), width=1)
    _text_center(draw, 710, metric_label.upper(), f_mono_s, WARM)
    _text_center(draw, 775, metric_value, f_mono_xl, WHITE)

    trend_text = f"{trend_arrow}  {trend_delta}  THIS WEEK" if trend_delta else "— NO HISTORY YET"
    _text_center(draw, 820, trend_text, f_mono_s, CREAM)

    pct_text = f"TOP {percentile:.0f}%"
    _text_center(draw, 868, pct_text, f_mono_l, GOLD)

    if rivals_line:
        _text_center(draw, 920, rivals_line, f_mono_s, WARM)

    # footer
    draw.line([(160, 952), (920, 952)], fill=(*gold, 80), width=1)
    _text_left(draw,  120, 970, date_str,                              f_footer, GOLD_DIM)
    _text_center(draw, 970, "tracked by social credit surveillant",    f_footer, GOLD_DARK)
    _text_right(draw, 960, 970, "GLORY TO THE CCP!",                  f_footer, GOLD_DIM)

    buf = io.BytesIO()
    card.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
