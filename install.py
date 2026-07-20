"""One-shot installer for claude-deck.

Creates the venv, installs dependencies, registers Claude Code hooks,
sideloads the VS Code bridge extension, and adds the login startup script.

Usage: python install.py
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOOK_EVENTS = [
    "SessionStart",
    "UserPromptSubmit",
    "PostToolUse",
    "Notification",
    "Stop",
    "SessionEnd",
]


def step(msg: str) -> None:
    print(f"\n=== {msg} ===")


def create_venv() -> Path:
    step("Python environment")
    venv = ROOT / "venv"
    if not venv.exists():
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
    pip = venv / "Scripts" / "pip.exe"
    subprocess.check_call(
        [str(pip), "install", "--quiet", "hidapi", "pillow", "fastapi", "uvicorn"]
    )
    print("venv ready")
    return venv


def install_hooks() -> None:
    step("Claude Code hooks")
    settings_path = Path.home() / ".claude" / "settings.json"
    settings = (
        json.loads(settings_path.read_text()) if settings_path.exists() else {}
    )
    hooks = settings.setdefault("hooks", {})
    hook_cmd = f"python {(ROOT / 'hooks' / 'claude_deck_hook.py').as_posix()}"
    entry = {"hooks": [{"type": "command", "command": hook_cmd, "async": True}]}
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if not any(
            "claude_deck_hook" in h.get("command", "")
            for e in entries
            for h in e.get("hooks", [])
        ):
            entries.append(json.loads(json.dumps(entry)))
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"hooks registered in {settings_path}")


def install_extension() -> None:
    step("VS Code bridge extension")
    src = ROOT / "vscode-extension" / "claude-deck-bridge"
    dest = Path.home() / ".vscode" / "extensions" / "claude-deck.claude-deck-bridge-0.0.1"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "extension.js"):
        shutil.copy2(src / name, dest / name)
    print(f"sideloaded to {dest} (restart VS Code to load)")


def install_startup() -> None:
    step("Login autostart")
    vbs = ROOT / "start_deck_hidden.vbs"
    vbs.write_text(
        "' Launch the claude-deck daemon without a console window\n"
        'Set shell = CreateObject("WScript.Shell")\n'
        f'shell.CurrentDirectory = "{ROOT}"\n'
        'shell.Environment("PROCESS")("PYTHONPATH") = "src"\n'
        f'shell.Run """{ROOT / "venv" / "Scripts" / "pythonw.exe"}"" -m claude_deck.app", 0, False\n'
    )
    startup = (
        Path(os.environ["APPDATA"])
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )
    shutil.copy2(vbs, startup / "claude-deck.vbs")
    print(f"startup script at {startup / 'claude-deck.vbs'}")


def main() -> None:
    if os.name != "nt":
        sys.exit("Windows only (the vendored transport.dll is a Windows binary).")
    create_venv()
    install_hooks()
    install_extension()
    install_startup()
    step("Done")
    print("Start now with start_deck.bat, or log off/on for autostart.")
    print("Plug in the deck; sessions appear as you interact with Claude Code.")


if __name__ == "__main__":
    main()
