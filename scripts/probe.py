"""Hardware validation probe for the VSDinside 5x3 stream dock (5548:1000).

Steps:
1. Enumerate HID interfaces and print them.
2. Open, CONNECT handshake, wake screen, set brightness.
3. Paint raw key ids 1..15 with numbered colored tiles.
4. Listen for key presses and print raw reports (for grid calibration).
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from claude_deck.device import StreamDock, list_interfaces
from claude_deck.render import render_key

PALETTE = [
    "idle",
    "running",
    "permission",
    "question",
    "error",
    "done",
    "idle",
    "running",
    "permission",
    "question",
    "error",
    "done",
    "idle",
    "running",
    "permission",
]


def main() -> None:
    listen_seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    print("--- interfaces ---")
    for iface in list_interfaces():
        print(
            f"path={iface['path']} usage_page={iface.get('usage_page', 0):#06x} "
            f"usage={iface.get('usage', 0):#04x} product={iface.get('product_string')!r}"
        )

    deck = StreamDock()
    deck.open()
    print("--- opened, sending CONNECT + wake + brightness 80 ---")
    deck.send_connect()
    time.sleep(0.2)
    deck.wake_screen()
    deck.set_brightness(80)
    deck.clear_panel()
    time.sleep(0.3)

    print("--- painting raw key ids 1..15 ---")
    for key_id in range(1, 16):
        jpeg = render_key(str(key_id), PALETTE[key_id - 1], sublabel=f"id {key_id:#04x}")
        deck.set_key_jpeg(key_id, jpeg)
        print(f"key {key_id}: sent {len(jpeg)}B jpeg")
        time.sleep(0.05)

    print(f"--- listening for key presses for {listen_seconds}s, press some keys ---")
    deadline = time.time() + listen_seconds
    while time.time() < deadline:
        data = deck.read_raw(timeout_ms=500)
        if data:
            head = " ".join(f"{b:02x}" for b in data[:16])
            print(f"report: {head}  -> key={data[9]:#04x} state={data[10]}")

    deck.close()
    print("--- done ---")


if __name__ == "__main__":
    main()
