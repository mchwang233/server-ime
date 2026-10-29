"""Public version 1 conversion/session interface. SPDX-License-Identifier: GPL-3.0-or-later."""
from copy import deepcopy
from dataclasses import dataclass, asdict, field
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from .native import Native, NATIVE_LOCK
from .expansion import Expansion
from .spelling import split
from .composition import Composer, spans, literal_key
from .options import FUZZY_RULES, CORRECTION_RULES, DOUBLE_SCHEMES, rules_flags, sensitive
from . import lexicon_adapter as lexicon
from . import libime_backend

API_VERSION = "1.0"
COMPONENT_VERSION = "0.4.0"
MAX_INPUT = 128
REPAIR_LIMIT = 24  # letters; longer unfinished input is decoded as typed (libime)


class EngineError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise EngineError("invalid_argument", f"{name} must be an integer in [{low}, {high}]")
    return value


@dataclass(frozen=True)
class Config:
    schema: str = "full_pinyin"
    page_size: int = 5
    incomplete: bool = True
    learning: bool = False
    double_pinyin_scheme: str = "ziranma"
    fuzzy: dict = field(default_factory=lambda: {"enabled": False, "rules": []})
    correction: dict = field(default_factory=lambda: {"enabled": True, "rules": []})

    @classmethod
    def update(cls, previous, patch):
        if not isinstance(patch, dict):
            raise EngineError("invalid_config", "config must be an object")
        if any(not isinstance(key, str) for key in patch):
            raise EngineError("invalid_config", "config keys must be strings")
        unknown = set(patch) - set(asdict(previous))
        if unknown:
            raise EngineError("unsupported_config", "unsupported config: " + ", ".join(sorted(unknown)))
        values = {**asdict(previous), **patch}
        if values["schema"] not in ("full_pinyin", "double_pinyin"):
            raise EngineError("unsupported_config", "schema must be full_pinyin or double_pinyin")
        if not isinstance(values["double_pinyin_scheme"], str) or values["double_pinyin_scheme"] not in DOUBLE_SCHEMES:
            raise EngineError("unsupported_config", "supported double_pinyin_scheme: ziranma (自然码)")
        integer(values["page_size"], "page_size", 1, 9)
        for key in ("incomplete", "learning"):
            if type(values[key]) is not bool:
                raise EngineError("invalid_config", key + " must be boolean")
        for key, table in (("fuzzy", FUZZY_RULES), ("correction", CORRECTION_RULES)):
            value = values[key]
            if not isinstance(value, dict) or set(value) - {"enabled", "rules"}:
                raise EngineError("invalid_config", key + " must contain enabled/rules")
            enabled, rules = value.get("enabled", False), value.get("rules", [])
            if type(enabled) is not bool or not isinstance(rules, list) or any(not isinstance(r, str) for r in rules):
                raise EngineError("invalid_config", key + " needs boolean enabled and string-array rules")
            if set(rules) - set(table) or len(rules) != len(set(rules)):
                raise EngineError("unsupported_config", "unknown or duplicate " + key + " rule")
            values[key] = {"enabled": enabled, "rules": list(rules)}
        return cls(**values)


def normalize(text):
    if not isinstance(text, str):
        raise EngineError("invalid_argument", "text must be a string")
    text = text.lower().replace("ü", "v")
    if not re.fullmatch("[a-z']*", text):
        raise EngineError("invalid_input", "use full pinyin letters and apostrophes; ü is normalized to v")
    if len(text) > MAX_INPUT:
        raise EngineError("input_too_long", f"input is limited to {MAX_INPUT} characters")
    return text


def composition_text(text):
    if not isinstance(text, str):
        raise EngineError('invalid_argument', 'text must be a string')
    if len(text) > MAX_INPUT:
        raise EngineError('input_too_long', f'input is limited to {MAX_INPUT} characters')
    if any(not c.isprintable() for c in text):
        raise EngineError('invalid_input', 'composition accepts printable Unicode, without controls or surrogates')
    return text


