#!/usr/bin/env python3
from __future__ import annotations
import re
from pathlib import Path

BASE = Path("/opt/mseed-web-portal")
TARGETS = [BASE / "app" / "templates", BASE / "app" / "static", BASE / "app"]
CHINESE = re.compile(r"[\u4e00-\u9fff]")

IGNORE_SUFFIX = {".pyc", ".db", ".sqlite", ".mseed", ".png", ".jpg", ".jpeg", ".gif", ".woff", ".woff2"}
FILES = []
for root in TARGETS:
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() not in IGNORE_SUFFIX:
                if "__pycache__" not in str(p):
                    FILES.append(p)

seen = set()
hits = []
for p in sorted(set(FILES)):
    try:
        txt = p.read_text(errors="ignore")
    except Exception:
        continue
    for i, line in enumerate(txt.splitlines(), 1):
        if CHINESE.search(line):
            item = (str(p.relative_to(BASE)), i, line.strip()[:240])
            if item not in seen:
                seen.add(item)
                hits.append(item)

print(f"Chinese-containing source lines: {len(hits)}")
for rel, line_no, line in hits[:400]:
    print(f"{rel}:{line_no}: {line}")
if len(hits) > 400:
    print(f"... truncated, total {len(hits)} lines")
print()
print("Note: Chinese source strings are acceptable for zh mode. The browser console command")
print("window.mseedI18N.auditRemainingChinese() checks whether any Chinese remains visible in English mode.")
