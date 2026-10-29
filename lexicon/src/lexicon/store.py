"""Personal word frequency, custom phrases and the learning switch.

SPDX-License-Identifier: GPL-3.0-or-later

Ownership: this module is the only writer of ``meta.json``, ``words.jsonl``,
``audit.jsonl`` and ``native/`` under the user data directory.  The conversion
engine loads ``native/`` read-only and must never call pinyin_train/save there.
"""
import copy
import fcntl
import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import LexiconError
from .records import (
    MAX_COUNT, MAX_ENTRIES, SCHEMA_NATIVE, SCHEMA_USER, canonical_bytes,
    check_reading, entry_key, new_entry, normalize_pinyin, read_json, read_jsonl, sha256_bytes,
    sha256_file, utcnow, validate_entry, validate_text, write_json_atomic,
    write_jsonl_atomic,
)

SCHEMA_RE = re.compile(r"ime-lexicon-user/(\d+)\Z")
DEDUPE_WINDOW = 256
PRIVATE_PURPOSES = {"password", "pin", "secret", "credential", "private"}


def _major(schema):
    match = SCHEMA_RE.fullmatch(str(schema)) if schema else None
    if not match:
        raise LexiconError("incompatible_version", f"unknown user data schema {schema!r}")
    major = int(match.group(1))
    if major != 1:
        raise LexiconError(
            "incompatible_version",
            f"user data schema major {major} is newer than this reader",
            {"schema": schema, "supported": ["ime-lexicon-user/1"]},
        )
    return major


def _check_flag(value, name):
    if type(value) is not bool:
        raise LexiconError("invalid_argument", f"{name} must be a boolean")
    return value


