# Claude UNLMTD — TRMNL plugin

*A TRMNL-style rebrand of "Claude Limits" — the joke is that it's tracking
the very opposite. On-screen data labels stay literal.*

Shows your Claude Code usage against Anthropic's rolling limits on a TRMNL
e-ink display: the 5-hour session window plus the 7-day all-models, Sonnet,
and Opus buckets. Each limit gets its percentage, a progress bar, and a
"resets in …" countdown. Inspired by
[ClaudePulse](https://github.com/sergey-zhuravel/ClaudePulse).

```
┌──────────────────────────────────────────────────────────────┐
│   45        68        20        12                           │
│   %         %         %         %                            │
│   ▰▰▰▱▱▱   ▰▰▰▰▱▱   ▰▰▱▱▱▱   ▰▱▱▱▱▱                          │
│   Session   Weekly    Sonnet    Opus                         │
│   3h 12m    Wed 10:00 Wed 10:00 Wed 10:00                    │
└──────────────────────────────────────────────────────────────┘
 Claude UNLMTD · Max · updated 18:48
```

## How it works

- A small Python script reads your OAuth token from `~/.claude/.credentials.json`
  (the same file Claude Code itself uses).
- It calls `GET https://api.anthropic.com/api/oauth/usage` with that token.
- It transforms the response into flat merge variables and POSTs them to a
  TRMNL plugin **webhook** URL.
- A macOS LaunchAgent runs the script every 10 minutes.

The OAuth token never leaves your machine. TRMNL doesn't make any inbound
connection to your Mac.

## Setup

### 1. Create the TRMNL plugin

1. Go to your TRMNL dashboard → **Plugins** → **New plugin**.
2. Choose **Webhook** as the strategy.
3. Name it "Claude UNLMTD" (or whatever).
4. Copy the webhook URL TRMNL shows you. It looks like
   `https://usetrmnl.com/api/custom_plugins/<id>`.
5. Paste the contents of each `.liquid` file in `views/` into the matching
   view editor (Full, Half horizontal, Half vertical, Quadrant), and save.

### 2. Install the push script

```bash
git clone <this repo>
cd TRMNL_Claude_limits

# Verify it can read your credentials and talk to Anthropic
python3 scripts/push_usage.py --dry-run

# Install the LaunchAgent (replaces TRMNL_WEBHOOK_URL with yours)
./scripts/install.sh "https://usetrmnl.com/api/custom_plugins/<id>"

# Tail logs
tail -f ~/Library/Logs/trmnl-claude-usage.log
```

The LaunchAgent runs at load and every 10 minutes thereafter. The TRMNL
device fetches the latest stored payload on its own refresh cycle (default
~15 min for plus models).

### 3. Verify

Hit the webhook with a fixture to confirm the views render before relying on
the live script:

```bash
curl -X POST \
     -H 'Content-Type: application/json' \
     -d @samples/payload-typical.json \
     "https://usetrmnl.com/api/custom_plugins/<id>"
```

Edge cases to spot-check:

- `samples/payload-high-usage.json` — all bars near 100%, short reset label
- `samples/payload-stale.json` — `is_stale: true`, the stale banner appears
- `samples/payload-zero.json` — fresh week, every value at 0

### Uninstall

```bash
./scripts/uninstall.sh
```

## The merge variable contract

The Liquid templates read these keys directly. The script always emits all
of them; `weekly_opus_*` and `weekly_sonnet_*` come back as 0 / "" if the
Anthropic API doesn't include those buckets in the response.

| key | type | example |
|---|---|---|
| `plan_tier` | string | `"Max"` |
| `session_percent` | int 0–100 | `45` |
| `session_reset_label` | string | `"3h 12m"`, `"Soon"`, `""` |
| `weekly_all_percent` | int 0–100 | `68` |
| `weekly_all_reset_label` | string | `"Wed 10:00"` |
| `weekly_sonnet_percent` | int 0–100 | `20` |
| `weekly_sonnet_reset_label` | string | `"Wed 10:00"` |
| `weekly_opus_percent` | int 0–100 | `12` |
| `weekly_opus_reset_label` | string | `"Wed 10:00"` |
| `refreshed_at_label` | string | `"18:48"` |
| `is_stale` | bool | `false` |
| `frame_index` | int 0–3 | `2` |

The `frame_index` advances by 1 on every push and wraps at 4. It drives
the mascot's idle animation — see [Mascot](#mascot) below.

## Troubleshooting

- **`no Claude credentials found`** — run `claude login` first.
- **`token rejected (401)`** — Claude's OAuth token expired. `claude login`
  refreshes it.
- **HTTP 429s** — the script silently skips the POST. TRMNL keeps showing
  the last frame. After ~25 min the stale flag is set on the next refresh.
- **Numbers stuck on the device** — check `~/Library/Logs/trmnl-claude-usage.log`
  for failures. Run `python3 scripts/push_usage.py --dry-run --verbose` to
  confirm the script still works.
- **Plan tier wrong** — set `CLAUDE_PLAN=Pro` (or `Max`, `Team`) on the
  LaunchAgent's environment, or set the `claude_plan` custom field in the
  TRMNL plugin settings.

## Layout

```
TRMNL_Claude_limits/
├── README.md
├── settings.yml             # TRMNL plugin metadata
├── scripts/
│   ├── push_usage.py        # data pipeline (stdlib only)
│   ├── install.sh           # writes & loads the LaunchAgent
│   ├── uninstall.sh
│   └── com.claude.trmnl.usage.plist.tmpl
├── views/
│   ├── full.liquid          # 800×480
│   ├── half_horizontal.liquid  # 800×240
│   ├── half_vertical.liquid    # 400×480
│   └── quadrant.liquid         # 400×240
└── samples/
    ├── payload-typical.json
    ├── payload-high-usage.json
    ├── payload-stale.json
    └── payload-zero.json
```

## Mascot

Every view includes a pixel-art Claude — a monospace ASCII sticker where
each character cell is exactly one source pixel. It's not decoration: it's
a mood indicator you can read across the room.

**Mood** is derived from the worst live bucket:

| Mood       | Trigger                              |
|------------|--------------------------------------|
| `happy`    | worst bucket < 40%                   |
| `neutral`  | 40% ≤ worst < 70%                    |
| `worried`  | 70% ≤ worst < 90%                    |
| `panicked` | worst ≥ 90% *or* `is_stale`          |

**Idle animation** cycles across refresh ticks. `frame_index` (0..3) is
advanced by `push_usage.py` on every run and drives one of four sub-frames:

| Idle       | Mutation                                     |
|------------|----------------------------------------------|
| 0          | canonical                                    |
| 1          | left arm bobs down                           |
| 2          | blink (suppressed on `panicked`)             |
| 3          | right arm bobs down                          |

At the default 10-min refresh, a full idle cycle takes 40 minutes — the
mascot feels quietly alive at the timescale you actually glance at a TRMNL,
with **zero on-device animation cost**. No CSS transitions, no JS, no extra
refreshes. All 16 possible frames are pre-composed as static text at
render time.

Preview all 16 frames with `open prototypes/index.html`.

## Not yet supported

- Live consumption-rate projections ("you'll hit the limit in ~24 min")
  that ClaudePulse shows. Doable, but adds template noise.
- WebView cookie fallback for users without a `.credentials.json`. Run
  `claude login` once and the file appears.
