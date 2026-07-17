"""Live interactive test: paint the grid with correct row/col labels, keep it
alive via heartbeat, and log every key press until the window ends.

Grid mapping (validated by photo): key_id = (2 - row) * 5 + col + 1
  top row    -> ids 11..15
  middle row -> ids  6..10
  bottom row -> ids  1..5
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from claude_deck.device import StreamDock
from claude_deck.render import render_key

LISTEN_SECONDS = 300

STATES = ["idle", "running", "permission", "question", "error"]


def key_id_for(row: int, col: int) -> int:
    return (2 - row) * 5 + col + 1


def main() -> None:
    deck = StreamDock()
    deck.open()
    deck.send_connect()
    time.sleep(0.2)
    deck.wake_screen()
    deck.set_brightness(80)
    deck.clear_panel()
    time.sleep(0.2)

    for row in range(3):
        for col in range(5):
            key_id = key_id_for(row, col)
            jpeg = render_key(
                f"R{row}C{col}", STATES[col], sublabel=f"id {key_id}"
            )
            deck.set_key_jpeg(key_id, jpeg)

    print("grid painted; heartbeat on; press keys now (5 min window)", flush=True)
    deck.start_heartbeat()

    deadline = time.time() + LISTEN_SECONDS
    while time.time() < deadline:
        data = deck.read_raw(timeout_ms=500)
        if data:
            head = " ".join(f"{b:02x}" for b in data[:16])
            key = data[9] if len(data) > 10 else -1
            state = data[10] if len(data) > 10 else -1
            row, col = divmod(key - 1, 5)
            print(
                f"report: {head} -> id={key} ({'down' if state else 'up'}) "
                f"= row {2 - row} col {col}",
                flush=True,
            )

    deck.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
