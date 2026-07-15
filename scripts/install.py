#!/usr/bin/env python3
"""Claude UNLMTD — cross-platform installer.

Detects the OS, verifies Claude Code credentials, prompts for the TRMNL webhook
URL (opening the browser to help), pushes one payload to confirm the pipe
works, then installs a scheduler entry:

  macOS    launchd LaunchAgent   (~/Library/LaunchAgents)
  Linux    systemd --user timer  (~/.config/systemd/user)
  Windows  Task Scheduler task   (schtasks /Create)

Usage:
  python3 scripts/install.py                     # interactive
  python3 scripts/install.py --webhook-url URL   # non-interactive
  python3 scripts/install.py --uninstall
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

# push_usage.py always sits next to install.py — same dir under Homebrew's
# libexec (both flattened) as well as under scripts/ in a direct clone.
PUSH_SCRIPT = Path(__file__).resolve().parent / "push_usage.py"

LAUNCH_LABEL = "com.claude.trmnl.usage"
SYSTEMD_NAME = "trmnl-claude-usage"
WIN_TASK     = "ClaudeUnlmtdPush"

TRMNL_PLUGINS_URL = "https://trmnl.com/plugin_settings"

# Strict shape check. The URL is written into a launchd plist (XML), a systemd
# Environment= line, and a Windows schtasks command string — an unescaped `"`,
# `&`, `|`, `<`, `>`, or `%` in any of those breaks parsing or, worse, executes
# arbitrary commands. TRMNL currently issues webhook URLs on trmnl.com; the
# legacy usetrmnl.com host still resolves too, so accept both.
WEBHOOK_URL_PATTERN = re.compile(
    r"^https://(?:use)?trmnl\.com/api/custom_plugins/[A-Za-z0-9_-]{8,64}/?$"
)

INTERVAL_SECONDS = 600  # 10 minutes


def validate_webhook_url(url: str) -> str:
    if not WEBHOOK_URL_PATTERN.match(url or ""):
        raise SystemExit(
            "error: webhook URL must look like "
            "https://trmnl.com/api/custom_plugins/<uuid>"
        )
    return url


# --------------------------------------------------------------------------- #
# OS + credentials detection
# --------------------------------------------------------------------------- #

def detect_os() -> str:
    system = platform.system()
    if system == "Darwin":  return "mac"
    if system == "Linux":   return "linux"
    if system == "Windows": return "windows"
    raise SystemExit(f"Unsupported OS: {system}")


KEYCHAIN_SERVICE = "Claude Code-credentials"


def webhook_config_path() -> Path:
    """Where install.py stashes the webhook URL so ad-hoc `push` invocations
    (that don't inherit the scheduler's env) can still find it."""
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "Claude UNLMTD"
    elif system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home())) / "trmnl-claude-limits"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "trmnl-claude-limits"
    return base / "webhook"


def find_credentials() -> str | None:
    """Return a human-readable source string if Claude Code credentials are
    reachable — either a file path, or the macOS Keychain entry. Mirrors the
    file+keychain fallback push_usage.py uses at runtime, so the installer
    pre-flight can't reject a machine the push agent would actually work on.
    """
    for name in (".credentials.json", "credentials.json"):
        path = Path.home() / ".claude" / name
        if path.exists():
            return str(path)
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["/usr/bin/security", "find-generic-password",
                 "-s", KEYCHAIN_SERVICE, "-a", os.environ.get("USER", "")],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return f"macOS Keychain ({KEYCHAIN_SERVICE})"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return None


def log_path_for(os_name: str) -> Path:
    if os_name == "mac":
        return Path.home() / "Library" / "Logs" / "trmnl-claude-usage.log"
    if os_name == "linux":
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        return base / "trmnl-claude-usage.log"
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "trmnl-claude-usage" / "log.txt"


# --------------------------------------------------------------------------- #
# Interactive prompts
# --------------------------------------------------------------------------- #

def prompt_webhook_url() -> str:
    print()
    print(textwrap.dedent(f"""\
        =====================================================================
        Grab your TRMNL webhook URL
        =====================================================================
          1. Install the Claude UNLMTD plugin on TRMNL (or open an existing one).
          2. Open the plugin's settings page.
          3. Copy the value labelled 'Webhook URL'
             (looks like https://trmnl.com/api/custom_plugins/<uuid>).
    """))
    try:
        input("Press ENTER to open TRMNL in your browser... ")
        webbrowser.open(TRMNL_PLUGINS_URL)
    except EOFError:
        # Non-interactive stdin — skip the browser step.
        pass

    while True:
        url = input("Paste webhook URL: ").strip()
        if WEBHOOK_URL_PATTERN.match(url):
            return url
        print("  That doesn't look like a TRMNL webhook URL. Try again.\n")


# --------------------------------------------------------------------------- #
# Verify pipe by POSTing one payload
# --------------------------------------------------------------------------- #

def verify_webhook(url: str) -> None:
    payload = {
        "merge_variables": {
            "plan_tier": "Max",
            "session_percent": 0,
            "session_reset_label": "installing",
            "weekly_all_percent": 0,      "weekly_all_reset_label": "",
            "weekly_sonnet_percent": 0,   "weekly_sonnet_reset_label": "",
            "weekly_opus_percent": 0,     "weekly_opus_reset_label": "",
            "refreshed_at_label": "installer",
            "is_stale": False,
            "frame_index": 0,
        }
    }
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            # Cloudflare in front of TRMNL blocks the default Python-urllib
            # User-Agent (error 1010). Send an explicit, branded one.
            "User-Agent": (
                "trmnl-claude-limits/0.1 "
                "(+https://github.com/iosdev29/trmnl-claude-limits)"
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status >= 400:
                raise SystemExit(f"webhook returned HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        # 403/429 = TRMNL rate-limited us (typically ~1 push per 15 min per
        # webhook). Setup itself is fine; the scheduled agent will succeed on
        # its next tick. 5xx = TRMNL server hiccup, same story. Warn, keep
        # going instead of aborting the install.
        if e.code in (403, 429) or 500 <= e.code < 600:
            print(f"  (warning) webhook responded HTTP {e.code} — likely "
                  f"rate-limited or a transient TRMNL error. Install will "
                  f"proceed; the scheduler will retry on its normal cadence.")
            return
        raise SystemExit(f"webhook rejected the test payload: HTTP {e.code}")
    except urllib.error.URLError as e:
        raise SystemExit(f"couldn't reach webhook: {e.reason}")


# --------------------------------------------------------------------------- #
# Per-OS install / uninstall
# --------------------------------------------------------------------------- #

def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"


def _mac_agent_wrapper_path() -> Path:
    # Written on install so macOS Login Items shows "claude-unlmtd" (the
    # basename of ProgramArguments[0]) instead of "env" or "python3.12".
    return (Path.home() / "Library" / "Application Support"
            / "Claude UNLMTD" / "claude-unlmtd")


def detect_iana_tz() -> str | None:
    """Return the user's IANA time zone name, or None if it can't be detected.

    launchd (and by extension our LaunchAgent) runs with TZ=UTC unless we
    inject it explicitly. Without this, reset labels like "Wed 10:00" render
    in UTC for users in any other zone. `/etc/localtime` is a symlink into
    the zoneinfo tree on both macOS and Linux; parsing the suffix is the
    least-fragile cross-platform way to recover the IANA name.
    """
    if platform.system() not in ("Darwin", "Linux"):
        return None
    try:
        link = os.readlink("/etc/localtime")
    except OSError:
        return None
    marker = "/zoneinfo/"
    idx = link.find(marker)
    return link[idx + len(marker):] if idx != -1 else None


def install_mac(webhook_url: str) -> Path:
    plist_path = _mac_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path_for("mac")
    log.parent.mkdir(parents=True, exist_ok=True)

    # Write a branded wrapper. macOS Login Items shows the basename of
    # ProgramArguments[0], so pointing launchd at a file called
    # "claude-unlmtd" gives the user a recognisable entry (instead of "env"
    # from /usr/bin/env or a generic "python3.12"). Also pins the exact
    # Python interpreter that ran the installer — sidesteps launchd's PATH
    # picking up Xcode's python3 ahead of Homebrew's.
    agent = _mac_agent_wrapper_path()
    agent.parent.mkdir(parents=True, exist_ok=True)
    agent.write_text(
        "#!/bin/bash\n"
        "# Auto-generated by trmnl-claude-limits installer. Do not edit —\n"
        "# re-running the installer overwrites this file.\n"
        f'exec "{sys.executable}" "{PUSH_SCRIPT}" "$@"\n'
    )
    agent.chmod(0o755)

    # XML-escape all interpolated strings — user's $HOME could contain &, <, or >
    # (legal on macOS) and the webhook URL, though regex-validated, is still
    # untrusted at the boundary.
    agent_e   = xml_escape(str(agent))
    log_e     = xml_escape(str(log))
    webhook_e = xml_escape(webhook_url)

    tz = detect_iana_tz()
    tz_block = f"        <key>TZ</key><string>{xml_escape(tz)}</string>\n" if tz else ""

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LAUNCH_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{agent_e}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>TRMNL_WEBHOOK_URL</key><string>{webhook_e}</string>
{tz_block}    </dict>
    <key>StartInterval</key><integer>{INTERVAL_SECONDS}</integer>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>{log_e}</string>
    <key>StandardErrorPath</key><string>{log_e}</string>
</dict>
</plist>
"""
    plist_path.write_text(plist)
    subprocess.run(["launchctl", "unload", str(plist_path)],
                   stderr=subprocess.DEVNULL, check=False)
    subprocess.run(["launchctl", "load",   str(plist_path)], check=True)
    return plist_path


def uninstall_mac() -> None:
    p = _mac_plist_path()
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)],
                       stderr=subprocess.DEVNULL, check=False)
        p.unlink()
    agent = _mac_agent_wrapper_path()
    if agent.exists():
        agent.unlink()
    # Remove the "Claude UNLMTD" support dir if empty.
    try:
        agent.parent.rmdir()
    except OSError:
        pass


