# claude-deck

Physical dashboard for Claude Code sessions on a VSDinside 15-key Stream Dock
(5x3, VID `0x5548` PID `0x1000`, firmware `V3.VSDM18.xx`). No VSD Craft or
vendor software needed — the daemon drives the device directly over HID.

Each Claude Code CLI session claims a tile. Tile color = session state.
Pressing a tile focuses the exact VS Code terminal hosting that session.

## Install (Windows)

```
git clone <this repo>
cd claude-deck
python install.py
```

Then restart VS Code (loads the bridge extension) and run `start_deck.bat`
(or just log off/on — it autostarts). Requires Python 3.11+ and VS Code's
`code` CLI on PATH. Should work on other Mirabox/VSDinside "Stream Dock"
variants with minor tweaks (see key size / id mapping notes below).

## States

| Color | State | Trigger |
|-------|-------|---------|
| Green | idle / finished | `SessionStart`, `Stop` |
| Blue | running | `UserPromptSubmit` |
| Gold | needs permission | `Notification` (permission request) |
| Purple | waiting for input | `Notification` (other) |
| Dark | free slot | — |

The two LED strips under the keys turn amber when any session needs attention.

State returns to blue (running) on `PostToolUse`, so a tile that went gold for
a permission prompt flips back to blue as soon as work resumes after you
approve — it no longer stays stuck on the prompt color.

## Tile labels

A tile shows the session's **VS Code terminal tab name** if you've renamed it
(right-click the terminal tab → Rename, or the tab dropdown). Otherwise it
falls back to the repo folder name. Renames are picked up automatically within
~5s via the bridge extension. Generic shell names (pwsh, bash, node, claude…)
are ignored so an un-renamed terminal still shows the repo.

## Architecture

```
Claude Code hooks (all sessions)
        │ POST http://127.0.0.1:8642/hook   (hooks/claude_deck_hook.py)
        ▼
FastAPI broker + session store (src/claude_deck/app.py, state.py)
        │ dirty-slot repaints, single device worker thread
        ▼
Official Mirabox transport.dll (vendor/streamdock/)  ── USB HID ──► deck
```

Device protocol notes (hard-won):

- Official SDK: [MiraboxSpace/StreamDock-Device-SDK](https://github.com/MiraboxSpace/StreamDock-Device-SDK).
  The vendored `transport.dll` + `LibUSBHIDAPI.py` come from there.
- `change_mode(2)` (software mode) is REQUIRED or the device never reports
  key presses.
- Key images: **64x64** JPEG (calibrated with band tests; anything larger
  bleeds into neighboring keys because JPEGs decode in 8/16px blocks),
  <= 10 KB, no rotation, encode with subsampling=0 for crisp text.
- Display key ids: bottom-left = 1 ... top-right = 15 (rows bottom-up).
- Input key ids: top-left = 1 ... bottom-right = 15 (reading order).
  They are NOT the same mapping.
- The DLL is not thread-safe: all I/O (paint, heartbeat, read) must happen
  on one thread. Heartbeat every 8s or the device reverts to its boot logo.
- Front LED strips: `set_led_color(2, r, g, b)` works. The body light bar
  (`set_keyboard_rgb_backlight`/effects) only partially responds — unused.

## Run

```
start_deck.bat            # console
start_deck_hidden.vbs     # no console (put a shortcut in shell:startup)
```

Debug: `GET http://127.0.0.1:8642/status`

Logs: the venv uses Microsoft-Store Python, whose MSIX virtualization
redirects `%LOCALAPPDATA%\claude-deck\deck.log` to
`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\Local\claude-deck\deck.log`.

## Hooks

Installed in `~/.claude/settings.json`: SessionStart, UserPromptSubmit,
Notification, Stop, SessionEnd → `hooks/claude_deck_hook.py` (stdlib-only,
fire-and-forget, 2s timeout).

## Per-terminal focus

`vscode-extension/claude-deck-bridge/` (sideloaded into
`~/.vscode/extensions/claude-deck.claude-deck-bridge-0.0.1` by `install.py`)
runs a local HTTP endpoint per VS Code window and registers with the daemon. Hook events carry
the hook process's ancestor PIDs; on key press the daemon asks each window
whether one of its terminals matches (`terminal.processId` vs ancestry),
the owning window reveals that exact terminal, and the daemon raises the OS
window via win32. Fallback: `code <cwd>`.

## Round buttons

The 3 round buttons below the screen (input ids 37/48/49) answer the pending
prompt of the most recently active waiting (gold/purple) session: they focus
its terminal and type option `1`, `2`, or `3` — works for both permission
prompts and numbered questions.

## Known limitations / next steps

- Sessions in the Claude Code desktop app are intentionally not shown
  (only sessions whose ancestry includes Code.exe / Windows Terminal).
- Slots are in-memory: a daemon restart forgets sessions until their next
  hook event repopulates them.
- The body light bar is untamed (half-lit after our probes; power-cycle the
  deck to restore its default effect).

## Disclaimer

This is an independent hobby project, not affiliated with or endorsed by
VSDinside, Mirabox, or Anthropic. Device communication uses the MIT-licensed
[MiraboxSpace StreamDock Device SDK](https://github.com/MiraboxSpace/StreamDock-Device-SDK)
(see LICENSE for attribution).
