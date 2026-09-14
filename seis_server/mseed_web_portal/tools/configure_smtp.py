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