def _linux_unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def install_linux(webhook_url: str) -> tuple[Path, Path]:
    unit_dir = _linux_unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    service = unit_dir / f"{SYSTEMD_NAME}.service"
    timer   = unit_dir / f"{SYSTEMD_NAME}.timer"

    tz = detect_iana_tz()
    tz_line = f"Environment=TZ={tz}\n        " if tz else ""

    service.write_text(textwrap.dedent(f"""\
        [Unit]
        Description=Claude UNLMTD push
        [Service]
        Type=oneshot
        Environment=TRMNL_WEBHOOK_URL={webhook_url}
        {tz_line}ExecStart=/usr/bin/env python3 {PUSH_SCRIPT}
    """))
    timer.write_text(textwrap.dedent(f"""\
        [Unit]
        Description=Claude UNLMTD push timer
        [Timer]
        OnBootSec=1min
        OnUnitActiveSec={INTERVAL_SECONDS}s
        Unit={SYSTEMD_NAME}.service
        [Install]
        WantedBy=timers.target
    """))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now",
                    f"{SYSTEMD_NAME}.timer"], check=True)
    return service, timer


def uninstall_linux() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now",
                    f"{SYSTEMD_NAME}.timer"],
                   stderr=subprocess.DEVNULL, check=False)
    for p in (_linux_unit_dir() / f"{SYSTEMD_NAME}.service",
              _linux_unit_dir() / f"{SYSTEMD_NAME}.timer"):
        if p.exists():
            p.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"],
                   stderr=subprocess.DEVNULL, check=False)


