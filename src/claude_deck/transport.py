"""Device access via the official Mirabox transport.dll (vendored).

All device I/O happens on a single worker thread: the DLL is not safe for
concurrent read/write from multiple threads. Other threads enqueue commands.
"""

import logging
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor" / "streamdock"
sys.path.insert(0, str(VENDOR_DIR))

from LibUSBHIDAPI import LibUSBHIDAPI  # noqa: E402

logger = logging.getLogger(__name__)

VID = 0x5548
PID = 0x1000

SOFTWARE_MODE = 2
HEARTBEAT_INTERVAL_S = 8.0

ROWS = 3
COLS = 5


def key_id_for(row: int, col: int) -> int:
    """Grid position (0-indexed, top-left origin) to device key id."""
    return (2 - row) * 5 + col + 1


def slot_to_key_id(slot: int) -> int:
    """Slot 1..15 in reading order (top-left first) to device key id."""
    row, col = divmod(slot - 1, COLS)
    return key_id_for(row, col)


class DeckTransport:
    def __init__(self) -> None:
        self._api: Optional[LibUSBHIDAPI] = None
        self._stop = threading.Event()
        self._cmd_q: queue.Queue = queue.Queue()
        self._worker: Optional[threading.Thread] = None

    @property
    def connected(self) -> bool:
        return self._api is not None

    def open(self) -> bool:
        devices = LibUSBHIDAPI.enumerate_devices(VID, PID)
        if not devices:
            return False
        api = LibUSBHIDAPI()
        api._device_info = LibUSBHIDAPI.create_device_info_from_dict(devices[0])
        if not api.open(devices[0]["path"].encode()):
            logger.error("Failed to open deck: %s", api.get_last_error_info())
            return False
        self._api = api
        api.change_mode(SOFTWARE_MODE)
        api.wakeup_screen()
        api.set_key_brightness(80)
        try:
            api.set_led_brightness(100)
        except Exception as exc:
            logger.debug("LED brightness init failed: %s", exc)
        api.clear_all_keys()
        api.refresh_screen()
        logger.info("Deck opened, firmware %s", api.get_firmware_version())
        return True

    def close(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=3)
        if self._api is not None:
            try:
                self._api.clear_all_keys()
                self._api.close()
            except Exception:
                pass
            self._api = None

    def set_brightness(self, percent: int) -> None:
        self._cmd_q.put(lambda api: api.set_key_brightness(percent))

    def paint_key(self, key_id: int, jpeg: bytes) -> None:
        def cmd(api: LibUSBHIDAPI) -> None:
            api.set_key_image_stream(jpeg, key_id)
            api.refresh_screen()

        self._cmd_q.put(cmd)

    def clear_key(self, key_id: int) -> None:
        def cmd(api: LibUSBHIDAPI) -> None:
            api.clear_key(key_id)
            api.refresh_screen()

        self._cmd_q.put(cmd)

    def set_led_strips(self, r: int, g: int, b: int, count: int = 2) -> None:
        self._cmd_q.put(lambda api: api.set_led_color(count, r, g, b))

    def set_led_each(self, colors: list) -> None:
        self._cmd_q.put(lambda api: api.set_single_led_color(colors))

    def start(
        self,
        on_key: Callable[[int, bool], None],
        on_reconnect: Optional[Callable[[], None]] = None,
    ) -> None:
        """Start the single device worker thread (commands + heartbeat + reads).

        Reconnects automatically if the device is unplugged and replugged.
        """

        def reopen() -> None:
            logger.warning("Deck lost, attempting reconnect...")
            try:
                self._api.close()
            except Exception:
                pass
            self._api = None
            while not self._stop.is_set():
                time.sleep(3)
                try:
                    if self.open():
                        logger.info("Deck reconnected")
                        if on_reconnect:
                            on_reconnect()
                        return
                except Exception:
                    pass

        def loop() -> None:
            last_beat = time.time()
            last_health = time.time()
            failures = 0
            while not self._stop.is_set():
                try:
                    while True:
                        cmd = self._cmd_q.get_nowait()
                        cmd(self._api)
                except queue.Empty:
                    pass
                except Exception as exc:
                    logger.error("Deck command failed: %s", exc)
                    failures += 1

                if time.time() - last_beat >= HEARTBEAT_INTERVAL_S:
                    try:
                        self._api.heartbeat()
                    except Exception as exc:
                        logger.error("Heartbeat failed: %s", exc)
                        failures += 1
                    last_beat = time.time()

                # The SDK wrapper swallows I/O errors (returns empty instead of
                # raising), so exceptions alone can't detect an unplugged deck.
                # Poll the firmware version as an active liveness check.
                if time.time() - last_health >= 12:
                    try:
                        alive = bool(self._api.get_firmware_version())
                    except Exception:
                        alive = False
                    if alive:
                        failures = 0
                    else:
                        logger.warning("Health check failed (deck unplugged?)")
                        failures += 3
                    last_health = time.time()

                if failures >= 3:
                    reopen()
                    failures = 0
                    last_beat = last_health = time.time()
                    continue

                try:
                    data = self._api.read(timeout_ms=200)
                except Exception as exc:
                    logger.error("Read failed: %s", exc)
                    failures += 1
                    time.sleep(1)
                    continue
                if not data or len(data) < 11 or bytes(data[0:3]) != b"ACK":
                    continue
                key_id, pressed = data[9], data[10] == 0x01
                logger.info("Key event: id=%s pressed=%s", key_id, pressed)
                try:
                    on_key(key_id, pressed)
                except Exception as exc:
                    logger.error("Key handler failed: %s", exc)

        self._worker = threading.Thread(target=loop, daemon=True)
        self._worker.start()
