#!/usr/bin/env python3
"""
TRMNL Claude mascot generator — HI-RES pixel-art SVG.

4 emotional states (happy, neutral, worried, panicked).
Grid: 44 x 32 logical pixels per mascot (2x the earlier draft — more detail
per feature). Chunky 2x2 checker keeps it clean, not sandy.

Run:
    python3 mascots.py
Output (written next to this script):
    mascot_happy.svg
    mascot_neutral.svg
    mascot_worried.svg
    mascot_panicked.svg
    mascot_sheet.svg
    mascot_preview.html
"""

import os

# ── grid ──────────────────────────────────────────────────────────────
COLS, ROWS = 44, 32          # logical pixels per mascot cell (2x prior)
PX         = 24              # svg units per logical pixel → 1056×768 cell
CHECKER    = 2               # size in logical pixels of one checker square

# ── palette (16 evenly-spaced grays, e-ink safe) ─────────────────────
def gray(v):                 # v in 0..15
    n = round(255 * v / 15)
    return f"#{n:02x}{n:02x}{n:02x}"

BG      = gray(15)           # pure white background
LIGHT   = gray(11)           # body base
MID     = gray(8)            # body checker second tone
OUTLINE = gray(4)            # thin darker silhouette edge
SHADOW  = gray(5)            # subtle bottom band mid
SHADOW2 = gray(7)            # subtle bottom band light
BLACK   = gray(0)
WHITE   = gray(15)

# ── grid helpers ─────────────────────────────────────────────────────
def blank():
    return [[" "] * COLS for _ in range(ROWS)]

def rect(g, x, y, w, h, ch):
    for j in range(h):
        for i in range(w):
            if 0 <= y + j < ROWS and 0 <= x + i < COLS:
                g[y + j][x + i] = ch

# ── shared body silhouette ───────────────────────────────────────────
def draw_body(g):
    # main torso 32w × 22h
    rect(g, 6, 4, 32, 22, ".")
    # arm nubs at mid-height (default resting)
    rect(g, 2, 12, 4, 6, ".")
    rect(g, 38, 12, 4, 6, ".")
    # legs sticking down (2 rectangles with gap)
    rect(g, 10, 26, 6, 4, ".")
    rect(g, 28, 26, 6, 4, ".")

# ── 4 states ─────────────────────────────────────────────────────────
def neutral():
    g = blank()
    draw_body(g)
    # solid dark eyes 4×4
    rect(g, 12, 12, 4, 4, "#")
    rect(g, 28, 12, 4, 4, "#")
    # tiny flat mouth 4×2
    rect(g, 20, 19, 4, 2, "#")
    return g

def happy():
    g = blank()
    draw_body(g)
    # remove default side arms
    rect(g, 2, 12, 4, 6, " ")
    rect(g, 38, 12, 4, 6, " ")
    # left arm raised diagonally up-and-out
    rect(g, 2, 4, 4, 4, ".")
    rect(g, 4, 8, 4, 4, ".")
    # right arm raised (mirror)
    rect(g, 38, 4, 4, 4, ".")
    rect(g, 36, 8, 4, 4, ".")
    # smiling arc eyes ^_^   (curved: dip in middle, rise at ends)
    #   left
    rect(g, 10, 12, 2, 2, "#")
    rect(g, 12, 10, 4, 2, "#")
    rect(g, 16, 12, 2, 2, "#")
    #   right
    rect(g, 26, 12, 2, 2, "#")
    rect(g, 28, 10, 4, 2, "#")
    rect(g, 32, 12, 2, 2, "#")
    # smiling mouth
    rect(g, 18, 18, 8, 2, "#")
    rect(g, 20, 20, 4, 2, "#")
    return g

def worried():
    g = blank()
    draw_body(g)
    # left arm bent inward (self-hug)
    rect(g, 2, 12, 4, 6, " ")            # remove default left arm
    rect(g, 8, 18, 8, 2, ".")            # upper arm across chest
    rect(g, 12, 20, 6, 2, ".")           # forearm
    # squinted eyes (4×2 horizontal bars)
    rect(g, 12, 14, 4, 2, "#")
    rect(g, 28, 14, 4, 2, "#")
    # angled-inward concerned brows
    #   left brow  ╲
    rect(g, 10, 10, 2, 2, "#")
    rect(g, 12, 12, 2, 2, "#")
    rect(g, 14, 12, 2, 2, "#")
    #   right brow ╱
    rect(g, 32, 10, 2, 2, "#")
    rect(g, 30, 12, 2, 2, "#")
    rect(g, 28, 12, 2, 2, "#")
    # small wavy mouth
    rect(g, 18, 20, 2, 2, "#")
    rect(g, 20, 22, 2, 2, "#")
    rect(g, 22, 20, 2, 2, "#")
    rect(g, 24, 22, 2, 2, "#")
    # sweat drop (top-right of head)
    rect(g, 35, 6, 2, 4, "o")
    rect(g, 34, 8, 2, 2, "o")
    rect(g, 36, 8, 2, 2, "o")
    return g

