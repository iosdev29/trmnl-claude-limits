#!/usr/bin/env python3
"""Push Claude Code usage to a TRMNL webhook plugin.

Reads the user's local Claude OAuth token, queries
https://api.anthropic.com/api/oauth/usage, transforms the response into the
stable merge-variable contract the Liquid templates expect, and POSTs to the
configured TRMNL webhook URL.

Mirrors the API contract documented in ClaudePulse's ClaudeUsageFetcher.swift.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
ANTHROPIC_BETA = "oauth-2025-04-20"
DEFAULT_CLI_VERSION = "2.1.85"
KEYCHAIN_SERVICE = "Claude Code-credentials"
STATE_FILE = Path.home() / ".cache" / "trmnl-claude-usage" / "state.json"
STALE_AFTER_SECONDS = 15 * 60
MASCOT_FRAME_COUNT = 4


def claude_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".claude"


def read_credentials_file() -> dict | None:
    for name in (".credentials.json", "credentials.json"):
        path = claude_dir() / name
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
    return None


def read_keychain_credentials() -> dict | None:
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", os.environ.get("USER", ""), "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def read_cli_version() -> str:
    try:
        data = json.loads((Path.home() / ".claude.json").read_text())
        return data.get("lastOnboardingVersion") or DEFAULT_CLI_VERSION
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CLI_VERSION


def fetch_usage(access_token: str) -> dict:
    req = urllib.request.Request(USAGE_URL, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", f"claude-code/{read_cli_version()}")
    req.add_header("anthropic-beta", ANTHROPIC_BETA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def to_percent(util: float | int | str | None) -> int:
    if util is None:
        return 0
    try:
        n = float(util)
    except (TypeError, ValueError):
        return 0
    # /api/oauth/usage returns 0–100 directly (per ClaudePulse parseUsageJSON).
    # Defensive: if the API ever switches to 0–1, scale up.
    if 0 < n <= 1.0:
        n *= 100
    return max(0, min(100, int(round(n))))


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def reset_label(reset_at: datetime | None, now: datetime) -> str:
    if reset_at is None:
        return ""
    delta = reset_at - now
    seconds = int(delta.total_seconds())
    if seconds <= 60:
        return "Soon"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 24 * 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m" if m else f"{h}h"
    # > 24h: show weekday + local time (e.g. "Wed 10:00")
    local = reset_at.astimezone()
    return local.strftime("%a %H:%M")


def bucket(json_obj: dict, key: str, now: datetime) -> tuple[int, str]:
    section = json_obj.get(key) or {}
    if not isinstance(section, dict):
        return 0, ""
    pct = to_percent(section.get("utilization"))
    label = reset_label(parse_iso(section.get("resets_at")), now)
    return pct, label


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def is_stale(state: dict, now: datetime) -> bool:
    last = state.get("last_success_at")
    if not last:
        return False
    last_dt = parse_iso(last)
    if last_dt is None:
        return False
    return (now - last_dt).total_seconds() > STALE_AFTER_SECONDS


def next_frame_index(prev: object) -> int:
    try:
        n = int(prev)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = -1
    return (n + 1) % MASCOT_FRAME_COUNT


def build_payload(usage: dict, plan_tier: str | None, now: datetime,
                  frame_index: int) -> dict:
    session_pct, session_lbl = bucket(usage, "five_hour", now)
    all_pct, all_lbl = bucket(usage, "seven_day", now)
    sonnet_pct, sonnet_lbl = bucket(usage, "seven_day_sonnet", now)
    opus_pct, opus_lbl = bucket(usage, "seven_day_opus", now)
    return {
        "merge_variables": {
            "plan_tier": plan_tier or "",
            "session_percent": session_pct,
            "session_reset_label": session_lbl,
            "weekly_all_percent": all_pct,
            "weekly_all_reset_label": all_lbl,
            "weekly_sonnet_percent": sonnet_pct,
            "weekly_sonnet_reset_label": sonnet_lbl,
            "weekly_opus_percent": opus_pct,
            "weekly_opus_reset_label": opus_lbl,
            "refreshed_at_label": now.astimezone().strftime("%H:%M"),
            "is_stale": False,
            "frame_index": frame_index,
        }
    }


def post_to_webhook(url: str, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def post_stale_payload(url: str, now: datetime) -> None:
    state = load_state()
    last_payload = state.get("last_payload")
    if not last_payload:
        return
    last_payload["merge_variables"]["is_stale"] = True
    post_to_webhook(url, last_payload)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--webhook-url", default=os.environ.get("TRMNL_WEBHOOK_URL"))
    ap.add_argument("--plan", default=os.environ.get("CLAUDE_PLAN"),
                    help="Plan tier label sent in payload (overrides subscriptionType)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print payload instead of posting")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not args.dry_run and not args.webhook_url:
        print("error: --webhook-url or TRMNL_WEBHOOK_URL is required", file=sys.stderr)
        return 2

    creds = read_credentials_file() or read_keychain_credentials()
    if not creds:
        print("error: no Claude credentials found. Run `claude login` first.",
              file=sys.stderr)
        return 1

    oauth = creds.get("claudeAiOauth") or {}
    access_token = oauth.get("accessToken")
    if not access_token:
        print("error: credentials present but no accessToken inside.", file=sys.stderr)
        return 1
    plan_tier = args.plan or oauth.get("subscriptionType") or "Max"

    now = datetime.now(timezone.utc)
    prev_state = load_state()
    frame_index = next_frame_index(prev_state.get("frame_index"))
    try:
        usage = fetch_usage(access_token)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("error: token rejected (401). Run `claude login` to refresh.",
                  file=sys.stderr)
            return 1
        if e.code == 429:
            # Don't update — TRMNL keeps the last frame. Stale banner triggers
            # after STALE_AFTER_SECONDS if 429s persist.
            if not args.dry_run:
                state = load_state()
                if is_stale(state, now):
                    post_stale_payload(args.webhook_url, now)
            if args.verbose:
                print("rate-limited (429); skipping POST", file=sys.stderr)
            return 0
        print(f"error: HTTP {e.code} from {USAGE_URL}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"error: network failure: {e}", file=sys.stderr)
        return 1

    payload = build_payload(usage, plan_tier, now, frame_index)

    if args.dry_run:
        # persist so consecutive --dry-run calls advance the mascot idle cycle
        save_state({
            "last_success_at": prev_state.get("last_success_at"),
            "last_payload": prev_state.get("last_payload"),
            "frame_index": frame_index,
        })
        print(json.dumps(payload, indent=2))
        return 0

    try:
        post_to_webhook(args.webhook_url, payload)
    except urllib.error.HTTPError as e:
        print(f"error: webhook POST failed: HTTP {e.code}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"error: webhook POST failed: {e}", file=sys.stderr)
        return 1

    save_state({
        "last_success_at": now.isoformat(),
        "last_payload": payload,
        "frame_index": frame_index,
    })
    if args.verbose:
        print(f"ok: posted to {args.webhook_url}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
