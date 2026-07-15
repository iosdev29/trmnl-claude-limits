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
import copy
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_REFRESH_URL = "https://platform.claude.com/v1/oauth/token"
# Public OAuth client_id shipped with Claude Code — same one the CLI uses.
# Verified against the @anthropic-ai/claude-code npm package (cli.js) and
# Anthropic's own claude.ai/login redirect target. Not per-install; safe to
# hardcode.
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_DEFAULT_SCOPES = (
    "user:profile user:inference user:sessions:claude_code "
    "user:mcp_servers user:file_upload"
)
ANTHROPIC_BETA = "oauth-2025-04-20"
DEFAULT_CLI_VERSION = "2.1.85"
KEYCHAIN_SERVICE = "Claude Code-credentials"
STALE_AFTER_SECONDS = 15 * 60
MASCOT_FRAME_COUNT = 4


def _state_file_path() -> Path:
    """Per-platform cache location for the mascot/state file.

    - macOS:   ~/Library/Caches/trmnl-claude-usage/
    - Linux:   $XDG_CACHE_HOME/trmnl-claude-usage/  (or ~/.cache/…)
    - Windows: %LOCALAPPDATA%\\trmnl-claude-usage\\
    """
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Caches"
    elif system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "trmnl-claude-usage" / "state.json"


STATE_FILE = _state_file_path()
# Refresh a bit before actual expiry so we don't race the API with a token
# that lapses mid-request.
TOKEN_EXPIRY_BUFFER_SECONDS = 60

WEBHOOK_PREFIXES = (
    "https://trmnl.com/api/custom_plugins/",
    "https://usetrmnl.com/api/custom_plugins/",
)


def redact_webhook(url: str | None) -> str:
    """Strip the plugin token from a webhook URL so it's safe to log.

    The URL is effectively an auth token — anyone with it can spoof pushes,
    and launchd/systemd log files are readable outside our process.
    """
    if not url:
        return "(unset)"
    for prefix in WEBHOOK_PREFIXES:
        if url.startswith(prefix):
            tail = url[len(prefix):].rstrip("/")
            return f"{prefix}{tail[:8]}…" if len(tail) > 8 else url
    return "(redacted)"


def claude_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".claude"


CredsSaver = Callable[[dict], bool]


def _write_credentials_file(path: Path, creds: dict) -> bool:
    """Atomic write that preserves the file's original mode (Claude Code
    stores 0600 to keep the token private — we must not widen it)."""
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o600
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(creds))
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def _write_keychain_credentials(creds: dict) -> bool:
    if platform.system() != "Darwin":
        return False
    payload = json.dumps(creds)
    try:
        result = subprocess.run(
            ["/usr/bin/security", "add-generic-password", "-U",
             "-s", KEYCHAIN_SERVICE,
             "-a", os.environ.get("USER", ""),
             "-w", payload],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def read_credentials() -> tuple[dict, CredsSaver] | None:
    """Return (creds, save_fn) where save_fn writes updated creds back to the
    same source we read from. Prefer the file (Claude Code's usual location)
    over Keychain; fall back to Keychain on macOS only.
    """
    for name in (".credentials.json", "credentials.json"):
        path = claude_dir() / name
        # Open once (no exists()+read TOCTOU) — swallow OSError for missing file
        # or transient read failures alike.
        try:
            with path.open("rb") as f:
                data = json.loads(f.read())
        except (FileNotFoundError, IsADirectoryError, PermissionError,
                json.JSONDecodeError):
            continue

        def _save(new_creds: dict, _path: Path = path) -> bool:
            return _write_credentials_file(_path, new_creds)

        return data, _save

    # macOS Keychain fallback — /usr/bin/security exists on some Linux distros
    # as unrelated tooling, so gate strictly by platform.
    if platform.system() != "Darwin":
        return None
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
    try:
        data = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return None
    return data, _write_keychain_credentials


def read_cli_version() -> str:
    try:
        data = json.loads((Path.home() / ".claude.json").read_text())
        return data.get("lastOnboardingVersion") or DEFAULT_CLI_VERSION
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CLI_VERSION


def token_is_expired(oauth: dict, now: float | None = None) -> bool:
    """True if the access token has expired (or expires within the buffer)."""
    expires_at = oauth.get("expiresAt")
    if not isinstance(expires_at, (int, float)):
        return False
    # Claude Code stores expiresAt as epoch milliseconds.
    exp_seconds = expires_at / 1000
    now = time.time() if now is None else now
    return now + TOKEN_EXPIRY_BUFFER_SECONDS >= exp_seconds


def refresh_oauth(creds: dict) -> dict | None:
    """Refresh the OAuth access token via platform.claude.com.

    Returns the updated creds dict with only the token-related fields
    replaced — every other key (scopes, subscriptionType, mcpOAuth, …)
    survives untouched, so the result is safe to write back for Claude Code
    to keep using. Returns None on permanent failure (refresh token revoked
    or malformed response).
    """
    creds = copy.deepcopy(creds)
    oauth = creds.get("claudeAiOauth") or {}
    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        return None
    scopes = oauth.get("scopes") or []
    scope_str = " ".join(scopes) if scopes else OAUTH_DEFAULT_SCOPES

    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": OAUTH_CLIENT_ID,
        "scope": scope_str,
    }).encode("utf-8")
    req = urllib.request.Request(TOKEN_REFRESH_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # 400/401 = refresh token revoked or rotated by concurrent Claude Code
        # refresh — permanent for this token. 5xx / other = transient; caller
        # retries next tick.
        return None
    except urllib.error.URLError:
        return None

    access_token = data.get("access_token")
    expires_in = data.get("expires_in")
    if not access_token or not isinstance(expires_in, (int, float)):
        return None

    now_ms = int(time.time() * 1000)
    oauth["accessToken"] = access_token
    oauth["expiresAt"] = int(now_ms + expires_in * 1000)
    # Refresh token rotation — preserve the new one if returned.
    new_refresh = data.get("refresh_token")
    if isinstance(new_refresh, str) and new_refresh:
        oauth["refreshToken"] = new_refresh
    rt_expires_in = data.get("refresh_token_expires_in")
    if isinstance(rt_expires_in, (int, float)):
        oauth["refreshTokenExpiresAt"] = int(now_ms + rt_expires_in * 1000)
    creds["claudeAiOauth"] = oauth
    return creds


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
    # Atomic replace so a crash mid-write can't leave truncated JSON that
    # zeroes out frame_index and last_payload on the next tick.
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, STATE_FILE)


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


