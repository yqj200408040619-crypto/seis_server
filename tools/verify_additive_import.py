#!/usr/bin/env python3
"""Verify archived source hashes and byte/mode preservation of the original Git tree."""
from __future__ import annotations
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

def verify(repo):
    meta = json.loads((repo / 'docs/SOURCE_ARCHIVES.json').read_text())
    baseline = meta['baseline_commit']
    tree = subprocess.check_output(['git','ls-tree','-rz',baseline],cwd=repo)
    errors = []
    checked = 0
    for entry in tree.split(b'\0'):
        if not entry: continue
        header, path_b = entry.split(b'\t',1)
        mode, kind, oid = header.split()
        path = repo / os.fsdecode(path_b)
        if kind != b'blob':
            errors.append({'path':os.fsdecode(path_b),'reason':'unsupported_baseline_entry'})
            continue
        try:
            data = os.fsencode(os.readlink(path)) if mode == b'120000' else path.read_bytes()
            actual = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            if actual != oid.decode():
                errors.append({'path':os.fsdecode(path_b),'reason':'original_bytes_changed'})
            if mode in {b'100644',b'100755'}:
                executable = bool(path.stat().st_mode & 0o111)
                if executable != (mode==b'100755'):
                    errors.append({'path':os.fsdecode(path_b),'reason':'original_mode_changed'})
            checked += 1
        except OSError as e:
            errors.append({'path':os.fsdecode(path_b),'reason':type(e).__name__})
    imported = 0
    with (repo / 'docs/CODE_PROVENANCE.csv').open(newline='') as f:
        for row in csv.DictReader(f):
            if row['status'] != 'imported_original_bytes': continue
            path = repo / row['target_path']
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if actual != row['original_sha256']:
                    errors.append({'path':row['target_path'],'reason':'import_hash_mismatch'})
                imported += 1
            except OSError as e:
                errors.append({'path':row['target_path'],'reason':type(e).__name__})
    # Staged or committed additions are allowed; modifying/deleting old paths is not.
    for entry in subprocess.check_output(['git','diff','--name-status',baseline],cwd=repo,text=True).splitlines():
        status,path = entry.split('\t',1)
        if status != 'A':
            errors.append({'path':path,'reason':'non_additive_git_diff','status':status})
    report = {'baseline_commit':baseline,'original_files_verified':checked,
              'imported_source_files_verified':imported,'errors':errors,
              'passed':not errors}
    return report

if __name__=='__main__':
    result=verify(Path(__file__).resolve().parents[1])
    print(json.dumps(result,ensure_ascii=False,indent=2))
    sys.exit(0 if result['passed'] else 1)
