"""Render the 3 action tiles, upscale, and stitch into one preview PNG."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from claude_deck.render import render_action

SCALE = 6
GAP = 16
TILES = [("design", "Design"), ("review", "Review"), ("compact", "Compact")]

imgs = []
for name, label in TILES:
    jpeg = render_action(name, label)
    im = Image.open(io.BytesIO(jpeg)).resize((64 * SCALE, 64 * SCALE), Image.NEAREST)
    imgs.append(im)

w = sum(i.width for i in imgs) + GAP * (len(imgs) + 1)
h = imgs[0].height + GAP * 2
canvas = Image.new("RGB", (w, h), (12, 14, 20))
x = GAP
for im in imgs:
    canvas.paste(im, (x, GAP))
    x += im.width + GAP

out = Path(__file__).resolve().parents[1] / "action_tiles_preview.png"
canvas.save(out)
print(out)
