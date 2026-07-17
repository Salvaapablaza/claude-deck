"""Test the device via the official Mirabox transport.dll wrapper.

Opens the device, prints firmware version, switches to software mode,
paints a test grid, then listens for key events for 5 minutes.
"""

import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "streamdock"))
sys.path.insert(0, str(ROOT / "src"))

from LibUSBHIDAPI import LibUSBHIDAPI

from claude_deck.render import render_key

STATES = ["idle", "running", "permission", "question", "error"]


def main() -> None:
    devices = LibUSBHIDAPI.enumerate_devices(0x5548, 0x1000)
    print("devices:", devices, flush=True)
    if not devices:
        print("no device found", flush=True)
        return

    api = LibUSBHIDAPI()
    info = LibUSBHIDAPI.create_device_info_from_dict(devices[0])
    api._device_info = info
    ok = api.open(devices[0]["path"].encode())
    print("open:", ok, flush=True)
    if not ok:
        print("last error:", api.get_last_error_info(), flush=True)
        return

    print("report id:", api.get_report_id(), flush=True)
    print(
        "report sizes in/out/feature:",
        api.input_report_size,
        api.output_report_size,
        api.feature_report_size,
        flush=True,
    )
    fw = api.get_firmware_version()
    print("firmware:", fw, flush=True)

    try:
        api.change_mode(2)
        print("change_mode(2) sent", flush=True)
    except Exception as exc:
        print("change_mode failed:", exc, flush=True)

    api.wakeup_screen()
    api.set_key_brightness(80)
    api.clear_all_keys()
    time.sleep(0.2)

    for row in range(3):
        for col in range(5):
            key_id = (2 - row) * 5 + col + 1
            jpeg = render_key(f"R{row}C{col}", STATES[col], sublabel=f"id {key_id}")
            api.set_key_image_stream(jpeg, key_id)
    api.refresh_screen()
    print("grid painted via SDK; press keys now (5 min)", flush=True)

    deadline = time.time() + 300
    last_beat = time.time()
    while time.time() < deadline:
        if time.time() - last_beat > 8:
            api.heartbeat()
            last_beat = time.time()
        data = api.read(timeout_ms=500)
        if data:
            head = " ".join(f"{b:02x}" for b in data[:16])
            print(f"event({len(data)}B): {head}", flush=True)

    api.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