def _windows_wrapper_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return base / "trmnl-claude-usage" / "run.cmd"


def install_windows(webhook_url: str) -> str:
    python = shutil.which("python") or shutil.which("python3") or "python"
    wrapper = _windows_wrapper_path()
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    # Write a .cmd wrapper file instead of inlining the command into /TR — user
    # $LOCALAPPDATA or Python paths containing spaces, &, %, or " otherwise
    # slip past schtasks' fragile quoting.
    wrapper.write_text(
        "@echo off\r\n"
        f'set "TRMNL_WEBHOOK_URL={webhook_url}"\r\n'
        f'"{python}" "{PUSH_SCRIPT}"\r\n'
    )
    subprocess.run([
        "schtasks", "/Create",
        "/SC", "MINUTE", "/MO", str(INTERVAL_SECONDS // 60),
        "/TN", WIN_TASK, "/TR", str(wrapper),
        "/RL", "LIMITED", "/F",
    ], check=True)
    subprocess.run(["schtasks", "/Run", "/TN", WIN_TASK], check=False)
    return WIN_TASK


def uninstall_windows() -> None:
    subprocess.run(["schtasks", "/Delete", "/TN", WIN_TASK, "/F"],
                   stderr=subprocess.DEVNULL, check=False)
    wrapper = _windows_wrapper_path()
    if wrapper.exists():
        wrapper.unlink()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--webhook-url",
                    help="Skip the interactive prompt.")
    ap.add_argument("--uninstall", action="store_true",
                    help="Remove the scheduler entry (leaves credentials alone).")
    args = ap.parse_args()

    os_name = detect_os()

    if args.uninstall:
        {"mac": uninstall_mac, "linux": uninstall_linux, "windows": uninstall_windows}[os_name]()
        cfg = webhook_config_path()
        if cfg.exists():
            cfg.unlink()
            try:
                cfg.parent.rmdir()  # only if empty
            except OSError:
                pass
        print("Uninstalled scheduler entry.")
        return 0

    print(f"→ platform: {os_name}")

    cred = find_credentials()
    if not cred:
        print()
        print("Couldn't find Claude Code credentials.")
        print("Install Claude Code (https://claude.com/download), then run:")
        print("    claude login")
        print("...and re-run this installer.")
        return 1
    print(f"→ credentials: {cred}")

    webhook_url = (
        validate_webhook_url(args.webhook_url)
        if args.webhook_url else prompt_webhook_url()
    )

    print("→ testing webhook (one POST)...")
    verify_webhook(webhook_url)
    print("→ webhook OK")

    # Persist the URL so `trmnl-claude-limits push` from a plain shell can
    # find it without needing the scheduler's env.
    cfg = webhook_config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(webhook_url + "\n")
    try:
        os.chmod(cfg, 0o600)
    except OSError:
        pass

    print(f"→ installing scheduler ({INTERVAL_SECONDS // 60} min interval)...")
    if os_name == "mac":
        p = install_mac(webhook_url)
        print(f"    LaunchAgent: {p}")
        print(f"    Log:         {log_path_for('mac')}")
    elif os_name == "linux":
        s, t = install_linux(webhook_url)
        print(f"    Service: {s}")
        print(f"    Timer:   {t}")
        print(f"    Log:     journalctl --user -u {SYSTEMD_NAME}.service")
    else:
        t = install_windows(webhook_url)
        print(f"    Scheduled task: {t}")
        print(f"    Log:            {log_path_for('windows')}")

    print()
    print("Done. First push has already fired; the next runs on schedule.")
    print("Uninstall any time with:  trmnl-claude-limits --uninstall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
