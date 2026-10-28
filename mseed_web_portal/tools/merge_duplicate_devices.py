#!/usr/bin/env python3
"""Logically merge duplicate instrument devices whose stored time ranges do NOT
overlap, without touching any .h5 file.

For each device_key that has more than one active device row, this tool:
  * computes each backing file's stored [min_start, max_end] range,
  * picks a PRIMARY device (the one with the most records),
  * attaches every OTHER device whose range is disjoint from the primary (and
    from already-chosen members) as a merge member of the primary,
  * deactivates the merged member device rows (hidden, not deleted),
leaving any device whose range OVERLAPS the primary as its own separate device.

The portal then presents one logical device per device_key that reads across
all its member files.  Everything is reversible with --undo.

Usage:
  merge_duplicate_devices.py            # dry-run: show the plan, change nothing
  merge_duplicate_devices.py --apply    # perform the merge
  merge_duplicate_devices.py --undo     # reverse ALL merges (reactivate rows)
  merge_duplicate_devices.py --min-records N   # ignore files with < N records
                                               # (default 1; skips empty files)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, "/opt/mseed-web-portal")

import h5py  # noqa: E402
import numpy as np  # noqa: E402

from app import app_db  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.data_reader import open_h5_read, _has_index, _legacy_record_datasets  # noqa: E402


def fmt(u):
    if u is None:
        return "-"
    return dt.datetime.utcfromtimestamp(u).strftime("%Y-%m-%d %H:%M:%S")


def file_range(path: str):
    """Return (min_start, max_end, total_records) across all streams, dual-layout."""
    if not path or not os.path.exists(path):
        return (None, None, 0)
    mn = mx = None
    total = 0
    try:
        with open_h5_read(path) as h:
            for k in h.keys():
                g = h[k]
                if not isinstance(g, h5py.Group):
                    continue
                if _has_index(g) and g["index"].shape[0]:
                    idx = g["index"][:]
                    total += int(idx.shape[0])
                    su = idx["start_unix"]
                    eu = idx["end_unix"]
                    smn = float(np.min(su))
                    euv = eu[eu > 0]
                    smx = float(np.max(euv)) if euv.size else float(np.max(su))
                    mn = smn if mn is None else min(mn, smn)
                    mx = smx if mx is None else max(mx, smx)
                for name in _legacy_record_datasets(g):
                    ds = g[name]
                    s = float(ds.attrs.get("start_unix"))
                    e = float(ds.attrs.get("end_unix", -1.0))
                    e = e if e > 0 else s
                    total += 1
                    mn = s if mn is None else min(mn, s)
                    mx = e if mx is None else max(mx, e)
    except Exception as exc:
        print(f"  ! could not read {path}: {exc}")
        return (None, None, 0)
    return (mn, mx, total)


def disjoint(a, b):
    """True if ranges a=(mn,mx) and b=(mn,mx) do not overlap in time."""
    return a[1] < b[0] or b[1] < a[0]


def plan_merges(app_db_path, min_records):
    from collections import defaultdict
    conn = app_db.connect(app_db_path)
    rows = [dict(r) for r in conn.execute(
        "SELECT id,label,device_key,db_path,client_ip FROM devices WHERE is_active = 1 ORDER BY device_key,id")]
    conn.close()

    groups = defaultdict(list)
    for r in rows:
        groups[r["device_key"]].append(r)

    plans = []  # list of dict: primary, members[], skipped[]
    for dk, items in groups.items():
        if len(items) < 2:
            continue
        enriched = []
        for r in items:
            mn, mx, total = file_range(r["db_path"])
            enriched.append({**r, "mn": mn, "mx": mx, "total": total})
        # candidates = usable (have a real range and enough records)
        usable = [e for e in enriched if e["total"] >= min_records and e["mn"] is not None and e["mx"] is not None and e["mx"] > 0]
        junk = [e for e in enriched if e not in usable]
        if len(usable) < 2:
            continue
        # primary = most records
        usable.sort(key=lambda e: e["total"], reverse=True)
        primary = usable[0]
        members = []
        overlapped = []
        accepted_ranges = [(primary["mn"], primary["mx"])]
        for cand in usable[1:]:
            crange = (cand["mn"], cand["mx"])
            if all(disjoint(crange, ar) for ar in accepted_ranges):
                members.append(cand)
                accepted_ranges.append(crange)
            else:
                overlapped.append(cand)
        if members:
            plans.append({"device_key": dk, "primary": primary,
                          "members": members, "overlapped": overlapped, "junk": junk})
    return plans


def print_plan(plans):
    if not plans:
        print("No mergeable duplicate devices found.")
        return
    for p in plans:
        pr = p["primary"]
        print(f"\ndevice_key={p['device_key']}")
        print(f"  PRIMARY  id={pr['id']:<3} ip={str(pr['client_ip']):<16} records={pr['total']:<6} "
              f"[{fmt(pr['mn'])} .. {fmt(pr['mx'])}]  {os.path.basename(pr['db_path'])}")
        for m in p["members"]:
            print(f"  + MERGE  id={m['id']:<3} ip={str(m['client_ip']):<16} records={m['total']:<6} "
                  f"[{fmt(m['mn'])} .. {fmt(m['mx'])}]  {os.path.basename(m['db_path'])}")
        for o in p["overlapped"]:
            print(f"  = KEEP SEPARATE (overlaps primary) id={o['id']} "
                  f"[{fmt(o['mn'])} .. {fmt(o['mx'])}]  {os.path.basename(o['db_path'])}")
        for j in p["junk"]:
            print(f"  . skip (empty/too-few/epoch-0) id={j['id']} records={j['total']} "
                  f"{os.path.basename(j['db_path'])}")


def apply_plan(app_db_path, plans):
    for p in plans:
        pr = p["primary"]
        for m in p["members"]:
            app_db.add_device_member(app_db_path, int(pr["id"]), m["db_path"],
                                     m["device_key"], int(m["id"]))
            app_db.set_device_active(app_db_path, int(m["id"]), False)
            print(f"merged device id={m['id']} into primary id={pr['id']} ({p['device_key']})")
    print(f"\nApplied {sum(len(p['members']) for p in plans)} merge(s).")


def undo_all(app_db_path):
    mappings = app_db.all_merge_mappings(app_db_path)
    if not mappings:
        print("No merge mappings to undo.")
        return
    primaries = sorted({int(m["primary_device_id"]) for m in mappings})
    reactivated = 0
    for m in mappings:
        mdid = m["member_device_id"]
        if mdid is not None:
            app_db.set_device_active(app_db_path, int(mdid), True)
            reactivated += 1
    for pid in primaries:
        app_db.clear_device_members(app_db_path, pid)
    print(f"Undo complete: cleared {len(mappings)} mapping(s), reactivated {reactivated} device row(s).")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.environ.get("MSEED_WEB_CONFIG", "/etc/mseed-web-portal/portal.ini"))
    ap.add_argument("--apply", action="store_true", help="perform the merge (default is dry-run)")
    ap.add_argument("--undo", action="store_true", help="reverse ALL merges and reactivate hidden rows")
    ap.add_argument("--min-records", type=int, default=1, help="ignore files with fewer than N records")
    args = ap.parse_args()

    settings = load_settings(args.config)
    app_db.init_db(settings.app_db)
    app_db.migrate_device_merge_members(settings.app_db)

    if args.undo:
        undo_all(settings.app_db)
        return 0

    plans = plan_merges(settings.app_db, args.min_records)
    print_plan(plans)
    if args.apply:
        print("\n--- applying ---")
        apply_plan(settings.app_db, plans)
    else:
        print("\n(dry-run; re-run with --apply to perform the merge, or --undo to reverse)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
