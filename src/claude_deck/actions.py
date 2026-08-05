"""Stream Deck actions: Design/Review from clipboard, Compact active session.

Orchestrated by the daemon. Uses the VS Code bridge for terminal I/O and the
Windows process tree to detect when Claude is ready (no blind fixed delay).
"""

import json
import logging
import time
import urllib.request

from . import config, procutil
from .focus import registry

logger = logging.getLogger(__name__)

CLAUDE_PROC_NAMES = ("claude", "node")


def _read_clipboard() -> str:
    try:
        import pyperclip

        return pyperclip.paste() or ""
    except Exception as exc:
        logger.error("Clipboard read failed: %s", exc)
        return ""


def _post(port: int, path: str, payload: dict) -> dict | None:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.error("POST %s failed: %s", path, exc)
        return None


def _get(port: int, path: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=4) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.error("GET %s failed: %s", path, exc)
        return None


def _ping(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1) as resp:
            return resp.read() == b"ok"
    except Exception:
        return False


def _pick_window() -> dict | None:
    """Return the first alive AND reachable window (dead ports are skipped)."""
    for win in registry.alive():
        if _ping(win["port"]):
            return win
    return None


def _notify(port: int | None, level: str, message: str) -> None:
    if port is None:
        win = _pick_window()
        port = win["port"] if win else None
    if port is not None:
        _post(port, "/notify", {"level": level, "message": message})
    logger.info("NOTIFY [%s] %s", level, message)


def _wait_ready(shell_pid: int, cfg: dict) -> bool:
    deadline = time.time() + cfg["ready_timeout_s"]
    while time.time() < deadline:
        if procutil.has_descendant_named(shell_pid, CLAUDE_PROC_NAMES):
            time.sleep(cfg["ready_settle_s"])
            return True
        time.sleep(0.4)
    return False


def _clipboard_action(command: str, terminal_name: str) -> None:
    cfg = config.load()
    if not command.strip():
        _notify(None, "error", "Comando no configurado — definilo en config.json.")
        return
    clip = _read_clipboard().strip()
    if not clip:
        _notify(None, "error", "Clipboard vacío — nada que enviar.")
        return

    win = _pick_window()
    if win is None:
        logger.error("No VS Code window registered; cannot create terminal")
        return
    port = win["port"]

    created = _post(port, "/create-terminal", {"name": terminal_name})
    if not created or created.get("processId") is None:
        _notify(port, "error", "No se pudo crear la terminal.")
        return
    shell_pid = created["processId"]
    term_id = created["id"]
    _notify(port, "info", f"Terminal '{terminal_name}' creada. Iniciando Claude…")

    _post(port, "/send-terminal", {"target": term_id, "text": cfg["claude_command"], "submit": True})

    if not _wait_ready(shell_pid, cfg):
        _notify(port, "error", "Claude no estuvo listo a tiempo.")
        return

    _post(port, "/send-terminal", {"target": term_id, "text": command + " "})
    _post(port, "/send-terminal", {"target": term_id, "text": clip, "bracketed": "\n" in clip})
    time.sleep(0.3)
    _post(port, "/send-terminal", {"target": term_id, "submit": True})
    _notify(port, "info", f"Enviado: {command}")


def design_action() -> None:
    cfg = config.load()
    _clipboard_action(cfg["design_command"], cfg["design_terminal_name"])


def review_action() -> None:
    cfg = config.load()
    _clipboard_action(cfg["review_command"], cfg["review_terminal_name"])


def compact_action() -> None:
    cfg = config.load()
    for win in registry.alive():
        port = win["port"]
        if not _ping(port):
            continue
        active = _get(port, "/active-terminal")
        if not active or not active.get("processId"):
            continue
        if not procutil.has_descendant_named(active["processId"], CLAUDE_PROC_NAMES):
            continue
        _post(port, "/send-terminal", {"target": "active", "text": cfg["compact_command"], "submit": True})
        _notify(port, "info", f"{cfg['compact_command']} enviado a '{active.get('name')}'.")
        return
    _notify(None, "error", "La terminal activa no tiene una sesión de Claude.")
