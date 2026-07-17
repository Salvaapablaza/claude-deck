"""Resolution calibration + key listener.

Paints the top row with border-frame test images at different resolutions.
The key whose white border is fully visible on all 4 sides reveals the
panel's native resolution. Bottom rows get filled tiles for contrast.
Listens for key presses for 5 minutes.
"""

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw, ImageFont

from claude_deck.device import StreamDock

RESOLUTIONS = [96, 100, 112, 85, 80]
COLORS = [(31, 111, 235), (46, 160, 67), (210, 153, 34), (163, 113, 247), (218, 54, 51)]


def frame_image(size: int, color: tuple, label: str) -> bytes:
    img = Image.new("RGB", (size, size), color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, size - 1, size - 1], outline="white", width=2)
    draw.line([0, 0, 10, 10], fill="white", width=3)
    draw.line([size - 1, 0, size - 11, 10], fill="white", width=3)
    draw.line([0, size - 1, 10, size - 11], fill="white", width=3)
    draw.line([size - 1, size - 1, size - 11, size - 11], fill="white", width=3)
    try:
        font = ImageFont.truetype("arialbd.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
    draw.text((size // 2, size // 2), label, font=font, fill="white", anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def main() -> None:
    deck = StreamDock()
    deck.open()
    deck.send_connect()
    time.sleep(0.2)
    deck.wake_screen()
    deck.set_brightness(80)
    deck.clear_panel()
    time.sleep(0.2)

    for col, (res, color) in enumerate(zip(RESOLUTIONS, COLORS)):
        key_id = 11 + col
        deck.set_key_jpeg(key_id, frame_image(res, color, str(res)))
        print(f"top row col {col}: {res}x{res} frame", flush=True)

    print("calibration painted; listening 5 min - press keys now", flush=True)
    deck.start_heartbeat()

    deadline = time.time() + 300
    while time.time() < deadline:
        data = deck.read_raw(timeout_ms=500)
        if data:
            head = " ".join(f"{b:02x}" for b in data[:16])
            print(f"report: {head}", flush=True)

    deck.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
