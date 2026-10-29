"""Portable user-data export/import, legacy migration and backups.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import re
import shutil
import uuid
from pathlib import Path

from .errors import LexiconError
from .records import (
    MAX_ENTRIES, SCHEMA_BUNDLE, SCHEMA_USER, canonical_bytes, entry_key,
    normalize_pinyin, read_json, read_jsonl, sha256_bytes, sha256_file, utcnow,
    validate_entry, validate_text, write_json_atomic, write_jsonl_atomic,
)

SCHEMA_BACKUP = "ime-lexicon-backup/1"
BUNDLE_RE = re.compile(r"ime-lexicon-user-bundle/(\d+)\Z")
SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")


def _bundle_body(bundle):
    """Payload covered by the checksum.

    Store identity and the learning switch are deliberately excluded so that a
    user's export keeps the same payload checksum after import into another
    store, while entries and compatibility are fully protected.
    """
    return {key: value for key, value in bundle.items()
            if key not in ("checksum", "producer", "exported_at", "source", "learning")}


def _checksum(bundle):
    return sha256_bytes(canonical_bytes(_bundle_body(bundle)))


def export_bundle(store, out_path):
    snapshot = store.snapshot()
    entries = sorted(snapshot["entries"], key=lambda row: (row["text"], row["pinyin"]))
    bundle = {
        "format": SCHEMA_BUNDLE,
        "producer": {"component": "lexicon", "version": "0.1.0", "employee_id": "lexicon"},
        "exported_at": utcnow(),
        "source": {
            "schema": snapshot["meta"].get("schema"),
            "store_id": snapshot["meta"].get("store_id"),
            "revision": snapshot["meta"].get("revision"),
            "base": snapshot["meta"].get("base"),
        },
        "compatibility": {"min_reader": "1.0", "max_reader": "1.x"},
        "learning": {"enabled": bool(snapshot["meta"].get("learning", {}).get("enabled"))},
        "entries": entries,
        "entry_count": len(entries),
    }
    bundle["checksum"] = {"algorithm": "sha256",
                          "scope": "format, compatibility, entries and entry_count; excludes checksum, producer, exported_at, source, learning",
                          "value": _checksum(bundle)}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    write_json_atomic(tmp, bundle)
    tmp.replace(out_path)
    return {
        "ok": True,
        "path": str(out_path),
        "entries": len(entries),
        "bytes": out_path.stat().st_size,
        "sha256": sha256_file(out_path),
        "checksum": bundle["checksum"]["value"],
        "learning_enabled": bundle["learning"]["enabled"],
    }


def _validate_compatibility(bundle):
    compatibility = bundle.get("compatibility")
    if not isinstance(compatibility, dict):
        raise LexiconError("invalid_format", "bundle has no compatibility object")
    minimum = str(compatibility.get("min_reader", ""))
    maximum = str(compatibility.get("max_reader", ""))
    match = re.fullmatch(r"(\d+)(?:\.\d+)?", minimum)
    if not match:
        raise LexiconError("invalid_format", "compatibility.min_reader is not a version")
    if int(match.group(1)) > 1:
        raise LexiconError(
            "incompatible_version",
            "bundle requires a newer reader",
            {"min_reader": minimum, "max_reader": maximum, "supported": "1.x"},
        )
    if maximum and not re.fullmatch(r"1(?:\.\w+)?", maximum):
        raise LexiconError("incompatible_version", "bundle is not readable by this version",
                           {"max_reader": maximum})


def _legacy_entries(payload):
    """Convert the documented pre-1.0 forms into v1 entries."""
    source = None
    if isinstance(payload, list):
        rows, source = payload, "legacy-list"
    elif isinstance(payload, dict) and isinstance(payload.get("words"), list):
        rows, source = payload["words"], payload.get("format") or "legacy-words"
    else:
        raise LexiconError("invalid_format", "not a v1 bundle or a recognised legacy word list")
    entries = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise LexiconError("invalid_record", f"legacy entry {index} is not an object")
        text = row.get("text", row.get("word"))
        pinyin = row.get("pinyin")
        count = row.get("count", row.get("freq", 1))
        kind = row.get("kind", "learned")
        if kind not in ("learned", "custom"):
            kind = "learned"
        try:
            entries.append(validate_entry({
                "text": text, "pinyin": pinyin, "count": count, "kind": kind,
                "source": "legacy-v0",
                "first_seen": row.get("first_seen"), "last_seen": row.get("last_seen"),
            }, kinds=("learned", "custom")))
        except LexiconError as exc:
            raise LexiconError("invalid_record", f"legacy entry {index}: {exc.message}", exc.details)
    return entries, "ime-user-words/0"


def _load_legacy_tsv(path):
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) not in (2, 3):
            raise LexiconError("invalid_format", f"legacy TSV line {number} needs 2 or 3 fields")
        count = int(fields[2]) if len(fields) == 3 else 1
        rows.append({"text": fields[0], "pinyin": fields[1], "count": count,
                     "kind": "learned", "source": "legacy-v0"})
    entries = [validate_entry(row, kinds=("learned", "custom")) for row in rows]
    return {"entries": entries, "migrated_from": "ime-user-words/0", "bundle": None}


def load_bundle(path):
    path = Path(path)
    try:
        payload = read_json(path, code="invalid_json")
    except LexiconError as exc:
        if exc.code == "invalid_json" and path.suffix.lower() in (".tsv", ".txt"):
            return _load_legacy_tsv(path)
        raise
    if isinstance(payload, (list, dict)) and not (isinstance(payload, dict) and isinstance(payload.get("format"), str)):
        entries, migrated = _legacy_entries(payload)
        return {"entries": entries, "migrated_from": migrated, "bundle": None}
    if not isinstance(payload, dict):
        raise LexiconError("invalid_format", "bundle must be a JSON object")
    fmt = payload.get("format", "")
    if fmt == "ime-user-words/0":
        entries, migrated = _legacy_entries(payload)
        return {"entries": entries, "migrated_from": migrated, "bundle": None}
    match = BUNDLE_RE.fullmatch(str(fmt))
    if not match:
        if str(fmt).startswith("ime-lexicon-user-bundle/"):
            raise LexiconError("incompatible_version", f"unsupported bundle format {fmt!r}")
        raise LexiconError("invalid_format", f"unknown bundle format {fmt!r}")
    if int(match.group(1)) != 1:
        raise LexiconError("incompatible_version", f"unsupported bundle format {fmt!r}")
    _validate_compatibility(payload)
    checksum = payload.get("checksum")
    if not isinstance(checksum, dict) or checksum.get("algorithm") != "sha256" or not checksum.get("value"):
        raise LexiconError("invalid_format", "bundle has no sha256 checksum")
    actual = _checksum(payload)
    if actual != checksum["value"]:
        raise LexiconError("checksum_mismatch", "bundle checksum does not match its contents",
                           {"expected": checksum["value"], "actual": actual})
    rows = payload.get("entries")
    if not isinstance(rows, list):
        raise LexiconError("invalid_format", "bundle has no entries array")
    if len(rows) > MAX_ENTRIES:
        raise LexiconError("limit_exceeded", f"bundle has more than {MAX_ENTRIES} entries")
    entries = [validate_entry(row, kinds=("learned", "custom")) for row in rows]
    unique = {}
    for entry in entries:
        key = entry_key(entry["text"], entry["pinyin"])
        current = unique.get(key)
        if current:
            entry = dict(entry)
            entry["count"] = max(int(current["count"]), int(entry["count"]))
            if current["kind"] == "custom":
                entry["kind"] = "custom"
        unique[key] = entry
    return {"entries": list(unique.values()), "migrated_from": None, "bundle": payload}


def preview_import(store, path, mode="merge"):
    loaded = load_bundle(path)
    current = {entry_key(row["text"], row["pinyin"]): row for row in store.snapshot()["entries"]}
    added = updated = unchanged = 0
    for entry in loaded["entries"]:
        key = entry_key(entry["text"], entry["pinyin"])
        existing = current.get(key)
        if existing is None:
            added += 1
        elif mode == "replace":
            updated += 1
        elif (entry["count"] > existing["count"] or
              (entry["kind"] == "custom" and existing["kind"] != "custom")):
            updated += 1
        else:
            unchanged += 1
    return {
        "ok": True,
        "dry_run": True,
        "mode": mode,
        "entries": len(loaded["entries"]),
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "migrated_from": loaded["migrated_from"],
    }


def import_bundle(store, path, *, mode="merge", dry_run=False):
    if mode not in ("merge", "replace"):
        raise LexiconError("invalid_argument", "mode must be merge or replace")
    loaded = load_bundle(path)
    if dry_run:
        return preview_import(store, path, mode)
    if mode == "replace":
        revision = store.replace_entries(loaded["entries"], action="import_replace")
        summary = {"added": 0, "updated": len(loaded["entries"]), "unchanged": 0}
    else:
        summary = store.merge_entries(loaded["entries"], action="import_merge")
        revision = summary.pop("revision")
    return {
        "ok": True,
        "mode": mode,
        "entries": len(loaded["entries"]),
        "migrated_from": loaded["migrated_from"],
        "revision": revision,
        **summary,
    }


# ------------------------------------------------------------------- backups
def _backup_path(store, backup_id):
    if not isinstance(backup_id, str) or not SAFE_ID.fullmatch(backup_id):
        raise LexiconError("invalid_argument", "backup id contains unsupported characters")
    path = (store.backups_dir / backup_id).resolve()
    if path.parent != store.backups_dir.resolve():
        raise LexiconError("invalid_argument", "backup id escapes the backup directory")
    return path


def make_backup(store, *, label="", note=""):
    snapshot = store.snapshot()
    stamp = utcnow().rstrip("Z").replace("-", "").replace(":", "")
    safe_label = re.sub(r"[^A-Za-z0-9._-]", "-", label or "manual")[:40]
    backup_id = f"{stamp}Z-{safe_label}-{uuid.uuid4().hex[:6]}"
    path = store.backups_dir / backup_id
    path.mkdir(parents=True, exist_ok=False)
    words = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                    for row in sorted(snapshot["entries"], key=lambda item: (item["text"], item["pinyin"]))).encode("utf-8")
    meta = dict(snapshot["meta"])
    write_jsonl_atomic(path / "words.jsonl", sorted(snapshot["entries"], key=lambda item: (item["text"], item["pinyin"])))
    write_json_atomic(path / "meta.json", meta)
    manifest = {
        "schema": SCHEMA_BACKUP,
        "backup_id": backup_id,
        "created_at": utcnow(),
        "label": label,
        "note": note,
        "writer": "lexicon",
        "store": {
            "schema": snapshot["meta"].get("schema"),
            "store_id": snapshot["meta"].get("store_id"),
            "revision": snapshot["meta"].get("revision"),
            "learning": snapshot["meta"].get("learning"),
            "base": snapshot["meta"].get("base"),
            "counts": snapshot["meta"].get("counts"),
        },
        "entry_count": len(snapshot["entries"]),
        "files": {
            "words.jsonl": {"sha256": sha256_bytes(words), "bytes": len(words)},
            "meta.json": {"sha256": sha256_file(path / "meta.json"),
                           "bytes": (path / "meta.json").stat().st_size},
        },
        "restore_note": "Derived native/ tables are rebuilt after restore; they are not part of a backup.",
    }
    write_json_atomic(path / "manifest.json", manifest)
    return {"ok": True, **manifest}


def list_backups(store):
    rows = []
    if store.backups_dir.is_dir():
        for path in sorted(store.backups_dir.iterdir()):
            if not path.is_dir():
                continue
            manifest = path / "manifest.json"
            if not manifest.is_file():
                rows.append({"backup_id": path.name, "valid": False, "error": "missing manifest"})
                continue
            try:
                data = read_json(manifest)
                rows.append({
                    "backup_id": path.name,
                    "valid": data.get("schema") == SCHEMA_BACKUP,
                    "created_at": data.get("created_at"),
                    "label": data.get("label"),
                    "entry_count": data.get("entry_count"),
                    "store_revision": (data.get("store") or {}).get("revision"),
                    "learning_enabled": ((data.get("store") or {}).get("learning") or {}).get("enabled"),
                })
            except LexiconError as exc:
                rows.append({"backup_id": path.name, "valid": False, "error": exc.message})
    return {"ok": True, "backups": rows, "count": len(rows)}


def verify_backup(store, backup_id):
    path = _backup_path(store, backup_id)
    if not path.is_dir():
        raise LexiconError("unknown_backup", f"backup not found: {backup_id}")
    manifest = read_json(path / "manifest.json", code="store_corrupt")
    if manifest.get("schema") != SCHEMA_BACKUP:
        raise LexiconError("incompatible_version", "unsupported backup schema",
                           {"schema": manifest.get("schema")})
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise LexiconError("store_corrupt", "backup manifest has no file hashes")
    for name, info in files.items():
        target = path / name
        if not target.is_file():
            raise LexiconError("store_corrupt", f"backup file is missing: {name}")
        actual = sha256_file(target)
        if actual != info.get("sha256"):
            raise LexiconError("checksum_mismatch", f"backup file hash mismatch: {name}",
                               {"expected": info.get("sha256"), "actual": actual})
    meta = read_json(path / "meta.json", code="store_corrupt")
    if meta.get("schema") != SCHEMA_USER:
        raise LexiconError("incompatible_version", "backup uses an incompatible user data schema",
                           {"schema": meta.get("schema"), "supported": SCHEMA_USER})
    entries = [validate_entry(row, kinds=("learned", "custom"))
               for row in read_jsonl(path / "words.jsonl", code="store_corrupt")]
    if len(entries) != manifest.get("entry_count"):
        raise LexiconError("store_corrupt", "backup entry count does not match its manifest")
    return {"ok": True, "manifest": manifest, "meta": meta, "entries": entries, "path": path}


def restore_backup(store, backup_id):
    verified = verify_backup(store, backup_id)
    pre = make_backup(store, label="pre-restore", note=f"automatic before restoring {backup_id}")
    revision = store.replace_entries(verified["entries"], action="restore")
    target_learning = bool((verified["meta"].get("learning") or {}).get("enabled"))
    if target_learning != store.learning_enabled:
        store.set_learning(target_learning, reason=f"restored from {backup_id}", actor="restore")
    return {
        "ok": True,
        "restored_from": backup_id,
        "entries": len(verified["entries"]),
        "revision": store.meta.get("revision"),
        "learning_enabled": store.learning_enabled,
        "pre_restore_backup": pre["backup_id"],
        "native_rebuild_required": True,
    }


def prune_backups(store, keep=10):
    if type(keep) is not int or keep < 1:
        raise LexiconError("invalid_argument", "keep must be a positive integer")
    rows = list_backups(store)["backups"]
    rows = [row for row in rows if row.get("valid")]
    rows.sort(key=lambda row: row.get("created_at") or row["backup_id"], reverse=True)
    removed = []
    for row in rows[keep:]:
        path = _backup_path(store, row["backup_id"])
        shutil.rmtree(path)
        removed.append(row["backup_id"])
    return {"ok": True, "removed": removed, "kept": [row["backup_id"] for row in rows[:keep]]}
