"""Render polished key tiles as device-ready JPEGs.

KEY_SIZE is the panel's true native resolution (calibrated empirically:
oversized images bleed into neighboring keys; 64x64 fills perfectly).
"""

import io
import re

from PIL import Image, ImageDraw, ImageFont

KEY_SIZE = 64
MAX_JPEG_BYTES = 10240

STATE_COLORS = {
    "idle": (38, 166, 91),
    "running": (43, 108, 224),
    "permission": (222, 152, 0),
    "question": (150, 92, 240),
    "error": (222, 56, 43),
    "offline": (60, 66, 82),
    "empty": (16, 18, 24),
    "action": (28, 96, 120),
}


def _sanitize(text: str) -> str:
    """Keep only printable ASCII the deck font can render, and drop any leading
    non-alphanumeric noise (e.g. VS Code's mojibake emoji prefix)."""
    ascii_only = "".join(c for c in text if 0x20 <= ord(c) <= 0x7E)
    ascii_only = re.sub(r"^[^0-9A-Za-z]+", "", ascii_only)
    return " ".join(ascii_only.split())


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _vertical_gradient(img: Image.Image, color: tuple) -> None:
    """Fill img with color, lighter at the top, darker at the bottom."""
    w, h = img.size
    draw = ImageDraw.Draw(img)
    r, g, b = color
    for y in range(h):
        t = y / h
        factor = 1.18 - 0.36 * t
        draw.line(
            [(0, y), (w, y)],
            fill=(
                min(255, int(r * factor)),
                min(255, int(g * factor)),
                min(255, int(b * factor)),
            ),
        )


def _draw_glyph(draw: ImageDraw.ImageDraw, state: str, cx: int, cy: int, s: int) -> None:
    """Draw a state glyph as vector shapes centered at (cx, cy), scale s."""
    white = (255, 255, 255)
    if state in ("idle",):
        draw.line(
            [(cx - s, cy), (cx - s * 0.2, cy + s * 0.7), (cx + s, cy - s * 0.6)],
            fill=white,
            width=3,
            joint="curve",
        )
    elif state == "running":
        for dx in (-s * 0.55, s * 0.35):
            draw.polygon(
                [
                    (cx + dx - s * 0.3, cy - s * 0.7),
                    (cx + dx + s * 0.5, cy),
                    (cx + dx - s * 0.3, cy + s * 0.7),
                ],
                fill=white,
            )
    elif state == "permission":
        draw.rounded_rectangle(
            [cx - 2, cy - s * 0.8, cx + 2, cy + s * 0.25], radius=2, fill=white
        )
        draw.ellipse([cx - 2.5, cy + s * 0.5, cx + 2.5, cy + s * 0.5 + 5], fill=white)
    elif state == "question":
        draw.text((cx, cy), "?", font=_font(int(s * 2.2)), fill=white, anchor="mm")
    elif state == "error":
        k = s * 0.65
        draw.line([(cx - k, cy - k), (cx + k, cy + k)], fill=white, width=3)
        draw.line([(cx - k, cy + k), (cx + k, cy - k)], fill=white, width=3)
    elif state == "offline":
        draw.text((cx, cy), "zz", font=_font(int(s * 1.4)), fill=white, anchor="mm")


def _fit_label(label: str, max_chars: int = 9) -> list[str]:
    """Split a project name into up to 2 display lines."""
    if len(label) <= max_chars:
        return [label]
    for sep in ("-", "_", " "):
        if sep in label:
            head, _, tail = label.partition(sep)
            if 2 <= len(head) <= max_chars:
                second = tail if len(tail) <= max_chars else tail[: max_chars - 1] + "…"
                return [head, second]
    return [label[:max_chars], label[max_chars : max_chars * 2 - 1] + "…"]


ACTION_BG = {
    "design": (150, 110, 20),
    "review": (28, 96, 120),
    "compact": (96, 64, 150),
}