class Engine:
    """Stock + domain model, with explicit optional local personal storage.

    Native contexts only change in memory. UserStore is the sole disk writer.
    Sensitive sessions always use the separate stock + public-domain context.
    """
    def __init__(self, runtime_dir=None, data_dir=None, user_dir=None, *,
                 user_data_dir=None, base_lexicon=None, libime_dir=None):
        root = Path(__file__).resolve().parents[2]
        self.runtime_dir = Path(runtime_dir or root / "vendor/runtime").resolve()
        self.data_dir = Path(data_dir or self.runtime_dir / "data").resolve()
        self._sessions = {}
        self._context = self._personal_context = None
        self._native_snapshot = None
        self._store = None
        self._store_stamp = None
        self._personal = []
        self._personal_index = {}
        self._lexicon_generation = 0
        self._libime = None
        for name in ("table.conf", "bigram.db", "pinyin_index.bin", "phrase_index.bin",
                     "gb_char.bin", "gbk_char.bin", "opengram.bin", "merged.bin",
                     "addon_pinyin_index.bin", "addon_phrase_index.bin"):
            if not (self.data_dir / name).is_file():
                raise EngineError("dependency_missing", str(self.data_dir / name))
        table = (self.data_dir / "table.conf").read_text()
        if not all(line in table.splitlines() for line in (
                "binary format version:6", "model data version:14", "database format:BerkeleyDB")):
            raise EngineError("incompatible_data", "requires libpinyin binary format 6/model 14/BerkeleyDB")
        with NATIVE_LOCK:
            try:
                self._native = Native(self.runtime_dir)
            except (OSError, AttributeError) as exc:
                raise EngineError("dependency_missing", str(exc)) from exc
            # Full pinyin is decoded by libime when its runtime is present (libime_dir=False: never).
            libime_root = Path(libime_dir or root / "vendor/libime")
            if libime_dir is not False and libime_backend.available(libime_root):
                try:
                    self._libime = libime_backend.shared(libime_root)
                except OSError as exc:
                    raise EngineError("dependency_missing", str(exc)) from exc
            try:
                self._base, self.base_identity = lexicon.base_entries(base_lexicon)
                if user_data_dir is not None:
                    self._store = lexicon.UserStore(user_data_dir, create=True)
                if user_dir is not None:
                    # libpinyin check_format can delete incompatible user files:
                    # copy a trusted matching native table, never initialize on originals.
                    user = Path(user_dir).resolve()
                    required = ("user.conf", "user_phrase_index.bin", "user_pinyin_index.bin", "user_bigram.db")
                    if any(not (user / n).is_file() for n in required):
                        raise EngineError("incompatible_data", "incomplete native user_dir")
                    conf = (user / "user.conf").read_text()
                    if any(line not in conf.splitlines() for line in (
                            "binary format version:6", "model data version:14")):
                        raise EngineError("incompatible_data", "native user_dir version mismatch")
                    self._native_snapshot = tempfile.TemporaryDirectory(prefix="server-ime-native-")
                    allowed = set(required) | {"user.bin", "addon.bin", "network.bin", "gb_char.dbin",
                                               "gbk_char.dbin", "opengram.dbin", "merged.dbin"}
                    for name in allowed:
                        if (user / name).is_file():
                            shutil.copyfile(user / name, Path(self._native_snapshot.name) / name)
                self._context = self._new_context(self._base)
                self._sync_store(force=True)
            except (lexicon.LexiconError, OSError, ValueError) as exc:
                self.close()
                if isinstance(exc, EngineError):
                    raise
                raise EngineError(getattr(exc, "code", "lexicon_error"), str(exc)) from exc

    @staticmethod
    def capabilities():
        return {
            "api_version": API_VERSION, "component_version": COMPONENT_VERSION,
            "employee_id": "engine", "backend": "libpinyin", "backend_version": "2.6.0",
            "full_pinyin_backend": "libime 1.1.11" if libime_backend.available(
                Path(__file__).resolve().parents[2] / "vendor/libime") else "libpinyin 2.6.0",
            "license": "GPL-3.0-or-later", "schemas": ["full_pinyin", "double_pinyin"],
            "features": {"sentence": True, "candidates": True, "partial_selection": True,
                         "editing": True, "session_isolation": True, "pagination": True,
                         "double_pinyin": True, "fuzzy_pinyin": True,
                         "correction": True, "dictionary_import": True, "learning": True,
                         "privacy_context": True, "user_phrases": True, "mixed_input": True},
            "composition": {"operations": ["set_composition", "input_text"],
                            "preserves_literal": True, "partial_selection": True,
                            "digit_policy": "digits in/after literal spans insert; pure-pinyin digits select; input_text always inserts",
                            "legacy_set_input": "unchanged normalization and validation"},
            "search_limits": {"phrase_window_codepoints": 24, "repair_readings": 4,
                              "sentence_branches": 2, "composition_candidates": 200},
            "double_pinyin_schemes": deepcopy(DOUBLE_SCHEMES),
            "fuzzy_rules": list(FUZZY_RULES), "correction_rules": list(CORRECTION_RULES),
            "correction_scope": "8 native syllable rules plus bounded single-edit repairs of incomplete full-pinyin spellings (5..64 letters); valid full pinyin and double-pinyin are not rewritten",
            "learning_requires": "explicit user_data_dir, store master switch and session learning=true",
            "operations": ["set_context", "add_phrase", "remove_phrase", "import_dictionary", "reload_lexicon", "learning_status", "set_composition", "input_text"],
            "config_defaults": asdict(Config()), "max_input_length": MAX_INPUT,
            "max_sessions": 64, "coordinate_unit": "unicode_codepoint", "network": False,
        }

    def create_session(self, config=None, session_id=None):
        with NATIVE_LOCK:
            if not self._context:
                raise EngineError("closed", "engine is closed")
            settings = Config.update(Config(), {} if config is None else config)
            sid = str(uuid.uuid4()) if session_id is None else session_id
            if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", sid):
                raise EngineError("invalid_argument", "session_id must contain 1..64 letters, digits, _ or -")
            if sid in self._sessions:
                raise EngineError("session_exists", sid)
            if len(self._sessions) >= 64:
                raise EngineError("session_limit", "at most 64 sessions per engine")
            self._set_learning(settings.learning, explicit=config is not None and "learning" in config)
            self._sync_store()
            session = Session(self, sid, settings)
            self._sessions[sid] = session
            return session

    def session(self, session_id):
        with NATIVE_LOCK:
            if not isinstance(session_id, str) or session_id not in self._sessions:
                raise EngineError("unknown_session", "unknown session")
            return self._sessions[session_id]

    def destroy_session(self, session_id):
        self.session(session_id).close()

    def close(self):
        with NATIVE_LOCK:
            if self._context:
                for session in list(self._sessions.values()):
                    session.close()
                if self._personal_context:
                    self._native.fini(self._personal_context)
                    self._personal_context = None
                self._native.fini(self._context)
                self._context = None
            if self._libime:
                libime_backend.release(self._libime)
                self._libime = None
            if self._native_snapshot:
                self._native_snapshot.cleanup()
                self._native_snapshot = None

    def _new_context(self, entries, personal=False):
        directory = self._native_snapshot.name.encode() if personal and self._native_snapshot else None
        context = self._native.init(str(self.data_dir).encode(), directory)
        if not context:
            raise EngineError("native_error", "libpinyin initialization failed")
        try:
            self._native.add_entries(context, entries)
        except Exception:
            self._native.fini(context)
            raise
        return context

    def _sync_store(self, force=False):
        try:
            return self._sync_store_impl(force)
        except (lexicon.LexiconError, OSError, ValueError) as exc:
            if isinstance(exc, EngineError):
                raise
            raise EngineError(getattr(exc, "code", "lexicon_error"), str(exc)) from exc

    def _sync_store_impl(self, force=False):
        personal = self._personal
        stamp = self._store_stamp
        if self._store:
            stat = self._store.meta_path.stat()
            stamp = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
            if not force and stamp == self._store_stamp:
                return
            personal = self._store.snapshot()["entries"]
        elif not force:
            return
        if personal == self._personal and not force:
            self._store_stamp = stamp
            return
        new = self._new_context(lexicon.merged_entries(self._base, personal), personal=True) if personal or self._native_snapshot else None
        old = self._personal_context
        self._personal_context, self._personal = new, personal
        self._store_stamp = stamp
        index = {}
        for row in personal:
            index.setdefault(row["pinyin"].replace("'", ""), []).append(row)
        for rows in index.values():
            rows.sort(key=lambda row: (-row["count"], row.get("last_seen", ""), row["text"]))
        self._personal_index = index
        self._lexicon_generation += 1
        try:
            for session in self._sessions.values():
                session._rebind()
        finally:
            if old:
                self._native.fini(old)

    def _set_learning(self, enabled, explicit=True):
        if not explicit:
            return
        if not self._store:
            if enabled:
                raise EngineError("learning_unavailable", "learning requires explicit user_data_dir")
            return
        try:
            with self._store.lock(exclusive=False):
                self._store.reload()
            if self._store.learning_enabled != enabled:
                self._store.set_learning(enabled, reason="engine configuration", actor="engine")
        except (lexicon.LexiconError, OSError) as exc:
            raise EngineError(getattr(exc, "code", "storage_error"), str(exc)) from exc

    def learning_status(self):
        with NATIVE_LOCK:
            if not self._context:
                raise EngineError("closed", "engine is closed")
            self._sync_store()
            return {"available": self._store is not None,
                    "enabled": bool(self._store and self._store.learning_enabled),
                    "entries": len(self._personal), "generation": self._lexicon_generation}

    def reload_lexicon(self):
        with NATIVE_LOCK:
            if not self._context:
                raise EngineError("closed", "engine is closed")
            try:
                self._sync_store(force=True)
            except (lexicon.LexiconError, OSError, ValueError) as exc:
                raise EngineError(getattr(exc, "code", "lexicon_error"), str(exc)) from exc
            return self.learning_status()

    def _phrase_action(self, method, *args, **kwargs):
        with NATIVE_LOCK:
            if not self._context:
                raise EngineError("closed", "engine is closed")
            if not self._store:
                raise EngineError("learning_unavailable", "user phrases require explicit user_data_dir")
            try:
                if method == "add_phrase":
                    entry = lexicon.new_entry(args[0], args[1], args[2], "custom")
                    # Validate native support before committing persistent data.
                    probe = self._new_context([entry])
                    self._native.fini(probe)
                result = getattr(self._store, method)(*args, **kwargs)
                self._sync_store()
                return result
            except (lexicon.LexiconError, OSError, ValueError) as exc:
                raise EngineError(getattr(exc, "code", "lexicon_error"), str(exc)) from exc

    def add_phrase(self, text, pinyin, count=50):
        return self._phrase_action("add_phrase", text, pinyin, count)

    def remove_phrase(self, text, pinyin=None):
        return self._phrase_action("remove_phrase", text, pinyin)

    def import_dictionary(self, entries):
        """Atomic in-memory addition of lexicon base records; no competing format."""
        with NATIVE_LOCK:
            if not self._context:
                raise EngineError("closed", "engine is closed")
            new_public = new_personal = None
            try:
                rows = lexicon.validate_import(entries)
                combined = {(r["text"], r["pinyin"]): r for r in self._base}
                combined.update({(r["text"], r["pinyin"]): r for r in rows})
                base = list(combined.values())
                if len(base) > lexicon.MAX_ENTRIES:
                    raise ValueError("domain dictionary exceeds 20000 entries")
                new_public = self._new_context(base)
                if self._personal or self._native_snapshot:
                    new_personal = self._new_context(lexicon.merged_entries(base, self._personal), personal=True)
            except (lexicon.LexiconError, OSError, ValueError) as exc:
                if new_public:
                    self._native.fini(new_public)
                if new_personal:
                    self._native.fini(new_personal)
                raise EngineError(getattr(exc, "code", "dictionary_error"), str(exc)) from exc
            old_public, old_personal = self._context, self._personal_context
            self._base, self._context, self._personal_context = base, new_public, new_personal
            self._lexicon_generation += 1
            for session in self._sessions.values():
                session._rebind()
            self._native.fini(old_public)
            if old_personal:
                self._native.fini(old_personal)
            return {"accepted": len(rows), "total": len(base), "persistent": False,
                    "generation": self._lexicon_generation}

    def predict(self, history, limit=10):
        """Words likely to follow the committed text (history: recent words, oldest first)."""
        with NATIVE_LOCK:
            if not self._context:
                raise EngineError("closed", "engine is closed")
            if not self._libime or not isinstance(history, (list, tuple)) or \
                    any(not isinstance(word, str) for word in history):
                return []
            return self._libime.predict(list(history), integer(limit, "limit", 1, 50))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Session:
    def __init__(self, engine, session_id, config):
        self.engine, self.session_id, self.config = engine, session_id, config
        self._n = engine._native
        self.context = {"private": False, "purpose": "text", "hints": 0}
        self._context = engine._personal_context or engine._context
        self._instance = self._n.alloc_instance(self._context)
        self._order = None
        self._expansion = None
        self._phrase_instance = None
        self._composition = False
        self._composer = None
        self._composition_units = []
        self._ime_context = None
        self._readings = []
        if not self._instance:
            raise EngineError("native_error", "could not allocate session")
        self._nonce = uuid.uuid4().hex
        self.revision = 0
        self.raw = ""
        self.cursor = self.offset = self.parsed = self.page = self.total = 0
        self.selected = self.preview = ""

    def _check(self):
        if not self._instance:
            raise EngineError("closed", "session is closed")
        try:
            self.engine._sync_store()
        except (lexicon.LexiconError, OSError, ValueError) as exc:
            raise EngineError(getattr(exc, "code", "lexicon_error"), str(exc)) from exc
        self._options()

    @property
    def _private(self):
        return sensitive(**self.context)

    def _options(self):
        flags = 128 | 256 | 512 | (8 if self.config.incomplete else 0)
        flags |= rules_flags(self.config.fuzzy, FUZZY_RULES)
        if self.config.schema == "full_pinyin":
            flags |= rules_flags(self.config.correction, CORRECTION_RULES)
        self._n.set_options(self._context, flags)
        self._n.set_double_pinyin_scheme(self._context, DOUBLE_SCHEMES[self.config.double_pinyin_scheme]["native_id"])

    def _rebind(self):
        target = self.engine._context if self._private else self.engine._personal_context or self.engine._context
        new_instance = self._n.alloc_instance(target)
        if not new_instance:
            raise EngineError("native_error", "could not allocate replacement session")
        if self._composer:
            self._composer.close()
            self._composer = None
        if self._expansion:
            self._expansion.close()
            self._expansion = None
        if self._phrase_instance:
            self._n.free_instance(self._phrase_instance)
            self._phrase_instance = None
        self._n.free_instance(self._instance)
        self._instance, self._context = new_instance, target
        self.revision += 1
        self._options()
        self._decode()

    def set_context(self, private=False, purpose="text", hints=0):
        with NATIVE_LOCK:
            if type(private) is not bool or not (type(purpose) is int or isinstance(purpose, str)):
                raise EngineError("invalid_argument", "context requires boolean private and string/integer purpose")
            if isinstance(purpose, str) and not purpose:
                raise EngineError("invalid_argument", "purpose must not be empty")
            integer(hints, "hints", 0, 0xffffffff)
            self._check()
            context = {"private": private, "purpose": purpose, "hints": hints}
            if context != self.context:
                self._clear()
                self.context = context
                self._rebind()
            return self._state()

    def _decode(self):
        self._n.reset(self._instance)
        self.offset = self.parsed = self.page = self.total = 0
        self.selected = self.preview = ""
        self._order = None
        self._composition_units = []
        self._readings = []
        if self.raw:
            if self._composition:
                self._refresh_composition()
                return
            if self._libime:
                self._refresh()
                return
            parse = (self._n.parse_more_full_pinyins if self.config.schema == "full_pinyin"
                     else self._n.parse_more_double_pinyins)
            self.parsed = parse(self._instance, self.raw.encode("ascii"))
            self._refresh()

    def _refresh_composition(self):
        if self._composer is None:
            self._composer = Composer(self)
        self._order = self._composer.render()
        self.total = len(self._order)
        self.page = 0
        self.parsed = len(self.raw)
        self.preview = self.selected + (self._order[0]['text'] if self._order else '')

    @property
    def _libime(self):
        if self.config.schema != "full_pinyin" or not libime_backend.supports(self.config.fuzzy):
            return None
        return self.engine._libime

    @staticmethod
    def _unread(text):
        """A libime candidate that still holds input letters it could not read."""
        return not text.isascii() and any(c.isascii() for c in text)

    def _refresh_libime(self):
        """Candidates for the unselected input from libime, as selectable rows."""
        if self._ime_context is None:
            self._ime_context = self._libime.context()
        rest, positions = libime_backend.rewrite(self.raw[self.offset:], self.config.correction)
        flags = libime_backend.flags(self.config.fuzzy, self.config.correction)
        found = self._libime.decode(self._ime_context, rest, flags)
        if found and self._unread(found[0][0]):
            # Letters libime cannot read: decode the longest valid pinyin before
            # them instead ("nihao" of "nihaovv"), and leave the rest unparsed.
            prefix = next((rest[:end] for end in range(len(rest) - 1, 0, -1)
                           if split(rest[:end].strip("'") or "'") is not None), "")
            if prefix:
                found = self._libime.decode(self._ime_context, prefix, flags)
        order, seen = [], set()
        for text, end, reading in found:
            # libime keeps letters it cannot read inside the text ("你哈哦vv"); such
            # input stays unparsed, as with libpinyin.
            if self._unread(text):
                continue
            if not self.config.incomplete:
                # Initials alone ("nh" for 女孩) only when incomplete pinyin is on.
                path = split(rest[:end].strip("'"))
                if path is None or len(path) != len(reading.split("'")):
                    continue
            end = positions[end] + self.offset
            if (text, end) in seen or text.isascii():
                continue
            seen.add((text, end))
            full = not self.raw[end:].strip("'")
            order.append({"text": text, "pinyin": reading, "kind": "libime", "end": end,
                          "candidate_kind": "sentence" if full else "phrase",
                          "annotation": "整句" if full else "词语"})
        self._order, self.total = order, len(order)
        covered = max((row["end"] for row in order), default=self.offset)
        self.parsed = len(self.raw) if not self.raw[covered:].strip("'") else covered
        self.preview = self.selected + order[0]["text"] if order else ""

    def _refresh(self):
        self.page, self.total, self.preview = 0, 0, ""
        self._order = None
        if self._libime:
            self._refresh_libime()
        elif self.parsed and self._n.guess_sentence(self._instance):
            self.preview = self._n.sentence(self._instance)
            if self.offset < self.parsed:
                if self.parsed - self.offset > 24:
                    # Full-input N-best stays intact. Only *local phrase*
                    # enumeration is windowed; all configured fuzzy rules apply.
                    end = self.parsed
                    while end > 0 and self.raw[end-1] == "'":
                        end -= 1
                    self._n.guess_candidates(self._instance, end, 1)
                    order = [(self._instance, i) for i in range(self._n.count(self._instance))]
                    if not self._phrase_instance:
                        self._phrase_instance = self._n.alloc_instance(self._context)
                        if not self._phrase_instance:
                            raise EngineError('native_error', 'could not allocate phrase window')
                    end = self._n.prefix_end(self._instance, self.raw, self.offset)
                    self._n.reset(self._phrase_instance)
                    parse = (self._n.parse_more_full_pinyins if self.config.schema == 'full_pinyin'
                             else self._n.parse_more_double_pinyins)
                    parse(self._phrase_instance, self.raw[:end].encode('ascii'))
                    self._n.guess_sentence(self._phrase_instance)
                    self._n.guess_candidates(self._phrase_instance, self.offset, 1)
                    order.extend((self._phrase_instance, i) for i in range(self._n.count(self._phrase_instance))
                                 if self._n.candidate(self._phrase_instance, i)[2] != 1)
                    self._order = order
                    self.total = len(order)
                elif self._n.guess_candidates(self._instance, self.offset, 1):
                    self.total = self._n.count(self._instance)
        if self.offset == 0 and self.raw and self.config.schema == 'full_pinyin':
            self._expand()
        # Exact personal readings rank ahead of the language model. All remaining
        # candidates retain native N-best/bigram order. No corpus-specific weights.
        if not self._private and self.offset == 0 and self.engine._personal_index:
            if self.config.schema == "full_pinyin":
                key = self.raw.replace("'", "")
            else:
                key = (self._n.reading(self._instance, self.parsed, self.raw) or "").replace("'", "")
                if self.parsed != len(self.raw):
                    key = ""
            rows = self.engine._personal_index.get(key, [])
            if rows:
                texts = {row["text"] for row in rows}
                order = self._order if self._order is not None else range(self.total)
                self._order = list(rows) + [i for i in order
                                           if (i['text'] if isinstance(i, dict) else
                                               self._source_text(i)) not in texts]
                self.total = len(self._order)
                self.parsed = len(self.raw)
                self.preview = rows[0]["text"]

    def _expand(self):
        if not 5 <= len(self.raw) <= 64:
            return
        # libime's N-best already holds the alternative sentences; spelling
        # repairs are only tried when the input is not complete, valid pinyin,
        # and is short: each one decodes the whole input again (about 8 ms per
        # 10 letters), and a long input not yet complete is mostly mid-typing.
        if self._libime and (split(self.raw) is not None or len(self.raw) > REPAIR_LIMIT):
            return
        if self._expansion is None:
            self._expansion = Expansion(self._n, self._context)
        original = self._order if self._order is not None else list(range(self.total))
        head = [self._source_text(i) for i in original[:3]]
        rows, repaired = self._expansion.generate(self.raw, self.config, head, alternatives=not self._libime)
        if not rows:
            return
        # Preserve native top-three availability, including abbreviation choices.
        # Two repair candidates can precede them; sentence alternatives follow.
        first, seen = [], set()
        for row in rows:
            if row['text'] not in seen:
                first.append(row)
                seen.add(row['text'])
        if repaired:
            order = first[:2] + original[:3] + first[2:] + original[3:]
        else:
            order = original[:3] + first + original[3:]
        self._order, seen = [], set()
        for item in order:
            text = self._source_text(item)
            if text not in seen:
                seen.add(text)
                self._order.append(item)
        self.total = len(self._order)
        if repaired:
            self.preview = first[0]['text']

    def _source(self, source):
        return source if isinstance(source, tuple) else (self._instance, source)

    def _source_text(self, source):
        return source['text'] if isinstance(source, dict) else self._n.candidate(*self._source(source))[1]

    def _candidate(self, index):
        source = self._order[index] if self._order is not None else index
        if isinstance(source, dict):
            return {"id": f"{self._nonce}:{self.revision}:{index}", "index": index,
                    "text": source["text"], "annotation": source.get('annotation') or
                    ("用户短语" if source["kind"] == "custom" else "个人词频"),
                    "kind": source.get('candidate_kind', 'sentence'),
                    **({'input_end': source.get('end'), 'literal': not source.get('units') and '_local' not in source}
                       if source['kind'] == 'composition' else {})}
        _, text, kind = self._n.candidate(*self._source(source))
        # Native sentence candidates contain the ENTIRE sentence, even at offset > 0.
        display = text[len(self.selected):] if kind == 1 and text.startswith(self.selected) else text
        return {"id": f"{self._nonce}:{self.revision}:{index}", "index": index,
                "text": display, "annotation": "整句" if kind == 1 else "词语",
                "kind": "sentence" if kind == 1 else "phrase"}

    def _page(self, page):
        size = self.config.page_size
        start = page * size
        return {"page": page, "page_size": size, "total": self.total,
                "has_previous": page > 0, "has_next": start + size < self.total,
                "items": [self._candidate(i) for i in range(start, min(start + size, self.total))]}

    def _state(self, commits=None, handled=True):
        preedit = self.selected + self.raw[self.offset:]
        caret = len(self.selected) + max(0, self.cursor - self.offset)
        segments = []
        if self.selected:
            segments.append({"start": 0, "end": len(self.selected), "kind": "selected"})
        if self.raw[self.offset:]:
            segments.append({"start": len(self.selected), "end": len(preedit), "kind": "pinyin"})
        return {"api_version": API_VERSION, "session_id": self.session_id,
                "revision": self.revision, "handled": handled, "config": asdict(self.config),
                "input": {"text": self.raw, "cursor": self.cursor, "parsed_length": self.parsed,
                          "selected_length": self.offset},
                "preedit": {"text": preedit, "cursor": caret, "visible": bool(preedit),
                            "segments": segments, "preview": self.preview,
                            "unparsed": self.raw[self.parsed:]},
                "candidates": self._page(self.page), "commits": commits or [],
                "context": deepcopy(self.context),
                "composition": {"mode": 'mixed' if self._composition else 'pinyin',
                                "spans": spans(self.raw) if self._composition else [],
                                "literal_digits": self._composition and literal_key(self.raw, self.cursor, '1')},
                "personalization": {"active": not self._private,
                                    "learning_effective": bool(not self._private and self.config.learning and
                                                               self.engine._store and self.engine._store.learning_enabled)}}

    def state(self):
        with NATIVE_LOCK:
            self._check()
            return self._state()

    def candidates(self, page=None):
        with NATIVE_LOCK:
            self._check()
            page = self.page if page is None else page
            integer(page, "page", 0, max(0, (self.total - 1) // self.config.page_size))
            return deepcopy(self._page(page))

    def candidate_list(self, limit=200):
        """The first `limit` candidates of every page at once (fresh dicts, no copying)."""
        with NATIVE_LOCK:
            if not self._instance:
                raise EngineError("closed", "session is closed")
            return [self._candidate(i) for i in range(min(integer(limit, "limit", 0, 200), self.total))]

    def configure(self, patch):
        with NATIVE_LOCK:
            self._check()
            settings = Config.update(self.config, patch)
            self.engine._set_learning(settings.learning, explicit="learning" in patch)
            if settings != self.config:
                self.config = settings
                self._check()
                self.revision += 1
                self._decode()
            return self._state()

    def set_input(self, text, cursor=None):
        with NATIVE_LOCK:
            self._check()
            text = normalize(text)
            cursor = len(text) if cursor is None else integer(cursor, "cursor", 0, len(text))
            self._composition = False
            self.raw, self.cursor = text, cursor
            self.revision += 1
            self._decode()
            return self._state()

    def set_composition(self, text, cursor=None):
        """Lossless mixed-input counterpart of set_input; API 1.0 additive method."""
        with NATIVE_LOCK:
            self._check()
            text = composition_text(text)
            cursor = len(text) if cursor is None else integer(cursor, 'cursor', 0, len(text))
            self._composition = True
            self.raw, self.cursor = text, cursor
            self.revision += 1
            self._decode()
            return self._state()

    def input_text(self, text):
        """Insert literal-capable text at the raw cursor (digits are never selectors)."""
        with NATIVE_LOCK:
            self._check()
            text = composition_text(text)
            return self.set_composition(self.raw[:self.cursor] + text + self.raw[self.cursor:],
                                        self.cursor + len(text))

    def edit(self, start, end, text=""):
        with NATIVE_LOCK:
            self._check()
            integer(start, "start", 0, len(self.raw))
            integer(end, "end", start, len(self.raw))
            replacement = composition_text(text) if self._composition else normalize(text)
            setter = self.set_composition if self._composition else self.set_input
            return setter(self.raw[:start] + replacement + self.raw[end:], start + len(replacement))

    def input(self, text):
        with NATIVE_LOCK:
            return self.edit(self.cursor, self.cursor, text)

    def _clear(self):
        self._n.reset(self._instance)
        if self._expansion:
            self._expansion.reset()
        if self._composer:
            self._composer.reset()
        self._composition_units = []
        self._readings = []
        self.raw = self.selected = self.preview = ""
        self._order = None
        self.cursor = self.offset = self.parsed = self.page = self.total = 0
        self.revision += 1

    def reset(self):
        with NATIVE_LOCK:
            self._check()
            self._clear()
            return self._state()

    def _learn(self, text, event, reading=None):
        if self._private:
            return {"recorded": False, "reason": "sensitive_context"}
        if not event["learning_eligible"]:
            return {"recorded": False, "reason": "not_eligible"}
        if not self.config.learning:
            return {"recorded": False, "reason": "session_learning_disabled"}
        if not self.engine._store:
            return {"recorded": False, "reason": "store_unavailable"}
        try:
            reading = reading or self._n.reading(self._instance, self.parsed, self.raw)
            if not reading:
                return {"recorded": False, "reason": "incomplete_or_ambiguous_reading"}
            lexicon.check_reading(text, reading)
            return self.engine._store.record_commit(text, reading, event_id=event["event_id"],
                                                    source="engine.candidate", learning_eligible=True,
                                                    private=False, purpose="text")
        except (lexicon.LexiconError, OSError, ValueError) as exc:
            # Text must reach the application even if storage is unavailable.
            return {"recorded": False, "reason": "storage_or_reading_error",
                    "error": getattr(exc, "code", type(exc).__name__)}

    def _finish(self, text, source, candidate_id=None, reading=None):
        event = {"text": text, "source": source, "input": self.raw,
                 "candidate_id": candidate_id,
                 "learning_eligible": source == "candidate" and not self._private and
                                      (not self._composition or bool(self._composition_units)),
                 "event_id": f"{self._nonce}:commit:{self.revision}"}
        if self._composition and source == 'candidate' and self._composition_units:
            records = [self._learn(unit['text'], {**event, 'event_id': event['event_id'] + ':' + str(i)},
                                  unit['pinyin']) for i, unit in enumerate(self._composition_units)]
            event['learning'] = {'recorded': any(r['recorded'] for r in records),
                                 'reason': 'converted_pinyin_fragments_only', 'segments': records}
        else:
            event["learning"] = self._learn(text, event, reading)
        self._clear()
        return self._state([event])

    def _finish_selected_for_platform(self, candidate_id):
        with NATIVE_LOCK:
            self._check()
            if not self.selected:
                return self._state()
            selected, end = self.selected, self.offset
            reading = None if self._composition else self._n.reading(self._instance, end, self.raw)
            self.raw = self.raw[:end]
            self.parsed = end
            return self._finish(selected, "candidate", candidate_id, reading)

    def select(self, candidate_id):
        with NATIVE_LOCK:
            self._check()
            prefix = f"{self._nonce}:{self.revision}:"
            if not isinstance(candidate_id, str) or not candidate_id.startswith(prefix):
                raise EngineError("stale_candidate", "candidate belongs to another session or revision")
            suffix = candidate_id[len(prefix):]
            if not re.fullmatch(r"0|[1-9][0-9]{0,5}", suffix) or int(suffix) >= self.total:
                raise EngineError("invalid_candidate", "candidate index out of range")
            source = self._order[int(suffix)] if self._order is not None else int(suffix)
            if isinstance(source, dict):
                if source['kind'] == 'composition':
                    end, text, units = self._composer.resolve(source)
                    self._composition_units.extend(units)
                    self.selected += text
                    self.offset = self.cursor = end
                    if end == len(self.raw):
                        return self._finish(self.selected, 'candidate', candidate_id)
                    self.revision += 1
                    self._refresh_composition()
                    return self._state()
                if source['kind'] == 'libime':
                    self.selected += source['text']
                    self._readings.append(source['pinyin'])
                    self.offset = self.cursor = source['end']
                    if not self.raw[self.offset:].strip("'"):
                        return self._finish(self.selected, 'candidate', candidate_id, "'".join(self._readings))
                    self.revision += 1
                    self._refresh()
                    return self._state()
                return self._finish(source["text"], "candidate", candidate_id, source["pinyin"])
            ptr, text, kind = self._n.candidate(*self._source(source))
            end = self._n.choose_candidate(self._instance, self.offset, ptr)
            if not self.offset < end <= self.parsed:
                raise EngineError("native_error", "native selection did not advance")
            self.offset, self.cursor = end, end
            self.selected = text if kind == 1 else self.selected + text
            if self.offset == len(self.raw):
                return self._finish(self.selected, "candidate", candidate_id)
            self.revision += 1
            self._refresh()
            return self._state()

    def commit(self, mode="best"):
        with NATIVE_LOCK:
            self._check()
            if mode not in ("best", "literal"):
                raise EngineError("invalid_argument", "commit mode must be best or literal")
            if not self.raw:
                return self._state(handled=False)
            if mode == "literal":
                return self._finish(self.selected + self.raw[self.offset:], "literal")
            corrected = self._order and isinstance(self._order[0], dict) and self._order[0].get("kind") != "libime"
            if (self.parsed != len(self.raw) and not corrected) or not self.total:
                raise EngineError("incomplete_input", "no full conversion; edit input or use literal commit")
            return self.select(self._candidate(0)["id"])

    def key(self, key):
        with NATIVE_LOCK:
            self._check()
            if not isinstance(key, str):
                raise EngineError("invalid_argument", "key must be a string")
            if self._composition and key != ' ' and literal_key(self.raw, self.cursor, key):
                return self.input_text(key)
            if len(key) == 1 and re.fullmatch("[a-zA-ZüÜ']", key):
                return self.input(key)
            if key == "Escape":
                if self.raw:
                    return self.reset()
            elif key in ("BackSpace", "Delete") and self.raw:
                start = max(0, self.cursor - 1) if key == "BackSpace" else self.cursor
                end = self.cursor if key == "BackSpace" else min(len(self.raw), self.cursor + 1)
                return self.edit(start, end)
            elif key in ("Left", "Right", "Home", "End") and self.raw:
                positions = {"Left": max(0, self.cursor - 1), "Right": min(len(self.raw), self.cursor + 1),
                             "Home": 0, "End": len(self.raw)}
                setter = self.set_composition if self._composition else self.set_input
                return setter(self.raw, positions[key])
            elif key in ("Page_Up", "Page_Down") and self.total:
                last = (self.total - 1) // self.config.page_size
                self.page = max(0, min(last, self.page + (-1 if key == "Page_Up" else 1)))
                return self._state()
            elif key in ("space", " ") and self.total:
                return self.select(self._candidate(self.page * self.config.page_size)["id"])
            elif key in "123456789" and len(key) == 1 and self.total:
                index = self.page * self.config.page_size + int(key) - 1
                if int(key) <= self.config.page_size and index < self.total:
                    return self.select(self._candidate(index)["id"])
            elif key == "Return" and self.raw:
                return self.commit("literal")
            return self._state(handled=False)

    def close(self):
        with NATIVE_LOCK:
            if self._instance:
                if self._composer:
                    self._composer.close()
                    self._composer = None
                if self._expansion:
                    self._expansion.close()
                    self._expansion = None
                if self._phrase_instance:
                    self._n.free_instance(self._phrase_instance)
                    self._phrase_instance = None
                if self._ime_context is not None and self.engine._libime:
                    self.engine._libime.free(self._ime_context)
                self._ime_context = None
                self._n.free_instance(self._instance)
                self._instance = None
                if self.engine._sessions.get(self.session_id) is self:
                    self.engine._sessions.pop(self.session_id, None)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
