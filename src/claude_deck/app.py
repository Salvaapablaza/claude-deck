"""Claude Deck daemon: HTTP broker + deck controller."""

import logging
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request

from .actions import compact_action, design_action, review_action
from .focus import focus_and_answer, focus_session, registry, resolve_terminal_name
from .render import render_action, render_key
from .state import ACTION_KEYS, SessionStore
from .transport import DeckTransport, slot_to_key_id

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8642

ATTENTION_STATES = {"permission", "question", "error"}

store = SessionStore()
deck = DeckTransport()
app = FastAPI(title="claude-deck")


@app.post("/hook")
async def hook(request: Request) -> dict:
    payload = await request.json()
    event = payload.get("hook_event_name", "")
    session_id = payload.get("session_id", "")
    cwd = payload.get("cwd", "")
    message = payload.get("message", "")
    ancestry = payload.get("ancestry") or []
    ancestry_names = payload.get("ancestry_names") or []
    logger.info(
        "HOOK event=%s sid=%s cwd=%s hosts=%s",
        event,
        session_id[:8],
        cwd,
        ancestry_names,
    )
    if session_id and event:
        store.handle_event(session_id, cwd, event, message, ancestry, ancestry_names)
    return {"ok": True}


@app.post("/register-window")
async def register_window(request: Request) -> dict:
    registry.register(await request.json())
    return {"ok": True}


@app.post("/refresh")
def refresh() -> dict:
    """Force a full repaint (e.g. after the device was cleared on resume)."""
    store.mark_all_dirty()
    return {"ok": True}


@app.post("/led")
async def led(request: Request) -> dict:
    p = await request.json()
    deck.set_led_strips(
        p.get("r", 0), p.get("g", 0), p.get("b", 0), p.get("count", 2)
    )
    return {"ok": True}


@app.post("/led-each")
async def led_each(request: Request) -> dict:
    p = await request.json()
    deck.set_led_each([tuple(c) for c in p.get("colors", [])])
    return {"ok": True}


@app.get("/status")
def status() -> dict:
    return {
        "connected": deck.connected,
        "sessions": [
            {
                "slot": s.slot,
                "label": s.label,
                "state": s.state,
                "cwd": s.cwd,
                "session_id": s.session_id,
                "age_s": round(time.time() - s.last_event),
            }
            for s in sorted(store.snapshot(), key=lambda s: s.slot)
        ],
        "windows": [
            {"port": w["port"], "name": w.get("name"), "folders": w.get("folders")}
            for w in registry.alive()
        ],
    }


ROUND_BUTTONS = {37: 1, 48: 2, 49: 3}
ACTION_HANDLERS = {5: design_action, 10: review_action, 15: compact_action}
ACTION_LABELS = {5: "Design", 10: "Review", 15: "Compact"}
ACTION_ICONS = {5: "design", 10: "review", 15: "compact"}
ACTION_DEBOUNCE_S = 1.5
_last_action_ts: dict[int, float] = {}


def on_key(key_id: int, pressed: bool) -> None:
    """Input key ids arrive in reading order (top-left = 1), matching slots.

    Right column (5/10/15) = macro actions. Round buttons (37/48/49) answer
    the pending prompt of the most recently waiting session with option 1/2/3.
    """
    if not pressed:
        return

    if key_id in ACTION_HANDLERS:
        now = time.time()
        if now - _last_action_ts.get(key_id, 0) < ACTION_DEBOUNCE_S:
            return
        _last_action_ts[key_id] = now
        logger.info("Action key %s -> %s", key_id, ACTION_LABELS[key_id])
        threading.Thread(target=ACTION_HANDLERS[key_id], daemon=True).start()
        return

    if key_id in ROUND_BUTTONS:
        digit = ROUND_BUTTONS[key_id]
        session = store.attention_session()
        if session is None:
            logger.info("Round button %s pressed but no session is waiting", digit)
            return
        logger.info(
            "Round button %s -> answering %s with option %s",
            digit,
            session.label,
            digit,
        )
        threading.Thread(
            target=focus_and_answer,
            args=(session.cwd, session.ancestry, digit),
            daemon=True,
        ).start()
        return

    session = store.session_for_slot(key_id)
    if session is None or not session.cwd:
        return
    logger.info("Key %s -> focusing %s", key_id, session.cwd)
    threading.Thread(
        target=focus_session, args=(session.cwd, session.ancestry), daemon=True
    ).start()


def repaint_loop() -> None:
    last_sweep = time.time()
    last_tick = time.time()
    while True:
        time.sleep(0.3)
        now = time.time()
        if now - last_tick > 10:
            logger.info(
                "Wall-clock gap %.0fs (resume from sleep?), repainting all",
                now - last_tick,
            )
            store.mark_all_dirty()
        last_tick = now
        if not deck.connected:
            continue
        if now - last_sweep > 600:
            store.sweep_stale()
            last_sweep = now
        dirty = store.pop_dirty()
        if not dirty:
            continue
        sessions = {s.slot: s for s in store.snapshot()}
        for slot in sorted(dirty):
            if slot in ACTION_KEYS:
                jpeg = render_action(ACTION_ICONS[slot], ACTION_LABELS.get(slot, ""))
            else:
                session = sessions.get(slot)
                if session:
                    jpeg = render_key(session.label, session.state, str(slot))
                else:
                    jpeg = render_key("", "empty")
            try:
                deck.paint_key(slot_to_key_id(slot), jpeg)
            except Exception as exc:
                logger.error("Paint slot %s failed: %s", slot, exc)

        any_attention = any(s.state in ATTENTION_STATES for s in sessions.values())
        if any_attention:
            deck.set_led_strips(255, 140, 0, count=64)
        else:
            deck.set_led_strips(15, 40, 120, count=64)


def label_refresh_loop() -> None:
    """Poll the VS Code bridges for each session's terminal name, so renaming
    a terminal tab updates its tile within a few seconds."""
    while True:
        time.sleep(5)
        for session in store.snapshot():
            if not session.ancestry:
                continue
            name = resolve_terminal_name(session.ancestry)
            if name:
                store.update_term_label(session.session_id, name)


def start_deck() -> None:
    while not deck.open():
        logger.warning("Deck not found, retrying in 5s...")
        time.sleep(5)
    deck.start(on_key, on_reconnect=store.mark_all_dirty)
    store.mark_all_dirty()
    threading.Thread(target=repaint_loop, daemon=True).start()
    threading.Thread(target=label_refresh_loop, daemon=True).start()


def main() -> None:
    import os
    import sys

    handlers: list[logging.Handler] = []
    log_dir = Path(os.environ.get("LOCALAPPDATA", ".")) / "claude-deck"
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers.append(logging.FileHandler(log_dir / "deck.log", encoding="utf-8"))
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
    )

    if sys.stderr is None:
        sys.stderr = open(log_dir / "stderr.log", "a", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = open(log_dir / "stdout.log", "a", encoding="utf-8")

    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((HOST, PORT))
    except OSError:
        logger.error("Port %s already in use - another daemon is running, exiting", PORT)
        return
    finally:
        probe.close()

    threading.Thread(target=start_deck, daemon=True).start()

    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
