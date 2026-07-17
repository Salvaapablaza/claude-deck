"""HID driver for Mirabox/VSDinside Stream Dock family (VID 0x5548).

Protocol reference: bitfocus/companion-surface-mirabox-stream-dock and
rigor789/mirabox-streamdock-node (reverse-engineered).

Framing: every HID write is [0x00 report id] + payload zero-padded to
packet_size. Command payloads start with the "CRT\x00\x00" prefix followed by
a short ASCII-tagged command. Key images are JPEG (<= 10 KB), announced with
a BAT command carrying a big-endian 4-byte size and the key id, then streamed
raw in packet_size chunks.
"""

import logging
import threading
import time
from typing import Callable, Optional

import hid

logger = logging.getLogger(__name__)

DEFAULT_VID = 0x5548
DEFAULT_PID = 0x1000

CMD_PREFIX = bytes([0x43, 0x52, 0x54, 0x00, 0x00])

MAX_JPEG_SIZE = 10240


class StreamDockError(Exception):
    pass


def find_device_path(vid: int = DEFAULT_VID, pid: int = DEFAULT_PID) -> Optional[bytes]:
    """Return the HID path of the vendor-defined interface, if present."""
    candidates = [d for d in hid.enumerate(vid, pid)]
    if not candidates:
        return None
    for dev in candidates:
        if dev.get("usage_page", 0) >= 0xFF00:
            return dev["path"]
    return candidates[0]["path"]


def list_interfaces(vid: int = DEFAULT_VID, pid: int = DEFAULT_PID) -> list[dict]:
    return hid.enumerate(vid, pid)


class StreamDock:
    HEARTBEAT_INTERVAL_S = 8.0

    def __init__(
        self,
        vid: int = DEFAULT_VID,
        pid: int = DEFAULT_PID,
        packet_size: int = 1024,
    ):
        self.vid = vid
        self.pid = pid
        self.packet_size = packet_size
        self._dev: Optional[hid.device] = None
        self._write_lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def open(self) -> None:
        path = find_device_path(self.vid, self.pid)
        if path is None:
            raise StreamDockError(
                f"No HID device found for {self.vid:04x}:{self.pid:04x}"
            )
        self._dev = hid.device()
        self._dev.open_path(path)
        self._dev.set_nonblocking(1)
        logger.info("Opened stream dock at %s", path)

    def close(self) -> None:
        self._stop.set()
        if self._dev is not None:
            try:
                self._send_cmd(bytes([0x43, 0x4C, 0x45, 0, 0, 0x44, 0x43]))
            except Exception:
                pass
            self._dev.close()
            self._dev = None

    def _write_packet(self, payload: bytes) -> None:
        if self._dev is None:
            raise StreamDockError("Device not open")
        if len(payload) > self.packet_size:
            raise StreamDockError(
                f"Payload {len(payload)}B exceeds packet size {self.packet_size}B"
            )
        buf = b"\x00" + payload.ljust(self.packet_size, b"\x00")
        with self._write_lock:
            written = self._dev.write(buf)
        if written < 0:
            raise StreamDockError(f"HID write failed: {self._dev.error()}")

    def _send_cmd(self, cmd: bytes) -> None:
        self._write_packet(CMD_PREFIX + cmd)

    def send_connect(self) -> None:
        self._send_cmd(b"CONNECT")

    def wake_screen(self) -> None:
        self._send_cmd(b"DIS")

    def refresh(self) -> None:
        self._send_cmd(b"STP")

    def clear_panel(self) -> None:
        self._send_cmd(bytes([0x43, 0x4C, 0x45, 0, 0, 0, 0xFF]))

    def clear_key(self, key_id: int) -> None:
        self._send_cmd(bytes([0x43, 0x4C, 0x45, 0, 0, 0, key_id]))

    def set_brightness(self, percent: int) -> None:
        clamped = max(0, min(100, percent))
        value = round(((clamped / 100) ** 0.75) * 100)
        self._send_cmd(bytes([0x4C, 0x49, 0x47, 0, 0, value]))

    def set_key_jpeg(self, key_id: int, jpeg: bytes) -> None:
        if len(jpeg) > MAX_JPEG_SIZE:
            raise StreamDockError(
                f"JPEG is {len(jpeg)}B, exceeds device limit of {MAX_JPEG_SIZE}B"
            )
        size = len(jpeg)
        header = bytes(
            [
                0x42,
                0x41,
                0x54,
                (size >> 24) & 0xFF,
                (size >> 16) & 0xFF,
                (size >> 8) & 0xFF,
                size & 0xFF,
                key_id,
            ]
        )
        self._send_cmd(header)
        for offset in range(0, size, self.packet_size):
            self._write_packet(jpeg[offset : offset + self.packet_size])
        self.refresh()

    def start_heartbeat(self) -> None:
        def loop() -> None:
            while not self._stop.wait(self.HEARTBEAT_INTERVAL_S):
                try:
                    self.send_connect()
                except Exception as exc:
                    logger.error("Heartbeat failed: %s", exc)
                    return

        self._heartbeat_thread = threading.Thread(target=loop, daemon=True)
        self._heartbeat_thread.start()

    def start_reader(self, on_key: Callable[[int, bool], None]) -> None:
        """Invoke on_key(raw_key_id, pressed) for each key event."""

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    data = self._dev.read(1024)
                except Exception as exc:
                    logger.error("HID read failed: %s", exc)
                    return
                if not data:
                    time.sleep(0.02)
                    continue
                if len(data) < 11:
                    continue
                raw_key = data[9]
                pressed = data[10] != 0x00
                if raw_key:
                    on_key(raw_key, pressed)

        self._reader_thread = threading.Thread(target=loop, daemon=True)
        self._reader_thread.start()

    def read_raw(self, timeout_ms: int = 1000) -> list[int]:
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            data = self._dev.read(1024)
            if data:
                return data
            time.sleep(0.02)
        return []
