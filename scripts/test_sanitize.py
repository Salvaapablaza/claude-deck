import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from claude_deck.render import _sanitize, render_key

cases = [
    "✳ Claude Code",
    "â³ Claude Code",
    "Kosoku-48",
    "Address PR review comments",
    "/some-namespace:some-command",
]
for raw in cases:
    print(ascii(raw), "->", repr(_sanitize(raw)))
print("render ok bytes:", len(render_key("✳ Claude Code", "running", "2")))
