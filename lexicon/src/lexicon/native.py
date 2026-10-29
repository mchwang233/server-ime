"""ctypes binding for the pinned libpinyin 2.6.0 user-dictionary mechanism.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import ctypes as C
import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from .errors import LexiconError
from .records import sha256_file

USER_DICTIONARY = 7
USER_FILES = ("user.conf", "user_phrase_index.bin", "user_pinyin_index.bin", "user_bigram.db")
_LOCK = threading.RLock()
P = C.c_void_p


class Libpinyin:
    """The same native library and data that the conversion engine loads.

    Only the documented import/export/save entry points are used.  The system
    data directory is never written: libpinyin writes user tables to the user
    directory supplied to ``pinyin_init``.
    """

    def __init__(self, runtime_dir, system_dir):
        self.runtime_dir = Path(runtime_dir).resolve()
        self.system_dir = Path(system_dir).resolve()
        lib = self.runtime_dir / "lib"
        if not (lib / "libpinyin.so.13.0.0").is_file():
            raise LexiconError("native_unavailable", f"libpinyin runtime not found in {lib}")
        if not (self.system_dir / "table.conf").is_file():
            raise LexiconError("native_unavailable", f"engine data not found in {self.system_dir}")
        with _LOCK:
            self.handles = [C.CDLL(str(lib / name), mode=C.RTLD_GLOBAL) for name in (
                "libpcre.so.1", "libdb-5.3.so", "libglib-2.0.so.0")]
            self.glib = self.handles[-1]
            self.glib.g_free.argtypes = [P]
            self.glib.g_free.restype = None
            self.lib = C.CDLL(str(lib / "libpinyin.so.13.0.0"))
            self.init = self.lib.pinyin_init
            self.init.restype = P
            self.init.argtypes = [C.c_char_p, C.c_char_p]
            self.fini = self.lib.pinyin_fini
            self.fini.argtypes = [P]
            self.begin_add = self.lib.pinyin_begin_add_phrases
            self.begin_add.restype = P
            self.begin_add.argtypes = [P, C.c_ubyte]
            self.add_phrase = self.lib.pinyin_iterator_add_phrase
            self.add_phrase.restype = C.c_bool
            self.add_phrase.argtypes = [P, C.c_char_p, C.c_char_p, C.c_int]
            self.end_add = self.lib.pinyin_end_add_phrases
            self.end_add.argtypes = [P]
            self.save = self.lib.pinyin_save
            self.save.restype = C.c_bool
            self.save.argtypes = [P]
            self.begin_export = self.lib.pinyin_begin_get_phrases
            self.begin_export.restype = P
            self.begin_export.argtypes = [P, C.c_uint]
            self.has_next = self.lib.pinyin_iterator_has_next_phrase
            self.has_next.restype = C.c_bool
            self.has_next.argtypes = [P]
            self.get_next = self.lib.pinyin_iterator_get_next_phrase
            self.get_next.restype = C.c_bool
            self.get_next.argtypes = [P, C.POINTER(P), C.POINTER(P), C.POINTER(C.c_int)]
            self.end_export = self.lib.pinyin_end_get_phrases
            self.end_export.argtypes = [P]

    @contextmanager
    def _context(self, user_dir):
        with _LOCK:
            context = self.init(str(self.system_dir).encode(), str(user_dir).encode())
            if not context:
                raise LexiconError("native_build_failed", "libpinyin context initialization failed")
            try:
                yield context
            finally:
                self.fini(context)

    def build(self, user_dir, entries):
        """Write entries into a fresh libpinyin user dictionary.

        ``user_dir`` must be an empty directory.  Returns counts and file
        hashes; raises without writing a partial table if any entry is rejected.
        """
        user_dir = Path(user_dir).resolve()
        user_dir.mkdir(parents=True, exist_ok=True)
        if any(user_dir.iterdir()):
            raise LexiconError("native_build_failed", f"user directory is not empty: {user_dir}")
        accepted, rejected = [], []
        with self._context(user_dir) as context:
            iterator = self.begin_add(context, USER_DICTIONARY)
            if not iterator:
                raise LexiconError("native_build_failed", "cannot create import iterator")
            try:
                for entry in entries:
                    ok = bool(self.add_phrase(
                        iterator,
                        entry["text"].encode("utf-8"),
                        entry["pinyin"].encode("utf-8"),
                        int(entry["count"]),
                    ))
                    (accepted if ok else rejected).append(entry)
            finally:
                self.end_add(iterator)
            if not self.save(context):
                raise LexiconError("native_build_failed", "libpinyin did not save the user dictionary")
        if rejected:
            raise LexiconError(
                "native_build_failed",
                f"libpinyin rejected {len(rejected)} entries",
                {"rejected": [{"text": item["text"], "pinyin": item["pinyin"]} for item in rejected[:20]]},
            )
        files = self.verify_user_dir(user_dir)
        return {"accepted": len(accepted), "rejected": 0, "files": files}

    def export(self, user_dir):
        """Read back the user table through libpinyin's export iterator."""
        user_dir = Path(user_dir).resolve()
        rows = []
        with self._context(user_dir) as context:
            iterator = self.begin_export(context, USER_DICTIONARY)
            if not iterator:
                raise LexiconError("native_build_failed", "cannot create export iterator")
            try:
                while self.has_next(iterator):
                    phrase = P()
                    pinyin = P()
                    count = C.c_int(-1)
                    ok = self.get_next(iterator, C.byref(phrase), C.byref(pinyin), C.byref(count))
                    if not ok:
                        break
                    try:
                        text = C.string_at(phrase).decode("utf-8") if phrase.value else ""
                        reading = C.string_at(pinyin).decode("utf-8") if pinyin.value else ""
                    finally:
                        if phrase.value:
                            self.glib.g_free(phrase)
                        if pinyin.value:
                            self.glib.g_free(pinyin)
                    rows.append({"text": text, "pinyin": reading, "count": count.value})
            finally:
                self.end_export(iterator)
        return rows

    def verify_user_dir(self, user_dir):
        user_dir = Path(user_dir)
        missing = [name for name in USER_FILES if not (user_dir / name).is_file()]
        if missing:
            raise LexiconError("native_build_failed", "user dictionary is incomplete", {"missing": missing})
        return {
            name: {"sha256": sha256_file(user_dir / name), "bytes": (user_dir / name).stat().st_size}
            for name in USER_FILES
        }

    def build_into(self, destination, entries):
        """Build a complete user directory and swap it in after verification.

        The previous directory is kept until the new one has been read back and
        checked, so a failed build never leaves a partially written table.
        """
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=destination.name + ".tmp-", dir=str(destination.parent)))
        shutil.rmtree(staging)
        previous = None
        try:
            result = self.build(staging, entries)
            exported = self.export(staging)
            expected = {(row["text"], row["pinyin"]) for row in entries}
            actual = {(row["text"], row["pinyin"]) for row in exported}
            missing = sorted(expected - actual)
            if missing:
                raise LexiconError(
                    "native_build_failed",
                    "exported user dictionary is missing entries",
                    {"missing": missing[:20]},
                )
            if destination.exists():
                previous = Path(tempfile.mkdtemp(prefix=destination.name + ".old-", dir=str(destination.parent)))
                shutil.rmtree(previous)
                os.replace(destination, previous)
            os.replace(staging, destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            if previous is not None and previous.exists() and not destination.exists():
                os.replace(previous, destination)
            raise
        if previous is not None:
            shutil.rmtree(previous, ignore_errors=True)
        result["exported"] = len(exported)
        result["files"] = self.verify_user_dir(destination)
        return result