def extract_buckets(usage: dict, now: datetime) -> dict:
    """Return the four display slots (session, weekly_all, weekly_sonnet,
    weekly_opus) with dynamic labels.

    Prefers the newer 'limits' array (authoritative per-scope entries) and
    falls back to the legacy top-level keys (five_hour, seven_day, etc.).
    This makes new model rollouts (Fable, next Sonnet/Opus versions, etc.)
    picked up automatically — the display_name from the API drives the
    per-slot label instead of hardcoding "Sonnet"/"Opus".
    """
    session_pct,  session_lbl  = bucket(usage, "five_hour",        now)
    all_pct,      all_lbl      = bucket(usage, "seven_day",        now)
    sonnet_pct,   sonnet_lbl   = bucket(usage, "seven_day_sonnet", now)
    opus_pct,     opus_lbl     = bucket(usage, "seven_day_opus",   now)
    sonnet_name = "Sonnet"
    opus_name   = "Opus"

    limits = usage.get("limits")
    if isinstance(limits, list):
        for limit in limits:
            if not isinstance(limit, dict):
                continue
            kind    = limit.get("kind")
            pct     = to_percent(limit.get("percent"))
            reset   = reset_label(parse_iso(limit.get("resets_at")), now)
            scope   = limit.get("scope") or {}
            model   = (scope.get("model")   or {}).get("display_name")
            surface = (scope.get("surface") or {}).get("display_name")

            if kind == "session":
                session_pct, session_lbl = pct, reset
            elif kind == "weekly_all":
                all_pct, all_lbl = pct, reset
            elif kind == "weekly_scoped" and model:
                # "opus" in the display name → opus slot, anything else
                # (Sonnet, Fable, next model) → sonnet slot. Naming reflects
                # the current UI layout, not any hardcoded model list.
                if "opus" in model.lower():
                    opus_pct, opus_lbl, opus_name = pct, reset, model
                else:
                    sonnet_pct, sonnet_lbl, sonnet_name = pct, reset, model
            # weekly_scoped + surface (e.g. Claude Design "omelette") is
            # ignored for now — we don't render a design slot.

    return {
        "session_percent":         session_pct,
        "session_reset_label":     session_lbl,
        "weekly_all_percent":      all_pct,
        "weekly_all_reset_label":  all_lbl,
        "weekly_sonnet_percent":   sonnet_pct,
        "weekly_sonnet_reset_label": sonnet_lbl,
        "weekly_sonnet_name":      sonnet_name,
        "weekly_opus_percent":     opus_pct,
        "weekly_opus_reset_label": opus_lbl,
        "weekly_opus_name":        opus_name,
    }


