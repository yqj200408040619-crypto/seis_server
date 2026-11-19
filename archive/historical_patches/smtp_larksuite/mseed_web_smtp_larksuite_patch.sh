#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/mseed-web-portal"
CONFIG_DIR="/etc/mseed-web-portal"
ALERTS_INI="$CONFIG_DIR/alerts.ini"
PY=""
TS="$(date +%Y%m%d_%H%M%S)"

if [ -x "/opt/miniforge3/envs/mseed-web/bin/python" ]; then
  PY="/opt/miniforge3/envs/mseed-web/bin/python"
elif [ -x "$APP_DIR/.venv/bin/python" ]; then
  PY="$APP_DIR/.venv/bin/python"
else
  echo "ERROR: Python environment not found. Expected /opt/miniforge3/envs/mseed-web/bin/python or $APP_DIR/.venv/bin/python" >&2
  exit 1
fi

if [ ! -d "$APP_DIR/app" ]; then
  echo "ERROR: $APP_DIR/app not found. Is the Web Portal installed?" >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR" "$APP_DIR/tools"

echo "== SMTP patch for mseed-web-portal: LarkSuite / Feishu Mail support =="
echo "Python: $PY"

# Backup files.
[ -f "$APP_DIR/app/stage2.py" ] && cp -a "$APP_DIR/app/stage2.py" "$APP_DIR/app/stage2.py.bak_smtp_$TS"
[ -f "$ALERTS_INI" ] && cp -a "$ALERTS_INI" "$ALERTS_INI.bak_smtp_$TS"

# Ensure alerts.ini exists.
if [ ! -f "$ALERTS_INI" ]; then
cat > "$ALERTS_INI" <<'INICONF'
[thresholds]
offline_seconds = 600
channel_missing_seconds = 600
gap_min_seconds = 1.0
repeat_silence_seconds = 3600
expected_components = BHZ,BHN,BHE

[smtp]
enabled = false
host = smtp.larksuite.com
port = 465
security = ssl
username = WebPortal@geoplusgmbh.de
password =
from_addr = WebPortal@geoplusgmbh.de
to_addrs = WebPortal@geoplusgmbh.de
use_tls = false
timeout_seconds = 20

[email]
subject_prefix = [Seismic Portal]
INICONF
chmod 600 "$ALERTS_INI"
fi

# Patch stage2.py send_alert_email() to support SSL 465, STARTTLS 587 and no-TLS.
if [ ! -f "$APP_DIR/app/stage2.py" ]; then
  echo "ERROR: $APP_DIR/app/stage2.py not found. Stage 2 patch must be installed first." >&2
  exit 1
fi

PYTHONPATH="$APP_DIR" "$PY" - <<'PYCODE'
from pathlib import Path
import re

p = Path("/opt/mseed-web-portal/app/stage2.py")
s = p.read_text()