def panicked():
    g = blank()
    draw_body(g)
    # remove default side arms
    rect(g, 2, 12, 4, 6, " ")
    rect(g, 38, 12, 4, 6, " ")
    # arms flung straight up, spread wide
    rect(g, 0, 0, 4, 4, ".")     # left hand
    rect(g, 2, 4, 4, 4, ".")
    rect(g, 4, 8, 4, 4, ".")     # connect to body
    rect(g, 40, 0, 4, 4, ".")    # right hand (mirror)
    rect(g, 38, 4, 4, 4, ".")
    rect(g, 36, 8, 4, 4, ".")
    # wide googly eyes: 6×6 white with 2×2 dark pupil
    rect(g, 10, 10, 6, 6, "o")
    rect(g, 12, 12, 2, 2, "#")
    rect(g, 28, 10, 6, 6, "o")
    rect(g, 30, 12, 2, 2, "#")
    # big open shock mouth (oval-ish 6×4)
    rect(g, 20, 18, 4, 4, "#")
    rect(g, 19, 19, 6, 2, "#")
    # motion-line squiggles around the head
    rect(g, 8, 2, 4, 2, "#")
    rect(g, 32, 2, 4, 2, "#")
    rect(g, 5, 6, 2, 2, "#")
    rect(g, 37, 6, 2, 2, "#")
    rect(g, 3, 10, 2, 2, "#")
    rect(g, 39, 10, 2, 2, "#")
    return g

STATES = {
    "happy":    happy(),
    "neutral":  neutral(),
    "worried":  worried(),
    "panicked": panicked(),
}

# ── outline detection ────────────────────────────────────────────────
def edge_pixels(grid):
    """Solid pixels that border a transparent pixel or the canvas edge."""
    edge = set()
    for y in range(ROWS):
        for x in range(COLS):
            if grid[y][x] == " ":
                continue
            for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                ny, nx = y + dy, x + dx
                if not (0 <= ny < ROWS and 0 <= nx < COLS) or grid[ny][nx] == " ":
                    edge.add((x, y))
                    break
    return edge

# ── body-fill picker (chunky checker + bottom shadow band + edge) ────
def body_fill(x, y, edges):
    if (x, y) in edges:
        return OUTLINE
    checker_dark = ((x // CHECKER) + (y // CHECKER)) % 2 == 1
    # bottom band shadow (last ~6 rows of the body area)
    if y >= 22:
        return SHADOW if checker_dark else SHADOW2
    return MID if checker_dark else LIGHT

# ── SVG rendering ────────────────────────────────────────────────────
def cell_svg(grid, ox=0, oy=0):
    edges = edge_pixels(grid)
    parts = []
    for y in range(ROWS):
        for x in range(COLS):
            ch = grid[y][x]
            if ch == ".":
                fill = body_fill(x, y, edges)
            elif ch == "#":
                fill = BLACK
            elif ch == "o":
                fill = WHITE
            else:
                continue
            parts.append(
                f'<rect x="{ox + x*PX}" y="{oy + y*PX}" '
                f'width="{PX}" height="{PX}" fill="{fill}"/>'
            )
    return "\n".join(parts)

def render_single(grid):
    w, h = COLS * PX, ROWS * PX
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}" shape-rendering="crispEdges">\n'
        f'<rect width="{w}" height="{h}" fill="{BG}"/>\n'
        f'{cell_svg(grid)}\n'
        f'</svg>\n'
    )

def render_sheet():
    cw, ch = COLS * PX, ROWS * PX
    W, H = cw * 2, ch * 2
    positions = [
        ("happy",    0,   0),
        ("neutral",  cw,  0),
        ("worried",  0,   ch),
        ("panicked", cw,  ch),
    ]
    body = "\n".join(cell_svg(STATES[n], ox, oy) for n, ox, oy in positions)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" shape-rendering="crispEdges">\n'
        f'<rect width="{W}" height="{H}" fill="{BG}"/>\n'
        f'{body}\n'
        f'</svg>\n'
    )

# ── write files ──────────────────────────────────────────────────────
OUT = os.path.dirname(os.path.abspath(__file__))

for name, g in STATES.items():
    with open(os.path.join(OUT, f"mascot_{name}.svg"), "w") as f:
        f.write(render_single(g))

with open(os.path.join(OUT, "mascot_sheet.svg"), "w") as f:
    f.write(render_sheet())

preview = f"""<!doctype html><meta charset=utf8>
<title>TRMNL mascot preview (hi-res)</title>
<style>
  body {{ background:#e8e8e8; padding:24px; font:14px/1.4 system-ui,sans-serif; }}
  .row {{ display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }}
  .tile {{ background:#fff; padding:12px; border:1px solid #ccc; text-align:center; }}
  .tile img {{ display:block; width:360px; height:auto; image-rendering:pixelated; margin-bottom:8px; }}
  h2 {{ margin-top:32px; }}
  .sheet {{ background:#fff; border:1px solid #ccc; padding:12px; display:inline-block; }}
  .sheet img {{ width:900px; height:auto; image-rendering:pixelated; display:block; }}
</style>
<h1>TRMNL Claude mascot — hi-res, {COLS}×{ROWS} logical pixels/cell</h1>
<div class=row>
  <div class=tile><img src="mascot_happy.svg"><div>happy</div></div>
  <div class=tile><img src="mascot_neutral.svg"><div>neutral</div></div>
  <div class=tile><img src="mascot_worried.svg"><div>worried</div></div>
  <div class=tile><img src="mascot_panicked.svg"><div>panicked</div></div>
</div>
<h2>2×2 sheet</h2>
<div class=sheet><img src="mascot_sheet.svg"></div>
"""
with open(os.path.join(OUT, "mascot_preview.html"), "w") as f:
    f.write(preview)

print(f"wrote hi-res mascots ({COLS}x{ROWS} logical, {PX}px each → {COLS*PX}x{ROWS*PX} per cell):")
for name in STATES:
    print(f"  scripts/mascot_{name}.svg")
print(f"  scripts/mascot_sheet.svg    ({COLS*PX*2}x{ROWS*PX*2})")
print("  scripts/mascot_preview.html")
