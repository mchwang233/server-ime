#!/usr/bin/env python3
"""Compile data/base/lexicon-v1.jsonl into a libpinyin user dictionary.

The output directory is what the engine's user-directory slot loads.  It is
derived data: rebuild it from the immutable JSONL, never edit the binary files.
"""
import argparse
import json
import platform
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from lexicon import engine as engine_bridge  # noqa: E402
from lexicon.errors import LexiconError  # noqa: E402
from lexicon.native import Libpinyin  # noqa: E402
from lexicon.records import (  # noqa: E402
    SCHEMA_NATIVE, read_jsonl, sha256_file, utcnow, validate_entry, write_json_atomic,
)

BASE = ROOT / "data/base/lexicon-v1.jsonl"
BASE_MANIFEST = ROOT / "data/base/manifest.json"
OUT = ROOT / "build/base-v1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--runtime-dir", default="")
    parser.add_argument("--system-data", default="")
    parser.add_argument("--no-probe", action="store_true")
    args = parser.parse_args()
    runtime, data = engine_bridge.engine_paths(args.system_data or None, args.runtime_dir or None)
    try:
        entries = [validate_entry(row, require_source=True, kinds=("base",)) for row in read_jsonl(BASE)]
        base_manifest = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
        before = engine_bridge.fingerprint_data(data)
        lib = Libpinyin(runtime, data)
        destination = Path(args.out).resolve() / "native"
        result = lib.build_into(destination, entries)
        exported = lib.export(destination)
        expected = {(row["text"], row["pinyin"]) for row in entries}
        actual = {(row["text"], row["pinyin"]) for row in exported}
        if expected != actual:
            raise LexiconError("native_build_failed", "exported table differs from the base lexicon",
                               {"missing": sorted(expected - actual)[:20], "extra": sorted(actual - expected)[:20]})
        probe = None
        if not args.no_probe:
            engine = engine_bridge.open_engine(user_dir=destination)
            try:
                probe = engine_bridge.probe_entries(engine, entries)
            finally:
                engine.close()
            top1 = sum(row["top1"] for row in probe)
            top5 = sum(row["top5"] for row in probe)
        after = engine_bridge.fingerprint_data(data)
        if before != after:
            raise LexiconError("engine_incompatible", "engine data changed while building the user dictionary")
        manifest = {
            "schema": SCHEMA_NATIVE,
            "kind": "base",
            "lexicon_version": base_manifest["lexicon_version"],
            "lexicon_sha256": sha256_file(BASE),
            "entry_count": len(entries),
            "built_at": utcnow(),
            "builder": {"tool": "lexicon/tools/build_native.py", "python": platform.python_version()},
            "engine": {
                "backend": "libpinyin",
                "backend_version": "2.6.0",
                "runtime_dir": str(runtime),
                "system_data": str(data),
                "system_data_files": before,
            },
            "native": {
                "directory": "native",
                "files": result["files"],
                "exported": result["exported"],
                "missing": 0,
            },
            "probe": None if probe is None else {
                "entries": len(probe),
                "top1": top1,
                "top5": top5,
                "failures": [row for row in probe if not row["top5"]],
            },
        }
        write_json_atomic(Path(args.out).resolve() / "manifest.json", manifest)
        print(json.dumps({
            "ok": True,
            "native": str(destination),
            "entries": len(entries),
            "exported": result["exported"],
            "probe": None if probe is None else {"top1": top1, "top5": top5, "total": len(probe)},
            "files": {name: info["sha256"] for name, info in result["files"].items()},
        }, ensure_ascii=False))
        return 0
    except LexiconError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
