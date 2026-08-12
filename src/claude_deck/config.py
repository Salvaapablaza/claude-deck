"""User-tunable config (executable path, skill commands, terminal names).

Loaded from config.json next to the package root if present; otherwise
defaults are used. Env vars override individual values.
"""

import json
import os
from pathlib import Path

_DEFAULTS = {
    "claude_command": "claude",
    # Slash commands the Design/Review actions send. Left blank on purpose —
    # set your own (project/personal) skills in config.json, e.g.
    # {"design_command": "/my-design-skill", "review_command": "/my-review-skill"}
    "design_command": "",
    "review_command": "",
    "design_terminal_name": "Claude — Design",
    "review_terminal_name": "Claude — Review",
    "compact_command": "/compact",
    "ready_timeout_s": 25,
    # Claude with heavy plugins takes several seconds to finish loading after
    # its process appears; inject too early and the Enter gets dropped.
    "ready_settle_s": 2.5,
    "submit_delay_s": 0.6,
}

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"


def load() -> dict:
    cfg = dict(_DEFAULTS)
    if _CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(_CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    for key in cfg:
        env = os.environ.get(f"CLAUDE_DECK_{key.upper()}")
        if env is not None:
            cfg[key] = env
    return cfg