def _draw_action_icon(draw: ImageDraw.ImageDraw, name: str, cx: int, cy: int, s: int) -> None:
    white = (255, 255, 255)
    w = 3
    if name == "design":  # lightbulb
        draw.ellipse([cx - s, cy - s, cx + s, cy + s], outline=white, width=w)
        draw.line([cx - s * 0.45, cy + s * 0.9, cx - s * 0.45, cy + s * 1.6], fill=white, width=w)
        draw.line([cx + s * 0.45, cy + s * 0.9, cx + s * 0.45, cy + s * 1.6], fill=white, width=w)
        draw.line([cx - s * 0.45, cy + s * 1.6, cx + s * 0.45, cy + s * 1.6], fill=white, width=w)
        for dx, dy in ((-1.6, -1.4), (0, -1.9), (1.6, -1.4)):
            draw.line(
                [cx + dx * s * 0.7, cy + dy * s * 0.7, cx + dx * s, cy + dy * s],
                fill=white,
                width=2,
            )
    elif name == "review":  # magnifying glass
        r = s * 0.8
        lx, ly = cx - s * 0.2, cy - s * 0.2
        draw.ellipse([lx - r, ly - r, lx + r, ly + r], outline=white, width=w)
        draw.line([lx + r * 0.7, ly + r * 0.7, cx + s * 1.15, cy + s * 1.15], fill=white, width=w + 1)
    elif name == "compact":  # compress toward center
        draw.line([cx - s, cy, cx + s, cy], fill=white, width=1)
        draw.line([cx - s * 0.75, cy - s, cx, cy - s * 0.2], fill=white, width=w)
        draw.line([cx + s * 0.75, cy - s, cx, cy - s * 0.2], fill=white, width=w)
        draw.line([cx - s * 0.75, cy + s, cx, cy + s * 0.2], fill=white, width=w)
        draw.line([cx + s * 0.75, cy + s, cx, cy + s * 0.2], fill=white, width=w)


def render_action(name: str, label: str) -> bytes:
    size = KEY_SIZE
    color = ACTION_BG.get(name, STATE_COLORS["action"])
    img = Image.new("RGB", (size, size), color)
    _vertical_gradient(img, color)
    draw = ImageDraw.Draw(img)
    _draw_action_icon(draw, name, size // 2, 24, 13)
    draw.text((size // 2, size - 11), _sanitize(label)[:8], font=_font(11), fill="white", anchor="mm")

    data = b""
    for quality in range(90, 10, -10):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, subsampling=0)
        data = buf.getvalue()
        if len(data) <= MAX_JPEG_BYTES:
            return data
    return data[:MAX_JPEG_BYTES]


def render_key(label: str, state: str, sublabel: str = "") -> bytes:
    size = KEY_SIZE
    color = STATE_COLORS.get(state, STATE_COLORS["offline"])
    img = Image.new("RGB", (size, size), color)

    if state == "empty":
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    _vertical_gradient(img, color)

    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    band_h = int(size * 0.42)
    odraw.rounded_rectangle(
        [2, band_h, size - 3, size - 3],
        radius=6,
        fill=(0, 0, 0, 110),
    )
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)
    _draw_glyph(draw, state, size // 2, int(band_h * 0.52), int(size * 0.15))

    label = _sanitize(label)
    lines = _fit_label(label) if label else []
    text_area_top = band_h
    text_area_h = size - 3 - band_h
    font = _font(11 if len(lines) > 1 else 12)
    if len(lines) == 1:
        draw.text(
            (size // 2, text_area_top + text_area_h // 2),
            lines[0],
            font=font,
            fill="white",
            anchor="mm",
        )
    elif lines:
        cy = text_area_top + text_area_h // 2
        draw.text((size // 2, cy - 7), lines[0], font=font, fill="white", anchor="mm")
        draw.text((size // 2, cy + 7), lines[1], font=font, fill="white", anchor="mm")

    if sublabel:
        draw.text((4, 2), sublabel, font=_font(9), fill=(255, 255, 255, 160))

    data = b""
    for quality in range(90, 10, -10):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, subsampling=0)
        data = buf.getvalue()
        if len(data) <= MAX_JPEG_BYTES:
            return data
    return data[:MAX_JPEG_BYTES]
