"""Calibration round 2: find exact native key resolution.

Top row: border frames at 85/88/90/92/94. Middle+bottom rows: solid dark
gray so any overflow from the row above is clearly visible as a colored strip.
Also probes the LED strips with different APIs, one every 5 seconds.
"""

import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "streamdock"))

from PIL import Image, ImageDraw, ImageFont

from LibUSBHIDAPI import LibUSBHIDAPI

SIZES = [85, 88, 90, 92, 94]
COLORS = [(31, 111, 235), (46, 160, 67), (210, 153, 34), (163, 113, 247), (218, 54, 51)]


def frame(size: int, color: tuple, label: str) -> bytes:
    img = Image.new("RGB", (size, size), color)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, size - 1, size - 1], outline="white", width=2)
    try:
        font = ImageFont.truetype("arialbd.ttf", 20)
    except OSError:
        font = ImageFont.load_default()
    d.text((size // 2, size // 2), label, font=font, fill="white", anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def solid(size: int, color: tuple) -> bytes:
    img = Image.new("RGB", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def main() -> None:
    devices = LibUSBHIDAPI.enumerate_devices(0x5548, 0x1000)
    if not devices:
        print("device not found (is the daemon still running?)", flush=True)
        return
    api = LibUSBHIDAPI()
    api._device_info = LibUSBHIDAPI.create_device_info_from_dict(devices[0])
    if not api.open(devices[0]["path"].encode()):
        print("open failed:", api.get_last_error_info(), flush=True)
        return
    api.change_mode(2)
    api.wakeup_screen()
    api.set_key_brightness(80)
    api.clear_all_keys()
    time.sleep(0.3)

    gray = solid(96, (55, 60, 70))
    for key_id in list(range(1, 11)):
        api.set_key_image_stream(gray, key_id)
    for col, (size, color) in enumerate(zip(SIZES, COLORS)):
        api.set_key_image_stream(frame(size, color, str(size)), 11 + col)
    api.refresh_screen()
    print("painted: top row frames 85/88/90/92/94, rest gray", flush=True)

    led_tests = [
        ("set_led_brightness(100)", lambda: api.set_led_brightness(100)),
        ("set_led_color(2, amber)", lambda: api.set_led_color(2, 255, 140, 0)),
        ("set_led_color(8, amber)", lambda: api.set_led_color(8, 255, 140, 0)),
        (
            "set_single_led_color 8x red",
            lambda: api.set_single_led_color([(255, 0, 0)] * 8),
        ),
        ("reset_led_color()", lambda: api.reset_led_color()),
        ("set_led_color(2, blue)", lambda: api.set_led_color(2, 0, 80, 255)),
    ]
    last_beat = time.time()
    for name, fn in led_tests:
        print(f"LED test: {name}", flush=True)
        try:
            fn()
        except Exception as exc:
            print(f"  failed: {exc}", flush=True)
        for _ in range(10):
            if time.time() - last_beat > 8:
                api.heartbeat()
                last_beat = time.time()
            api.read(timeout_ms=100)
            time.sleep(0.4)

    print("holding image for 90s so you can photograph...", flush=True)
    deadline = time.time() + 90
    while time.time() < deadline:
        if time.time() - last_beat > 8:
            api.heartbeat()
            last_beat = time.time()
        api.read(timeout_ms=200)

    api.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
