"""Shared bootstrap: make the real mseed_tcp_server package importable with
stubbed heavy submodules, then import the genuine server module.

Usage (from a test script in this directory):

    import conftest_env as env
    server = env.load_server()        # real server.py, stubs installed
    cfg = env.make_config(**overrides)
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PKG_DIR = REPO / "mseed_tcp_server" / "mseed_tcp_server"

import _stubs  # noqa: E402


def _load_real_submodule(name: str):
    """Load config.py from disk as mseed_tcp_server.<name> (pure stdlib module)."""
    full = f"mseed_tcp_server.{name}"
    path = PKG_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def load_server():
    # 1. install the package object + stub submodules (db/mseed/util)
    _stubs.install_all()
    # 2. load the REAL config submodule (pure stdlib, no heavy deps)
    _load_real_submodule("config")
    # 3. load the REAL server submodule from disk
    full = "mseed_tcp_server.server"
    path = PKG_DIR / "server.py"
    spec = importlib.util.spec_from_file_location(full, path)
    server = importlib.util.module_from_spec(spec)
    sys.modules[full] = server
    spec.loader.exec_module(server)
    return server


def make_config(server):
    """Build an AppConfig from the real config module with test overrides via load_config."""
    cfg_mod = sys.modules["mseed_tcp_server.config"]
    return cfg_mod
