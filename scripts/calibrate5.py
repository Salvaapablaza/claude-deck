"""Calibration round 5: decisive size test with MCU-aligned dimensions.

R1C1 (id 7): 64x64 red frame
R1C3 (id 9): 72x72 green frame
R2C2 (id 3): 80x80 blue frame

The winner fills its key with a full border and causes no bleed anywhere.
"""

import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "streamdock"))

from PIL import Image, ImageDraw, ImageFont

from LibUSBHIDAPI import LibUSBHIDAPI


def frame(size: int, color: tuple, label: str) -> bytes:
    img = Image.new("RGB", (size, size), color)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, size - 1, size - 1], outline="white", width=2)
    try:
        font = ImageFont.truetype("arialbd.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    d.text((size // 2, size // 2), label, font=font, fill="white", anchor="mm")
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

    api.set_key_image_stream(frame(64, (200, 30, 30), "64"), 7)
    api.set_key_image_stream(frame(72, (30, 160, 60), "72"), 9)
    api.set_key_image_stream(frame(80, (40, 80, 220), "80"), 3)
    api.refresh_screen()
    print("painted 64/72/80; holding 4 min", flush=True)

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
