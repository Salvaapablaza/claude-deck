"""Calibration round 3.

Screen: paints key R1C2 (display id 8, middle of the deck) with numbered
8-pixel color bands (0..11), encoded 4:4:4 so nothing is padded. The last
band visible on the key itself = panel height / 8 - 1. Bands that appear on
the key BELOW reveal the overflow.

LEDs: labeled tests, 6 seconds apart, painted as text on key R0C0 so the
user always knows which test is active.
"""

import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "streamdock"))

from PIL import Image, ImageDraw, ImageFont

from LibUSBHIDAPI import LibUSBHIDAPI

BANDS = [
    ("0", (255, 0, 0)),
    ("1", (255, 128, 0)),
    ("2", (255, 255, 0)),
    ("3", (0, 200, 0)),
    ("4", (0, 255, 255)),
    ("5", (0, 80, 255)),
    ("6", (150, 0, 255)),
    ("7", (255, 0, 255)),
    ("8", (255, 255, 255)),
    ("9", (128, 128, 128)),
    ("10", (150, 75, 0)),
    ("11", (0, 0, 0)),
]


def band_image() -> bytes:
    img = Image.new("RGB", (96, 96))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arialbd.ttf", 8)
    except OSError:
        font = ImageFont.load_default()
    for i, (label, color) in enumerate(BANDS):
        y0 = i * 8
        d.rectangle([0, y0, 95, y0 + 7], fill=color)
        text_fill = "white" if sum(color) < 380 else "black"
        d.text((4, y0 + 4), label, font=font, fill=text_fill, anchor="lm")
        d.text((88, y0 + 4), label, font=font, fill=text_fill, anchor="rm")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95, subsampling=0)
    return buf.getvalue()


def text_tile(text: str) -> bytes:
    img = Image.new("RGB", (96, 96), (20, 24, 32))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arialbd.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
    lines = text.split("\n")
    y = 30
    for line in lines:
        d.text((40, y), line, font=font, fill="white", anchor="mm")
        y += 18
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
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

    api.set_key_image_stream(band_image(), 8)
    api.refresh_screen()
    print("band image on middle key (R1C2)", flush=True)

    last_beat = time.time()

    def wait(seconds: float) -> None:
        nonlocal last_beat
        end = time.time() + seconds
        while time.time() < end:
            if time.time() - last_beat > 8:
                api.heartbeat()
                last_beat = time.time()
            api.read(timeout_ms=100)

    led_tests = [
        ("LED A\nstrips\nred", lambda: api.set_led_color(2, 255, 0, 0)),
        ("LED B\nstrips\ngreen", lambda: api.set_led_color(2, 0, 255, 0)),
        (
            "LED C\nbody bar\nred fixed",
            lambda: api.set_keyboard_rgb_backlight(255, 0, 0),
        ),
        (
            "LED D\nbody fx 0",
            lambda: api.set_keyboard_lighting_effects(0),
        ),
        (
            "LED E\nbody fx 1",
            lambda: api.set_keyboard_lighting_effects(1),
        ),
        (
            "LED F\nbody bar\nblue",
            lambda: api.set_keyboard_rgb_backlight(0, 0, 255),
        ),
        ("LED G\nstrips\noff", lambda: api.set_led_color(2, 0, 0, 0)),
    ]

    for name, fn in led_tests:
        api.set_key_image_stream(text_tile(name), 11)
        api.refresh_screen()
        print("running:", name.replace("\n", " "), flush=True)
        try:
            fn()
        except Exception as exc:
            print("  failed:", exc, flush=True)
        wait(6)

    api.set_key_image_stream(text_tile("tests\ndone"), 11)
    api.refresh_screen()
    print("holding 4 minutes for observation...", flush=True)
    wait(240)
    api.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
