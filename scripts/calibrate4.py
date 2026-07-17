"""Calibration round 4: measure height AND width of the key panels.

- R1C1 (display id 7): horizontal bands 0-11 top-to-bottom (height count)
- R1C3 (display id 9): vertical bands 0-11 left-to-right (width count)
- R2C2 (display id 3): solid green 96x68 with white border - if 68 is the
  true height this shows a full border and NO bleed below.
"""

import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "streamdock"))

from PIL import Image, ImageDraw, ImageFont

from LibUSBHIDAPI import LibUSBHIDAPI

BAND_COLORS = [
    (255, 0, 0),
    (255, 128, 0),
    (255, 255, 0),
    (0, 200, 0),
    (0, 255, 255),
    (0, 80, 255),
    (150, 0, 255),
    (255, 0, 255),
    (255, 255, 255),
    (128, 128, 128),
    (150, 75, 0),
    (0, 0, 0),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("arialbd.ttf", size)
    except OSError:
        return ImageFont.load_default()


def hbands() -> bytes:
    img = Image.new("RGB", (96, 96))
    d = ImageDraw.Draw(img)
    for i, color in enumerate(BAND_COLORS):
        y0 = i * 8
        d.rectangle([0, y0, 95, y0 + 7], fill=color)
        fill = "white" if sum(color) < 380 else "black"
        d.text((4, y0 + 4), str(i), font=_font(8), fill=fill, anchor="lm")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95, subsampling=0)
    return buf.getvalue()


def vbands() -> bytes:
    img = Image.new("RGB", (96, 96))
    d = ImageDraw.Draw(img)
    for i, color in enumerate(BAND_COLORS):
        x0 = i * 8
        d.rectangle([x0, 0, x0 + 7, 95], fill=color)
        fill = "white" if sum(color) < 380 else "black"
        d.text((x0 + 4, 6), str(i), font=_font(8), fill=fill, anchor="mm")
        d.text((x0 + 4, 48), str(i), font=_font(8), fill=fill, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95, subsampling=0)
    return buf.getvalue()


def border_68() -> bytes:
    img = Image.new("RGB", (96, 68), (0, 150, 60))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 95, 67], outline="white", width=2)
    d.text((48, 34), "96x68", font=_font(14), fill="white", anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95, subsampling=0)
    return buf.getvalue()


def main() -> None:
    devices = LibUSBHIDAPI.enumerate_devices(0x5548, 0x1000)
    if not devices:
        print("device not found", flush=True)
        return
    api = LibUSBHIDAPI()
    api._device_info = LibUSBHIDAPI.create_device_info_from_dict(devices[0])
    if not api.open(devices[0]["path"].encode()):
        print("open failed", flush=True)
        return
    api.change_mode(2)
    api.wakeup_screen()
    api.set_key_brightness(90)
    api.clear_all_keys()
    time.sleep(0.3)

    api.set_key_image_stream(hbands(), 7)
    api.set_key_image_stream(vbands(), 9)
    api.set_key_image_stream(border_68(), 3)
    api.refresh_screen()
    print("painted; holding 4 min", flush=True)

    last_beat = time.time()
    deadline = time.time() + 240
    while time.time() < deadline:
        if time.time() - last_beat > 8:
            api.heartbeat()
            last_beat = time.time()
        api.read(timeout_ms=200)
    api.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