class UserStore:
    def __init__(self, root, *, create=False, base_manifest=None, clock=utcnow):
        self.root = Path(root).resolve()
        self.meta_path = self.root / "meta.json"
        self.words_path = self.root / "words.jsonl"
        self.lock_path = self.root / "lock"
        self.native_dir = self.root / "native"
        self.native_manifest_path = self.root / "native-manifest.json"
        self.backups_dir = self.root / "backups"
        self.audit_path = self.root / "audit.jsonl"
        self._clock = clock
        if not self.meta_path.exists():
            if not create:
                raise LexiconError("store_missing", f"no lexicon user store at {self.root}")
            self._create(base_manifest)
        self.meta = read_json(self.meta_path, code="store_corrupt")
        _major(self.meta.get("schema"))
        self.entries = self._load_words()
        self._check_loaded()

    # ---------------------------------------------------------------- creation
    def _create(self, base_manifest):
        if self.root.exists() and any(self.root.iterdir()):
            raise LexiconError("store_exists", f"directory is not empty: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        base = None
        if base_manifest:
            if isinstance(base_manifest, (str, Path)):
                base_manifest = read_json(Path(base_manifest), code="invalid_base")
            base = {
                "lexicon_version": base_manifest.get("lexicon_version"),
                "sha256": (base_manifest.get("files", {}).get("lexicon-v1.jsonl", {}) or {}).get("sha256"),
                "entry_count": base_manifest.get("entry_count"),
            }
            if not base["sha256"]:
                raise LexiconError("invalid_base", "base manifest has no lexicon-v1.jsonl hash")
        now = self._clock()
        meta = {
            "schema": SCHEMA_USER,
            "store_id": str(uuid.uuid4()),
            "created_at": now,
            "updated_at": now,
            "revision": 0,
            "writer": "lexicon",
            "learning": {"enabled": False, "updated_at": now, "reason": "created disabled", "actor": "init"},
            "base": base,
            "limits": {"max_entries": MAX_ENTRIES, "max_count": MAX_COUNT, "dedupe_window": DEDUPE_WINDOW},
            "last_event_ids": [],
            "last_action": None,
            "counts": {"base": 0, "learned": 0, "custom": 0, "total": 0},
        }
        self.root.joinpath("lock").touch(mode=0o600)
        self.root.chmod(0o700)
        write_jsonl_atomic(self.words_path, [])
        meta["files"] = {"words.jsonl": {"sha256": sha256_bytes(b""), "bytes": 0}}
        write_json_atomic(self.meta_path, meta)

    # ----------------------------------------------------------------- loading
    def _load_words(self):
        if not self.words_path.is_file():
            raise LexiconError("store_corrupt", "words.jsonl is missing")
        entries, keys = {}, set()
        for row in read_jsonl(self.words_path, code="store_corrupt"):
            entry = validate_entry(row, kinds=("learned", "custom"))
            key = entry_key(entry["text"], entry["pinyin"])
            if key in keys:
                raise LexiconError("store_corrupt", "duplicate entry in words.jsonl", {"text": entry["text"]})
            keys.add(key)
            entries[key] = entry
        return entries

    def _check_loaded(self):
        if not isinstance(self.meta.get("revision"), int) or self.meta["revision"] < 0:
            raise LexiconError("store_corrupt", "invalid revision")
        recorded = self.meta.get("files", {}).get("words.jsonl", {}).get("sha256")
        actual = sha256_file(self.words_path) if self.words_path.is_file() else None
        if recorded and actual != recorded:
            raise LexiconError(
                "store_corrupt",
                "words.jsonl does not match the hash recorded in meta.json",
                {"recorded": recorded, "actual": actual},
            )
        counts = self._counts()
        if self.meta.get("counts") != counts:
            raise LexiconError(
                "store_corrupt",
                "meta counts differ from words.jsonl; run verify/repair",
                {"recorded": self.meta.get("counts"), "actual": counts},
            )

    def _counts(self):
        counts = {"base": 0, "learned": 0, "custom": 0, "total": len(self.entries)}
        for entry in self.entries.values():
            counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
        return counts

    # ------------------------------------------------------------------ locking
    @contextmanager
    def lock(self, exclusive=True, blocking=False):
        self.root.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_path, "a+")
        try:
            flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            if not blocking:
                flags |= fcntl.LOCK_NB
            try:
                fcntl.flock(handle.fileno(), flags)
            except BlockingIOError:
                raise LexiconError("store_locked", "another process is writing this user data directory")
            yield self
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()

    def reload(self):
        meta = read_json(self.meta_path, code="store_corrupt")
        _major(meta.get("schema"))
        entries = self._load_words()
        self.meta, self.entries = meta, entries
        self._check_loaded()
        return self

    # ------------------------------------------------------------------ writing
    def _write_state(self, entries, *, meta_update=None):
        rows = [entries[key] for key in sorted(entries)]
        payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows).encode("utf-8")
        meta = dict(self.meta)
        if meta_update:
            meta.update(meta_update)
        meta["revision"] = int(meta["revision"]) + 1
        meta["updated_at"] = self._clock()
        meta["counts"] = {
            "base": 0, "learned": 0, "custom": 0, "total": len(entries),
        }
        for row in rows:
            meta["counts"][row["kind"]] = meta["counts"].get(row["kind"], 0) + 1
        meta["files"] = {"words.jsonl": {"sha256": sha256_bytes(payload), "bytes": len(payload)}}
        write_jsonl_atomic(self.words_path, rows)
        write_json_atomic(self.meta_path, meta)
        self.meta, self.entries = meta, entries
        return meta["revision"]

    def _audit(self, action, details=None):
        record = {"at": self._clock(), "action": action, "details": details or {}}
        self.root.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        descriptor = os.open(self.audit_path, flags, 0o600)
        try:
            os.write(descriptor, (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    # ------------------------------------------------------------------ status
    @property
    def learning_enabled(self):
        return bool(self.meta.get("learning", {}).get("enabled"))

    def status(self):
        native = None
        if self.native_manifest_path.is_file():
            try:
                data = read_json(self.native_manifest_path)
                native = {
                    "built_at": data.get("built_at"),
                    "store_revision": data.get("store_revision"),
                    "entry_count": data.get("entry_count"),
                    "base": data.get("base"),
                    "files": data.get("files"),
                }
            except LexiconError as exc:
                native = {"error": exc.to_dict()}
        return {
            "ok": True,
            "root": str(self.root),
            "schema": self.meta.get("schema"),
            "store_id": self.meta.get("store_id"),
            "revision": self.meta.get("revision"),
            "writer": self.meta.get("writer"),
            "learning": copy.deepcopy(self.meta.get("learning")),
            "counts": copy.deepcopy(self.meta.get("counts")),
            "base": copy.deepcopy(self.meta.get("base")),
            "native": native,
            "limits": copy.deepcopy(self.meta.get("limits")),
        }

    def set_learning(self, enabled, *, reason="", actor="user"):
        _check_flag(enabled, "enabled")
        with self.lock(exclusive=True):
            self.reload()
            now = self._clock()
            meta = dict(self.meta)
            meta["learning"] = {
                "enabled": enabled,
                "updated_at": now,
                "reason": str(reason)[:200],
                "actor": str(actor)[:80],
            }
            meta["last_action"] = {"action": "learning_on" if enabled else "learning_off", "at": now, "actor": actor}
            self._write_state(self.entries, meta_update=meta)
            self._audit("learning_on" if enabled else "learning_off", {"reason": reason, "actor": actor})
        return {"ok": True, "learning": copy.deepcopy(self.meta["learning"]), "revision": self.meta["revision"]}

    # ---------------------------------------------------------------- learning
    def record_commit(self, text, pinyin, *, source="commit", event_id=None,
                      learning_eligible=True, private=False, purpose="text"):
        """Record one technically eligible candidate commit.

        Returns ``recorded: false`` with an explicit reason and writes nothing
        when learning is off, the input is private, the purpose is sensitive or
        the event was already seen.
        """
        _check_flag(learning_eligible, "learning_eligible")
        _check_flag(private, "private")
        if not isinstance(purpose, str) or not purpose:
            raise LexiconError("invalid_argument", "purpose must be a non-empty string")
        if event_id is not None:
            if not isinstance(event_id, str) or not 1 <= len(event_id) <= 128:
                raise LexiconError("invalid_argument", "event_id must be 1-128 characters")
        if not learning_eligible:
            return self._not_recorded("not_eligible")
        if private:
            return self._not_recorded("private_input")
        if purpose.lower() in PRIVATE_PURPOSES:
            return self._not_recorded("purpose_not_allowed")
        try:
            clean_text = validate_text(text)
            clean_pinyin = normalize_pinyin(pinyin)
            check_reading(clean_text, clean_pinyin)
        except LexiconError as exc:
            return self._not_recorded("invalid_record", detail=exc.to_dict()["error"])
        with self.lock(exclusive=True):
            self.reload()
            if not self.learning_enabled:
                return self._not_recorded("learning_disabled", revision=self.meta["revision"])
            seen = self.meta.get("last_event_ids", [])
            if event_id and event_id in seen:
                return self._not_recorded("duplicate_event", revision=self.meta["revision"])
            key = entry_key(clean_text, clean_pinyin)
            now = self._clock()
            entry = self.entries.get(key)
            if entry is None:
                if len(self.entries) >= int(self.meta.get("limits", {}).get("max_entries", MAX_ENTRIES)):
                    return self._not_recorded("limit_exceeded", revision=self.meta["revision"])
                entry = new_entry(clean_text, clean_pinyin, 1, "learned", source=source,
                                  first_seen=now, last_seen=now)
            else:
                entry = dict(entry)
                entry["count"] = min(int(entry["count"]) + 1, MAX_COUNT)
                entry["last_seen"] = now
                if entry["kind"] == "custom":
                    entry["source"] = entry.get("source", source)
            entries = dict(self.entries)
            entries[key] = entry
            seen = [item for item in seen if item != event_id][-(DEDUPE_WINDOW - 1):]
            if event_id:
                seen.append(event_id)
            meta_update = {
                "last_event_ids": seen,
                "last_action": {"action": "learn", "at": now, "source": source, "count": entry["count"]},
            }
            revision = self._write_state(entries, meta_update=meta_update)
        return {
            "ok": True,
            "recorded": True,
            "reason": "learned",
            "entry": copy.deepcopy(entry),
            "revision": revision,
        }

    def _not_recorded(self, reason, *, revision=None, detail=None):
        payload = {
            "ok": True,
            "recorded": False,
            "reason": reason,
            "learning": self.learning_enabled,
        }
        if revision is not None:
            payload["revision"] = revision
        if detail:
            payload["detail"] = detail
        return payload

    def add_phrase(self, text, pinyin, count=50, *, source="custom"):
        if type(count) is not int or not 1 <= count <= MAX_COUNT:
            raise LexiconError("invalid_argument", f"count must be an integer in [1, {MAX_COUNT}]")
        entry = new_entry(text, pinyin, count, "custom", source=source,
                          first_seen=self._clock(), last_seen=self._clock())
        with self.lock(exclusive=True):
            self.reload()
            key = entry_key(entry["text"], entry["pinyin"])
            current = self.entries.get(key)
            if current:
                entry = dict(current)
                entry["kind"] = "custom"
                entry["count"] = max(int(entry["count"]), count)
                entry["last_seen"] = self._clock()
                entry["source"] = source
            elif len(self.entries) >= int(self.meta.get("limits", {}).get("max_entries", MAX_ENTRIES)):
                raise LexiconError("limit_exceeded", "user store entry limit reached")
            entries = dict(self.entries)
            entries[key] = entry
            revision = self._write_state(entries, meta_update={
                "last_action": {"action": "phrase_add", "at": self._clock(), "count": entry["count"]}})
        return {"ok": True, "entry": copy.deepcopy(entry), "revision": revision}

    def remove_phrase(self, text=None, pinyin=None, *, all_entries=False):
        if all_entries:
            if text is not None or pinyin is not None:
                raise LexiconError("invalid_argument", "all_entries cannot be combined with text or pinyin")
        elif text is None:
            raise LexiconError("invalid_argument", "text is required unless all_entries is true")
        else:
            text = validate_text(text)
            pinyin = normalize_pinyin(pinyin) if pinyin is not None else None
        with self.lock(exclusive=True):
            self.reload()
            removed = []
            for key, entry in list(self.entries.items()):
                if all_entries or (entry["text"] == text and (pinyin is None or entry["pinyin"] == pinyin)):
                    removed.append(entry)
            if removed:
                entries = {key: entry for key, entry in self.entries.items() if entry not in removed}
                revision = self._write_state(entries, meta_update={
                    "last_action": {"action": "phrase_remove", "at": self._clock(), "removed": len(removed)}})
            else:
                revision = self.meta["revision"]
        return {"ok": True, "removed": copy.deepcopy(removed), "count": len(removed), "revision": revision}

    # ------------------------------------------------------------------ queries
    def list_words(self, *, kind=None, query=None, limit=100, offset=0, reload=True):
        if limit is None or not isinstance(limit, int) or limit < 0:
            raise LexiconError("invalid_argument", "limit must be a non-negative integer")
        if not isinstance(offset, int) or offset < 0:
            raise LexiconError("invalid_argument", "offset must be a non-negative integer")
        if reload:
            with self.lock(exclusive=False):
                self.reload()
        rows = [entry for entry in self.entries.values() if kind is None or entry["kind"] == kind]
        if query:
            needle = str(query)
            rows = [entry for entry in rows if needle in entry["text"] or needle in entry["pinyin"]]
        rows.sort(key=lambda item: (-int(item["count"]), item["text"], item["pinyin"]))
        return {"ok": True, "total": len(rows), "offset": offset, "limit": limit,
                "entries": copy.deepcopy(rows[offset: offset + limit])}

    def snapshot(self):
        with self.lock(exclusive=False):
            self.reload()
            return {
                "meta": copy.deepcopy(self.meta),
                "entries": copy.deepcopy([self.entries[key] for key in sorted(self.entries)]),
            }

    def replace_entries(self, entries, *, action="import"):
        validated = {}
        for row in entries:
            entry = validate_entry(row, kinds=("learned", "custom"))
            validated[entry_key(entry["text"], entry["pinyin"])] = entry
        with self.lock(exclusive=True):
            self.reload()
            revision = self._write_state(validated, meta_update={
                "last_action": {"action": action, "at": self._clock(), "entries": len(validated)}})
        return revision

    def merge_entries(self, entries, *, action="import"):
        validated = [validate_entry(row, kinds=("learned", "custom")) for row in entries]
        with self.lock(exclusive=True):
            self.reload()
            merged = dict(self.entries)
            added = updated = unchanged = 0
            for entry in validated:
                key = entry_key(entry["text"], entry["pinyin"])
                current = merged.get(key)
                if current is None:
                    merged[key] = entry
                    added += 1
                    continue
                candidate = dict(current)
                changed = False
                if int(entry["count"]) > int(current["count"]):
                    candidate["count"] = entry["count"]
                    changed = True
                if entry["kind"] == "custom" and current["kind"] != "custom":
                    candidate["kind"] = "custom"
                    changed = True
                for stamp, pick in (("first_seen", min), ("last_seen", max)):
                    if entry.get(stamp):
                        candidate[stamp] = pick(candidate.get(stamp) or entry[stamp], entry[stamp])
                for field in ("source",):
                    if entry.get(field) and entry[field] != current.get(field):
                        candidate[field] = entry[field]
                        changed = True
                if changed:
                    merged[key] = candidate
                    updated += 1
                else:
                    unchanged += 1
            revision = self._write_state(merged, meta_update={
                "last_action": {"action": action, "at": self._clock(), "added": added, "updated": updated}})
        return {"added": added, "updated": updated, "unchanged": unchanged, "revision": revision}

    # ------------------------------------------------------------------- verify
    def verify(self):
        issues, warnings = [], []
        try:
            _major(self.meta.get("schema"))
        except LexiconError as exc:
            issues.append({"code": exc.code, "message": exc.message})
        try:
            actual = sha256_file(self.words_path)
            recorded = self.meta.get("files", {}).get("words.jsonl", {}).get("sha256")
            if recorded and actual != recorded:
                issues.append({"code": "store_corrupt", "message": "words.jsonl hash mismatch"})
        except OSError:
            issues.append({"code": "store_corrupt", "message": "words.jsonl is missing"})
        counts = self._counts()
        if counts != self.meta.get("counts"):
            issues.append({"code": "store_corrupt", "message": "counts differ from words.jsonl",
                           "details": {"recorded": self.meta.get("counts"), "actual": counts}})
        native = None
        if self.native_manifest_path.is_file():
            try:
                native = read_json(self.native_manifest_path)
                if native.get("schema") != SCHEMA_NATIVE:
                    issues.append({"code": "store_corrupt", "message": "native manifest schema mismatch"})
                base = self.meta.get("base") or {}
                built_base = native.get("base") or {}
                if base.get("sha256") and built_base.get("sha256") != base.get("sha256"):
                    warnings.append({"code": "native_stale", "message": "native table was built for another base lexicon"})
                if native.get("store_revision") != self.meta.get("revision"):
                    warnings.append({"code": "native_stale", "message": "native table is older than words.jsonl; rebuild it"})
                for name, info in (native.get("files") or {}).items():
                    path = self.native_dir / name
                    if not path.is_file() or sha256_file(path) != info.get("sha256"):
                        issues.append({"code": "native_corrupt", "message": f"native file differs: {name}"})
            except LexiconError as exc:
                issues.append({"code": "store_corrupt", "message": exc.message})
        backups = []
        if self.backups_dir.is_dir():
            backups = sorted(path.name for path in self.backups_dir.iterdir() if path.is_dir())
        return {
            "ok": not issues,
            "root": str(self.root),
            "schema": self.meta.get("schema"),
            "revision": self.meta.get("revision"),
            "entries": len(self.entries),
            "counts": counts,
            "learning": self.learning_enabled,
            "issues": issues,
            "warnings": warnings,
            "native": native,
            "backups": backups,
        }

    def repair(self, *, apply=False):
        counts = self._counts()
        meta = dict(self.meta)
        meta["counts"] = counts
        meta["files"] = {"words.jsonl": {"sha256": sha256_file(self.words_path),
                                          "bytes": self.words_path.stat().st_size}}
        if apply:
            with self.lock(exclusive=True):
                self.reload()
                self._write_state(self.entries, meta_update=meta)
                self._audit("repair", {"counts": counts})
            return {"ok": True, "applied": True, "counts": counts, "revision": self.meta["revision"]}
        return {"ok": True, "applied": False, "proposed": {"counts": counts}}


def default_data_dir(env=None, home=None):
    env = env if env is not None else os.environ
    home = Path(home or env.get("HOME") or Path.home())
    root = Path(env.get("XDG_DATA_HOME") or home / ".local/share")
    return root / "server-ime/lexicon"