new_func = r'''def send_alert_email(config: configparser.ConfigParser, *, title: str, message: str) -> bool:
    """Send an alert email using SMTP.

    Supported configuration in /etc/mseed-web-portal/alerts.ini:
      [smtp]
      enabled = true
      host = smtp.larksuite.com
      port = 465
      security = ssl        # ssl | starttls | none
      username = WebPortal@geoplusgmbh.de
      password = ...
      from_addr = WebPortal@geoplusgmbh.de
      to_addrs = user1@example.com,user2@example.com
      timeout_seconds = 20

    For compatibility with the earlier Stage 2 config, use_tls=true is still
    accepted and maps to security=starttls unless port=465.
    """
    if not config.getboolean("smtp", "enabled", fallback=False):
        return False

    import ssl

    host = config.get("smtp", "host", fallback="").strip()
    port = config.getint("smtp", "port", fallback=587)
    username = config.get("smtp", "username", fallback="").strip()
    password = config.get("smtp", "password", fallback="")
    from_addr = config.get("smtp", "from_addr", fallback=username).strip() or username
    to_addrs = [x.strip() for x in config.get("smtp", "to_addrs", fallback="").split(",") if x.strip()]
    timeout_seconds = config.getint("smtp", "timeout_seconds", fallback=20)

    security = config.get("smtp", "security", fallback="").strip().lower()
    if not security:
        # Backward compatibility for old use_tls field.
        use_tls = config.getboolean("smtp", "use_tls", fallback=True)
        security = "ssl" if port == 465 else ("starttls" if use_tls else "none")
    if security == "tls":
        security = "starttls"
    if security not in {"ssl", "starttls", "none"}:
        raise ValueError(f"Invalid smtp.security={security!r}. Use ssl, starttls, or none.")

    prefix = config.get("email", "subject_prefix", fallback="[Seismic Portal]").strip()
    if not host or not from_addr or not to_addrs:
        raise ValueError("SMTP host, from_addr, and to_addrs must be configured.")

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = f"{prefix} {title}"
    msg.set_content(message)

    context = ssl.create_default_context()
    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=timeout_seconds, context=context) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=timeout_seconds) as smtp:
            smtp.ehlo()
            if security == "starttls":
                smtp.starttls(context=context)
                smtp.ehlo()
            if username:
                smtp.login(username, password)
            smtp.send_message(msg)
    return True
'''

pat = re.compile(r"def send_alert_email\(config: configparser\.ConfigParser, \*, title: str, message: str\) -> bool:\n.*?\n\ndef check_devices_once", re.S)
m = pat.search(s)
if not m:
    raise SystemExit("Could not find existing send_alert_email() block. Is Stage 2 installed and unmodified?")
s = s[:m.start()] + new_func + "\n\ndef check_devices_once" + s[m.end():]
p.write_text(s)
print("patched send_alert_email() in", p)
PYCODE

# configure_smtp.py
cat > "$APP_DIR/tools/configure_smtp.py" <<'PYCODE'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import getpass
import os
from pathlib import Path

DEFAULT_PATH = "/etc/mseed-web-portal/alerts.ini"


def ensure_sections(c: configparser.ConfigParser) -> None:
    if not c.has_section("thresholds"):
        c.add_section("thresholds")
        c.set("thresholds", "offline_seconds", "600")
        c.set("thresholds", "channel_missing_seconds", "600")
        c.set("thresholds", "gap_min_seconds", "1.0")
        c.set("thresholds", "repeat_silence_seconds", "3600")
        c.set("thresholds", "expected_components", "BHZ,BHN,BHE")
    if not c.has_section("smtp"):
        c.add_section("smtp")
    if not c.has_section("email"):
        c.add_section("email")
        c.set("email", "subject_prefix", "[Seismic Portal]")


