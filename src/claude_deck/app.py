"""Claude Deck daemon: HTTP broker + deck controller."""

import logging
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request

from .focus import focus_and_answer, focus_session, registry
from .render import render_key
from .state import SessionStore
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
    if session_id and event:
        store.handle_event(session_id, cwd, event, message, ancestry, ancestry_names)
    return {"ok": True}


@app.post("/register-window")
async def register_window(request: Request) -> dict:
    registry.register(await request.json())
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
    }


ROUND_BUTTONS = {37: 1, 48: 2, 49: 3}


def on_key(key_id: int, pressed: bool) -> None:
    """Input key ids arrive in reading order (top-left = 1), matching slots.

    The 3 round buttons (ids 37/48/49) answer the pending prompt of the most
    recently active waiting session with option 1/2/3.
    """
    if not pressed:
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
    while True:
        time.sleep(0.3)
        if not deck.connected:
            continue
        if time.time() - last_sweep > 600:
            store.sweep_stale()
            last_sweep = time.time()
        dirty = store.pop_dirty()
        if not dirty:
            continue
        sessions = {s.slot: s for s in store.snapshot()}
        for slot in sorted(dirty):
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


def start_deck() -> None:
    while not deck.open():
        logger.warning("Deck not found, retrying in 5s...")
        time.sleep(5)
    deck.start(on_key, on_reconnect=store.mark_all_dirty)
    store.mark_all_dirty()
    threading.Thread(target=repaint_loop, daemon=True).start()


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
