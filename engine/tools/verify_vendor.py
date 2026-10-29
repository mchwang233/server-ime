#!/usr/bin/env python3
"""Verify pinned vendored inputs without contacting the network."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def verify():
    lock = json.loads((ROOT / "vendor.lock.json").read_text())
    failures = []
    for item in lock["files"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["size"]:
            failures.append(item["path"] + ": missing or wrong size")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            failures.append(item["path"] + ": SHA-256 mismatch")
    if failures:
        raise RuntimeError("\n".join(failures))
    return {"employee_id": "engine", "verified_files": len(lock["files"]), "ok": True}


if __name__ == "__main__":
    try:
        print(json.dumps(verify()))
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
