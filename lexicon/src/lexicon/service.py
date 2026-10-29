"""Compose base + personal entries and rebuild the derived native user table."""
import os
from pathlib import Path

from . import engine as engine_bridge
from .errors import LexiconError
from .native import Libpinyin
from .records import (
    MAX_COUNT, SCHEMA_NATIVE, entry_key, read_json, read_jsonl, sha256_file, utcnow,
    validate_entry, write_json_atomic,
)


def load_base(lexicon_path, manifest_path=None):
    lexicon_path = Path(lexicon_path)
    entries = [validate_entry(row, require_source=True, kinds=("base",))
               for row in read_jsonl(lexicon_path, code="invalid_base")]
    identity = {
        "lexicon_version": None,
        "sha256": sha256_file(lexicon_path),
        "entry_count": len(entries),
    }
    if manifest_path and Path(manifest_path).is_file():
        manifest = read_json(Path(manifest_path), code="invalid_base")
        identity["lexicon_version"] = manifest.get("lexicon_version")
        recorded = (manifest.get("files", {}).get("lexicon-v1.jsonl") or {}).get("sha256")
        if recorded and recorded != identity["sha256"]:
            raise LexiconError("invalid_base", "base lexicon does not match its manifest",
                               {"recorded": recorded, "actual": identity["sha256"]})
    return entries, identity


def merged_entries(base, personal):
    """Merge base and personal entries; personal frequency adds to the base prior.

    Keeping the base count avoids lowering an existing word's ranking when a user
    learns it once.  The personal kind is kept for diagnostics; libpinyin only
    consumes the combined frequency.
    """
    merged = {}
    for entry in base:
        merged[entry_key(entry["text"], entry["pinyin"])] = {
            "text": entry["text"], "pinyin": entry["pinyin"], "count": entry["count"],
            "kind": "base",
        }
    for entry in personal:
        key = entry_key(entry["text"], entry["pinyin"])
        current = merged.get(key)
        count = entry["count"] if current is None else min(MAX_COUNT, current["count"] + entry["count"])
        merged[key] = {
            "text": entry["text"], "pinyin": entry["pinyin"], "count": count,
            "kind": entry["kind"],
        }
    return [merged[key] for key in sorted(merged)]


def rebuild_native(store, base_lexicon, *, base_manifest=None, runtime_dir=None,
                   system_data=None, probe=0):
    runtime, data = engine_bridge.engine_paths(system_data, runtime_dir)
    base, base_identity = load_base(base_lexicon, base_manifest)
    with store.lock(exclusive=True):
        store.reload()
        entries = merged_entries(base, list(store.entries.values()))
        before = engine_bridge.fingerprint_data(data)
        lib = Libpinyin(runtime, data)
        result = lib.build_into(store.native_dir, entries)
        exported = lib.export(store.native_dir)
        if {(row["text"], row["pinyin"]) for row in exported} != {(row["text"], row["pinyin"]) for row in entries}:
            raise LexiconError("native_build_failed", "exported table differs from the merged lexicon")
        after = engine_bridge.fingerprint_data(data)
        if before != after:
            raise LexiconError("engine_incompatible", "engine data changed during user dictionary build")
        probe_rows = []
        if probe:
            engine = engine_bridge.open_engine(user_dir=store.native_dir)
            try:
                probe_rows = engine_bridge.probe_entries(engine, list(store.entries.values()), limit=probe)
            finally:
                engine.close()
        manifest = {
            "schema": SCHEMA_NATIVE,
            "kind": "user",
            "built_at": utcnow(),
            "store_id": store.meta.get("store_id"),
            "store_revision": store.meta.get("revision"),
            "entry_count": len(entries),
            "base_entry_count": len(base),
            "personal_entry_count": len(store.entries),
            "base": base_identity,
            "merge": "one record per (text, pinyin); personal frequency adds to the base prior, personal kind is kept",
            "files": result["files"],
            "exported": len(exported),
            "engine": {
                "backend": "libpinyin",
                "backend_version": "2.6.0",
                "runtime_dir": str(runtime),
                "system_data": str(data),
                "system_data_files": before,
            },
            "probe": probe_rows or None,
        }
        write_json_atomic(store.native_manifest_path, manifest)
    return {"ok": True, "native": str(store.native_dir), "entries": len(entries),
            "base": len(base), "personal": len(store.entries), "store_revision": store.meta.get("revision"),
            "files": {name: info["sha256"] for name, info in result["files"].items()},
            "probe": probe_rows or None}


def list_native(store, runtime_dir=None, system_data=None):
    runtime, data = engine_bridge.engine_paths(system_data, runtime_dir)
    if not store.native_dir.is_dir():
        raise LexiconError("native_unavailable", "no native dictionary has been built")
    rows = Libpinyin(runtime, data).export(store.native_dir)
    return {"ok": True, "entries": rows, "count": len(rows)}