def main() -> int:
    ap = argparse.ArgumentParser(description="Configure SMTP for Seismic Data Portal alerts.")
    ap.add_argument("--config", default=DEFAULT_PATH)
    ap.add_argument("--host", default="smtp.larksuite.com")
    ap.add_argument("--port", type=int, default=465)
    ap.add_argument("--security", choices=["ssl", "starttls", "none"], default="ssl")
    ap.add_argument("--username", default="WebPortal@geoplusgmbh.de")
    ap.add_argument("--from-addr", default="WebPortal@geoplusgmbh.de")
    ap.add_argument("--to-addrs", default="WebPortal@geoplusgmbh.de", help="Comma-separated recipients.")
    ap.add_argument("--subject-prefix", default="[Seismic Portal]")
    ap.add_argument("--timeout-seconds", type=int, default=20)
    ap.add_argument("--password", default=None, help="Avoid using this in shell history. Prefer interactive input.")
    ap.add_argument("--keep-password", action="store_true", help="Keep existing password if present.")
    ap.add_argument("--disable", action="store_true")
    args = ap.parse_args()

    path = Path(args.config)
    c = configparser.ConfigParser()
    c.read(path)
    ensure_sections(c)

    old_password = c.get("smtp", "password", fallback="")
    password = args.password
    if args.keep_password and old_password:
        password = old_password
    if password is None and not args.disable:
        prompt = "SMTP password"
        if old_password:
            prompt += " [press Enter to keep existing]"
        prompt += ": "
        entered = getpass.getpass(prompt)
        if entered:
            password = entered
        elif old_password:
            password = old_password
        else:
            raise SystemExit("SMTP password is required unless --disable is used.")

    c.set("smtp", "enabled", "false" if args.disable else "true")
    c.set("smtp", "host", args.host)
    c.set("smtp", "port", str(args.port))
    c.set("smtp", "security", args.security)
    c.set("smtp", "username", args.username)
    c.set("smtp", "from_addr", args.from_addr)
    c.set("smtp", "to_addrs", args.to_addrs)
    c.set("smtp", "timeout_seconds", str(args.timeout_seconds))
    # Keep legacy field for compatibility with older code paths.
    c.set("smtp", "use_tls", "true" if args.security == "starttls" else "false")
    if password is not None:
        c.set("smtp", "password", password)
    elif not c.has_option("smtp", "password"):
        c.set("smtp", "password", "")
    c.set("email", "subject_prefix", args.subject_prefix)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        c.write(f)
    os.chmod(path, 0o600)

    print("SMTP configuration saved:")
    print(f"  config:   {path}")
    print(f"  enabled:  {c.get('smtp', 'enabled')}")
    print(f"  host:     {c.get('smtp', 'host')}")
    print(f"  port:     {c.get('smtp', 'port')}")
    print(f"  security: {c.get('smtp', 'security')}")
    print(f"  username: {c.get('smtp', 'username')}")
    print(f"  from:     {c.get('smtp', 'from_addr')}")
    print(f"  to:       {c.get('smtp', 'to_addrs')}")
    print("  password: [stored, hidden]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PYCODE
chmod +x "$APP_DIR/tools/configure_smtp.py"

# test_smtp.py
cat > "$APP_DIR/tools/test_smtp.py" <<'PYCODE'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import sys
import time

sys.path.insert(0, "/opt/mseed-web-portal")

from app import stage2  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a test SMTP email using alerts.ini.")
    ap.add_argument("--config", default="/etc/mseed-web-portal/alerts.ini")
    ap.add_argument("--to", default=None, help="Override to_addrs for this test only.")
    ap.add_argument("--title", default="SMTP test")
    ap.add_argument("--message", default=None)
    args = ap.parse_args()

    c = configparser.ConfigParser()
    c.read(args.config)
    if args.to:
        if not c.has_section("smtp"):
            c.add_section("smtp")
        c.set("smtp", "to_addrs", args.to)
    msg = args.message or f"This is a test email from Seismic Data Portal. Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
    ok = stage2.send_alert_email(c, title=args.title, message=msg)
    print("SMTP test sent" if ok else "SMTP disabled or not sent")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
PYCODE
chmod +x "$APP_DIR/tools/test_smtp.py"

# compile and restart services if present.
PYTHONPATH="$APP_DIR" "$PY" -m py_compile "$APP_DIR/app/stage2.py" "$APP_DIR/tools/configure_smtp.py" "$APP_DIR/tools/test_smtp.py"

# Do not force prompt during patch. Print exact command to configure securely.
echo
cat <<EOF
SMTP patch installed.

Next, configure the mailbox interactively. The password will not be displayed:

sudo PYTHONPATH=$APP_DIR $PY $APP_DIR/tools/configure_smtp.py \\
  --host smtp.larksuite.com \\
  --port 465 \\
  --security ssl \\
  --username WebPortal@geoplusgmbh.de \\
  --from-addr WebPortal@geoplusgmbh.de \\
  --to-addrs WebPortal@geoplusgmbh.de

Then test sending one email:

sudo PYTHONPATH=$APP_DIR $PY $APP_DIR/tools/test_smtp.py --to WebPortal@geoplusgmbh.de

After test success, restart the alert timer:

sudo systemctl restart mseed-alert-worker.timer 2>/dev/null || true
sudo systemctl list-timers 'mseed-*'
EOF
