"""Read-only diagnostic: open the vendor interface, send nothing (optionally
just CONNECT), and poll for key-press reports. Prints every raw report."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import hid

from claude_deck.device import find_device_path

send_connect = "--connect" in sys.argv
listen_seconds = 120

path = find_device_path()
print("opening", path)
dev = hid.device()
dev.open_path(path)
dev.set_nonblocking(1)

if send_connect:
    payload = b"CRT\x00\x00CONNECT"
    buf = b"\x00" + payload.ljust(1024, b"\x00")
    print("CONNECT write returned", dev.write(buf))

print(f"polling for {listen_seconds}s - press keys on the deck now")
deadline = time.time() + listen_seconds
errors = 0
while time.time() < deadline:
    try:
        data = dev.read(1024)
    except OSError as exc:
        errors += 1
        print(f"read error #{errors}: {exc}; reopening...")
        try:
            dev.close()
        except Exception:
            pass
        time.sleep(0.5)
        try:
            dev = hid.device()
            dev.open_path(find_device_path())
            dev.set_nonblocking(1)
            print("reopened ok")
        except Exception as exc2:
            print("reopen failed:", exc2)
            time.sleep(1.0)
        if errors > 5:
            print("too many errors, giving up")
            break
        continue
    if data:
        head = " ".join(f"{b:02x}" for b in data[:16])
        print(f"report({len(data)}B): {head}")
    else:
        time.sleep(0.02)

dev.close()
print("done")
