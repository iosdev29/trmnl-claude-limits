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

### 2. Install the push agent

Pick your OS. Each is one line; the installer prompts for your TRMNL webhook
URL, POSTs one test payload to confirm the pipe works, and schedules the push
job every 10 minutes.

**macOS (Homebrew)**

```bash
brew install --HEAD iosdev29/trmnl-claude-limits/trmnl-claude-limits
trmnl-claude-limits
```

If the shorthand tap doesn't resolve, tap explicitly first:

```bash
brew tap iosdev29/trmnl-claude-limits https://github.com/iosdev29/trmnl-claude-limits.git
brew install --HEAD trmnl-claude-limits
```

**Linux (or macOS without Homebrew)**

```bash
curl -fsSL https://raw.githubusercontent.com/iosdev29/trmnl-claude-limits/main/scripts/bootstrap.sh | bash
```

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/iosdev29/trmnl-claude-limits/main/scripts/bootstrap.ps1 | iex
```

**Prerequisites (all platforms):**

- Python 3.8+
- Claude Code installed and `claude login` completed once — the installer
  reads your OAuth token from `~/.claude/.credentials.json`. That token
  never leaves your machine.

**Forking?** Point the installers at your fork with an env var:

```bash
REPO=you/your-fork curl -fsSL https://raw.githubusercontent.com/you/your-fork/main/scripts/bootstrap.sh | bash
```

```powershell
$env:REPO = "you/your-fork"
irm https://raw.githubusercontent.com/you/your-fork/main/scripts/bootstrap.ps1 | iex
```

### 3. Verify

Hit the webhook with a fixture to confirm the views render before relying on
the live agent:

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

Manual one-off push (all platforms, after install):

```bash
trmnl-claude-limits push --dry-run    # prints payload, doesn't POST
trmnl-claude-limits push               # posts once, right now
```

### Uninstall

Removes the scheduler entry only — leaves the tool itself installed:

```bash
trmnl-claude-limits --uninstall
```

To also remove the tool: `brew uninstall trmnl-claude-limits` (macOS), delete
`~/.local/share/trmnl-claude-limits` + `~/.local/bin/trmnl-claude-limits`
(Linux), or delete `%LOCALAPPDATA%\trmnl-claude-limits` +
`%LOCALAPPDATA%\Programs\trmnl-claude-limits` (Windows).

### Advanced: install from a clone

If you'd rather inspect the source before running it:

```bash
git clone https://github.com/iosdev29/trmnl-claude-limits
cd trmnl-claude-limits
python3 scripts/push_usage.py --dry-run   # sanity check
python3 scripts/install.py                # interactive; same installer the one-liners run
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
- **Numbers stuck on the device** — check the log (below) for failures. Run
  `trmnl-claude-limits push --dry-run --verbose` to confirm the agent still
  works end-to-end.
- **Plan tier wrong** — set `CLAUDE_PLAN=Pro` (or `Max`, `Team`) on the
  scheduler's environment, or set the `claude_plan` custom field in the
  TRMNL plugin settings.

Log locations:

| OS      | Path                                                            |
|---------|-----------------------------------------------------------------|
| macOS   | `~/Library/Logs/trmnl-claude-usage.log`                         |
| Linux   | `journalctl --user -u trmnl-claude-usage.service`               |
| Windows | `%LOCALAPPDATA%\trmnl-claude-usage\log.txt`                     |

## Layout

```
TRMNL_Claude_limits/
├── README.md
├── settings.yml               # TRMNL plugin metadata
├── Formula/
│   └── trmnl-claude-limits.rb # Homebrew formula (macOS one-liner)
├── LICENSE                    # MIT
├── scripts/
│   ├── push_usage.py          # data pipeline (stdlib only)
│   ├── install.py             # cross-platform interactive installer
│   ├── install.sh             # thin unix wrapper for install.py
│   ├── uninstall.sh           # thin unix wrapper for install.py --uninstall
│   ├── bootstrap.sh           # curl-pipe installer (Linux/macOS)
│   └── bootstrap.ps1          # PowerShell installer (Windows)
├── views/
│   ├── full.liquid            # 800×480
│   ├── half_horizontal.liquid # 800×240
│   ├── half_vertical.liquid   # 400×480
│   └── quadrant.liquid        # 400×240
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