def build_payload(usage: dict, plan_tier: str | None, now: datetime,
                  frame_index: int) -> dict:
    slots = extract_buckets(usage, now)
    return {
        "merge_variables": {
            "plan_tier": plan_tier or "",
            **slots,
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
        if resp.status >= 300:
            raise urllib.error.HTTPError(
                url, resp.status, "webhook returned non-2xx", resp.headers, None
            )


def post_stale_payload(url: str, state: dict) -> None:
    last_payload = state.get("last_payload")
    if not last_payload:
        return
    # Deepcopy so mutating is_stale doesn't corrupt the cached payload,
    # which the next successful tick would then persist back.
    stale = copy.deepcopy(last_payload)
    stale["merge_variables"]["is_stale"] = True
    post_to_webhook(url, stale)


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

    read_result = read_credentials()
    if not read_result:
        print("error: no Claude credentials found. Run `claude login` first.",
              file=sys.stderr)
        return 1
    creds, save_creds = read_result

    oauth = creds.get("claudeAiOauth") or {}
    access_token = oauth.get("accessToken")
    if not access_token:
        print("error: credentials present but no accessToken inside.", file=sys.stderr)
        return 1
    plan_tier = args.plan or oauth.get("subscriptionType") or "Max"

    # Proactive refresh: if the stored token has already lapsed (typical after
    # sleep), refresh before we burn a request the API will 401 on.
    if token_is_expired(oauth):
        refreshed = refresh_oauth(creds)
        if refreshed is not None:
            creds = refreshed
            save_creds(creds)  # best-effort; a failed write just re-refreshes next tick
            access_token = creds["claudeAiOauth"]["accessToken"]
            if args.verbose:
                print("token refreshed (proactive)", file=sys.stderr)

    now = datetime.now(timezone.utc)
    prev_state = load_state()
    frame_index = next_frame_index(prev_state.get("frame_index"))
    try:
        usage = fetch_usage(access_token)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # Reactive refresh: proactive check missed it (clock skew or
            # server-side revocation). Try once more with a fresh token.
            refreshed = refresh_oauth(creds)
            if refreshed is None:
                print("error: token rejected and refresh failed. "
                      "Run `claude login` to re-authenticate.", file=sys.stderr)
                return 1
            save_creds(refreshed)
            access_token = refreshed["claudeAiOauth"]["accessToken"]
            if args.verbose:
                print("token refreshed (reactive)", file=sys.stderr)
            try:
                usage = fetch_usage(access_token)
            except urllib.error.HTTPError as e2:
                print(f"error: HTTP {e2.code} after token refresh", file=sys.stderr)
                return 1
        elif e.code == 429:
            # Don't update — TRMNL keeps the last frame. Stale banner triggers
            # after STALE_AFTER_SECONDS if 429s persist.
            if not args.dry_run and is_stale(prev_state, now):
                post_stale_payload(args.webhook_url, prev_state)
            if args.verbose:
                print("rate-limited (429); skipping POST", file=sys.stderr)
            return 0
        else:
            print(f"error: HTTP {e.code} from {USAGE_URL}", file=sys.stderr)
            return 1
    except urllib.error.URLError as e:
        print(f"error: network failure: {e}", file=sys.stderr)
        return 1

    payload = build_payload(usage, plan_tier, now, frame_index)

    if args.dry_run:
        # Don't touch state — dry-run must be side-effect-free so a user
        # experimenting on their machine doesn't desync the live scheduler's
        # mascot idle cycle.
        print(json.dumps(payload, indent=2))
        return 0

    try:
        post_to_webhook(args.webhook_url, payload)
    except urllib.error.HTTPError as e:
        # TRMNL rate-limits webhook plugins (~1 push per 15 min). 403/429
        # under that policy is expected, not a failure — TRMNL keeps the
        # last frame and we retry next tick. Log as info so launchd doesn't
        # flag the run as failed.
        if e.code in (403, 429):
            if args.verbose:
                print(f"info: TRMNL rate-limited (HTTP {e.code}); "
                      f"keeping last frame, will retry next tick",
                      file=sys.stderr)
            return 0
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
        print(f"ok: posted to {redact_webhook(args.webhook_url)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
