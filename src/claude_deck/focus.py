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
from typing import Optional

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

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


GENERIC_TERMINAL_NAMES = {
    "pwsh",
    "powershell",
    "bash",
    "sh",
    "zsh",
    "cmd",
    "node",
    "claude",
    "git bash",
    "python",
}


def resolve_terminal_name(ancestry: list[int]) -> Optional[str]:
    """Ask registered VS Code windows for the name of the terminal that owns
    one of these PIDs. Returns None for generic (un-renamed) shell names so
    the caller falls back to the repo name."""
    for window in registry.alive():
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{window['port']}/terminal-name",
                data=json.dumps({"pids": ancestry}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                name = json.loads(resp.read()).get("name")
        except Exception:
            continue
        if name and name.strip().lower() not in GENERIC_TERMINAL_NAMES:
            return name.strip()
    return None


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
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    if user32.GetForegroundWindow() == hwnd:
        return True

    # Attach to the foreground window's input thread so Windows allows the
    # focus change (no synthetic ALT keystrokes - those pop the menu bar).
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    this_thread = kernel32.GetCurrentThreadId()
    attached = False
    if fg_thread and fg_thread != this_thread:
        attached = bool(user32.AttachThreadInput(this_thread, fg_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(this_thread, fg_thread, False)
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
