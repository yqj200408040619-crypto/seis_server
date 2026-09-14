#!/usr/bin/env python3
"""Verify and print the upstream account identity without exposing its token."""
from __future__ import annotations
import argparse
import getpass
import sys
sys.path.insert(0, "/opt/mseed-web-portal")
from app.upstream_identity import acquire_identity

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", required=True)
parser.add_argument("--username", required=True)
args = parser.parse_args()
identity = acquire_identity(args.base_url, args.username, getpass.getpass("Upstream password: "))
print({"username": identity.username, "is_super": identity.is_super, "expires_in": identity.expires_in})
