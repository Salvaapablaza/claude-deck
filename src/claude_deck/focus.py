"""Focus the right VS Code window + terminal for a session.

Strategy:
1. Ask each registered VS Code window (bridge extension) whether it owns a
   terminal whose shell PID is in the session's process ancestry.
2. The window that says yes reveals the terminal; we then raise that OS
   window via win32 (matched by workspace name in the window title).
3. Fallback: `code <cwd>` which focuses/opens a window for the project.
"""

import ctypes
import ctypes.wintypes as wt
import json
import logging
import subprocess
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32

WINDOW_TTL_S = 60


class WindowRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[int, dict] = {}

    def register(self, info: dict) -> None:
        port = info.get("port")
        if not port:
            return
        info["last_seen"] = time.time()
        with self._lock:
            self._windows[port] = info

    def alive(self) -> list[dict]:
        now = time.time()
        with self._lock:
            return [
                w for w in self._windows.values() if now - w["last_seen"] < WINDOW_TTL_S
            ]


registry = WindowRegistry()


def _ask_window(port: int, pids: list[int]) -> bool:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/focus",
            data=json.dumps({"pids": pids}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read()).get("found", False)
    except Exception as exc:
        logger.debug("Window on port %s unreachable: %s", port, exc)
        return False


def _raise_window_by_title(fragment: str) -> bool:
    """Bring the first visible window whose title contains fragment to front."""
    fragment_lower = fragment.lower()
    found_hwnd = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def enum_cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.lower()
        if fragment_lower in title and "visual studio code" in title:
            found_hwnd.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_cb, 0)
    if not found_hwnd:
        return False

    hwnd = found_hwnd[0]
    SW_RESTORE = 9
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    return True


def send_digit(digit: int) -> None:
    """Type a digit key (1-9) into the currently focused window."""
    KEYEVENTF_KEYUP = 0x0002
    vk = 0x30 + digit
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def focus_and_answer(cwd: str, ancestry: list[int], digit: int) -> None:
    """Focus the session's terminal, then type the option number."""
    focus_session(cwd, ancestry)
    time.sleep(0.9)
    send_digit(digit)
    logger.info("Answered with option %s", digit)


def focus_session(cwd: str, ancestry: list[int]) -> None:
    if ancestry:
        for window in registry.alive():
            if _ask_window(window["port"], ancestry):
                name = window.get("name", "")
                raised = _raise_window_by_title(name) if name else False
                logger.info(
                    "Focused terminal via window %r (os-raise=%s)", name, raised
                )
                return

    logger.info("No bridge window matched, falling back to `code %s`", cwd)
    try:
        subprocess.Popen(
            ["cmd", "/c", "code", cwd],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as exc:
        logger.error("Focus fallback failed: %s", exc)
