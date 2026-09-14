from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import glob
import shutil
from typing import Any


def station_points(devices: list[Any], *, test_coordinates: bool = True) -> list[dict[str, Any]]:
    points = []
    for d in devices:
        lat, lon = d["latitude"], d["longitude"]
        synthetic = lat is None or lon is None
        if synthetic and not test_coordinates:
            continue
        if synthetic:
            seed = int(hashlib.sha256(str(d["device_key"]).encode()).hexdigest()[:16], 16)
            lat = 29.35 + (seed % 450) / 1000.0
            lon = 106.25 + ((seed >> 12) % 650) / 1000.0
        points.append({"id": int(d["id"]), "label": str(d["alias"] or d["label"]), "latitude": float(lat), "longitude": float(lon), "synthetic": synthetic})
    return points


def render_station_map(points: list[dict[str, Any]], output: str) -> None:
    if not points:
        raise ValueError("No station locations available")
    # PyGMT/GMT keeps a session per process.  Uvicorn can process concurrent
    # requests in one process, so use a short-lived child process and a unique
    # session directory for each render instead of sharing GMT's temp files.
    renderer = '''
import json, os, sys
import pygmt
points = json.loads(os.environ["MSEED_STATION_POINTS"])
lons, lats = [p["longitude"] for p in points], [p["latitude"] for p in points]
pad = max(0.15, max(max(lons)-min(lons), max(lats)-min(lats)) * 0.15)
region = [min(lons)-pad, max(lons)+pad, min(lats)-pad, max(lats)+pad]
fig = pygmt.Figure()
fig.coast(region=region, projection="M15c", land="#e5e7eb", water="#bfdbfe",
          shorelines="0.5p,#4b5563", borders=["1/0.7p,#374151", "2/0.3p,#6b7280"],
          dcw="CN+g#fef3c7", resolution="i")
fig.basemap(frame=["afg", "+tStation locations"])
fig.plot(x=lons, y=lats, style="c0.32c", fill="#dc3545", pen="0.5p,white")
fig.text(x=lons, y=lats, text=[p["label"] for p in points], font="9p,Helvetica,black", justify="LM", offset="0.22c/0c")
fig.savefig(sys.argv[1], dpi=150)
'''
    output_dir = Path(output).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    # Ghostscript can be confined by host policy when reading PostScript below
    # /var/lib.  Keep its short-lived GMT session in the service's private /tmp;
    # only the final PNG is written to persistent portal state.
    session_dir = tempfile.mkdtemp(prefix="mseed-gmt-")
    render_output = os.path.join(session_dir, "station-map.png")
    try:
        env = os.environ.copy()
        env.update({
            "GMT_LIBRARY_PATH": "/usr/lib/x86_64-linux-gnu",
            "GMT_USERDIR": session_dir,
            # Ghostscript also consults HOME/TMPDIR for its own initialization.
            # The systemd service has a restricted home, so keep every renderer
            # scratch/cache path under the portal's writable state directory.
            "HOME": session_dir,
            "TMPDIR": session_dir,
            "TMP": session_dir,
            "TEMP": session_dir,
            "XDG_CACHE_HOME": session_dir,
            "MSEED_STATION_POINTS": json.dumps(points),
        })
        subprocess.run([sys.executable, "-c", renderer, render_output], env=env, check=True, capture_output=True, text=True)
        # GMT/Ghostscript is allowed to write in /tmp but may be denied access to
        # the portal state directory by host security policy.  The portal process
        # itself owns the final cache directory, so publish the finished image.
        shutil.move(render_output, output)
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "no renderer output").strip()
        bb_files = glob.glob(os.path.join(session_dir, "**", "*.bb"), recursive=True)
        if bb_files:
            try:
                ghostscript_error = Path(bb_files[0]).read_text(errors="replace").strip()
                if ghostscript_error:
                    details += f"; ghostscript={ghostscript_error}"
            except OSError:
                pass
        raise RuntimeError(f"PyGMT renderer failed; session={session_dir}; details={details}") from exc
    else:
        shutil.rmtree(session_dir, ignore_errors=True)
