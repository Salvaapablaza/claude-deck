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


TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>claude-deck daemon - self-healing autostart</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId></LogonTrigger>
    <SessionStateChangeTrigger>
      <Enabled>true</Enabled>
      <UserId>{user}</UserId>
      <StateChange>SessionUnlock</StateChange>
    </SessionStateChangeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{pythonw}</Command>
      <Arguments>run_daemon.py</Arguments>
      <WorkingDirectory>{root}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def install_startup() -> None:
    step("Autostart (self-healing scheduled task)")
    user = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"
    pythonw = ROOT / "venv" / "Scripts" / "pythonw.exe"
    xml = TASK_XML.format(user=user, pythonw=pythonw, root=ROOT)
    xml_path = ROOT / "claude-deck-task.xml"
    xml_path.write_text(xml, encoding="utf-16")
    subprocess.check_call(
        ["schtasks", "/create", "/tn", "claude-deck", "/xml", str(xml_path), "/f"]
    )
    # Retire the old login-only startup shortcut if a previous install left one.
    old = (
        Path(os.environ["APPDATA"])
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        / "claude-deck.vbs"
    )
    if old.exists():
        old.unlink()
    print("scheduled task 'claude-deck' registered (logon + unlock, restart on fail)")


def main() -> None:
    if os.name != "nt":
        sys.exit("Windows only (the vendored transport.dll is a Windows binary).")
    create_venv()
    install_hooks()
    install_extension()
    install_startup()
    subprocess.run(["schtasks", "/run", "/tn", "claude-deck"], check=False)
    step("Done")
    print("Daemon started via the scheduled task (also runs on logon + unlock).")
    print("Plug in the deck; sessions appear as you interact with Claude Code.")


if __name__ == "__main__":
    main()
