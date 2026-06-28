import io
import math
from PIL import Image, ImageOps

W, H = 720, 128
AVATAR_SIZE = 128


def _circle_crop(img: Image.Image, size: int) -> Image.Image:
    img = img.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    from PIL import ImageDraw
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, mask=mask)
    return out


def render_compare_banner(avatar_left: bytes, avatar_right: bytes) -> bytes:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    left_img = _circle_crop(Image.open(io.BytesIO(avatar_left)), AVATAR_SIZE)
    right_img = _circle_crop(Image.open(io.BytesIO(avatar_right)), AVATAR_SIZE)

    canvas.paste(left_img, (0, 0), left_img)
    canvas.paste(right_img, (W - AVATAR_SIZE, 0), right_img)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
