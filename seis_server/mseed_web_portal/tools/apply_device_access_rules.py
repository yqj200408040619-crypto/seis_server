#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
sys.path.insert(0, "/opt/mseed-web-portal")
from app import app_db  # noqa: E402
from app.config import load_settings  # noqa: E402

settings = load_settings(os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini"))
app_db.init_db(settings.app_db)
changed = app_db.apply_customer_device_rules_to_existing(settings.app_db)
print(f"applied access rules, changed devices={changed}")
