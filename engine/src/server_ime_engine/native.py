"""Private, typed binding to the pinned libpinyin 2.6 C ABI.

SPDX-License-Identifier: GPL-3.0-or-later
Opaque native objects never cross the public API boundary.
"""
import ctypes as C
import math
from pathlib import Path
from threading import RLock

NATIVE_LOCK = RLock()
P = C.c_void_p
PP = C.POINTER(P)
S = C.c_char_p
U = C.c_uint
Z = C.c_size_t
B = C.c_bool


class Native:
    def __init__(self, runtime_dir):
        self.root = Path(runtime_dir).resolve()
        lib = self.root / "lib"
        self.handles = [C.CDLL(str(lib / name), mode=C.RTLD_GLOBAL) for name in (
            "libpcre.so.1", "libdb-5.3.so", "libglib-2.0.so.0")]
        self.glib = self.handles[-1]
        self.glib.g_free.argtypes = [P]
        self.glib.g_free.restype = None
        self.lib = C.CDLL(str(lib / "libpinyin.so.13.0.0"))
        signatures = {
            "init": (P, [S, S]), "fini": (None, [P]),
            "set_options": (B, [P, U]), "alloc_instance": (P, [P]),
            "free_instance": (None, [P]), "reset": (B, [P]),
            "parse_more_full_pinyins": (Z, [P, S]),
            "parse_more_double_pinyins": (Z, [P, S]),
            "set_double_pinyin_scheme": (B, [P, C.c_int]),
            "begin_add_phrases": (P, [P, C.c_ubyte]),
            "iterator_add_phrase": (B, [P, S, S, C.c_int]),
            "end_add_phrases": (None, [P]),
            "get_pinyin_key": (B, [P, Z, PP]),
            "get_pinyin_key_rest": (B, [P, Z, PP]),
            "get_pinyin_key_rest_positions": (B, [P, P, C.POINTER(C.c_uint16), C.POINTER(C.c_uint16)]),
            "get_pinyin_string": (B, [P, P, PP]),
            "get_pinyin_is_incomplete": (B, [P, P]),
            "guess_sentence": (B, [P]),
            "phrase_segment": (B, [P, S]),
            "get_n_phrase": (B, [P, C.POINTER(U)]),
            "get_phrase_token": (B, [P, U, C.POINTER(U)]),
            "token_get_unigram_frequency": (B, [P, U, C.POINTER(U)]),
            "get_sentence": (B, [P, C.c_ubyte, PP]),
            "guess_candidates": (B, [P, Z, C.c_int]),
            "get_n_candidate": (B, [P, C.POINTER(U)]),
            "get_candidate": (B, [P, U, PP]),
            "get_candidate_string": (B, [P, P, C.POINTER(S)]),
            "get_candidate_type": (B, [P, P, C.POINTER(C.c_int)]),
            "choose_candidate": (C.c_int, [P, Z, P]),
            "clear_constraint": (B, [P, Z]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(self.lib, "pinyin_" + name)
            fn.restype, fn.argtypes = result, args
            setattr(self, name, fn)

    def sentence(self, instance, index=0):
        value = P()
        ok = self.get_sentence(instance, index, C.byref(value))
        try:
            return C.string_at(value).decode("utf-8") if ok and value.value else ""
        finally:
            if value.value:
                self.glib.g_free(value)

    def prefix_end(self, instance, raw, start, limit=24):
        """A bounded phrase-search window on the parser's existing key boundaries."""
        offset, last = start, start
        while offset < len(raw):
            if not raw[offset:].strip("'"):
                break
            rest = P()
            if not self.get_pinyin_key_rest(instance, offset, C.byref(rest)):
                break
            begin, end = C.c_uint16(), C.c_uint16()
            self.get_pinyin_key_rest_positions(instance, rest, C.byref(begin), C.byref(end))
            if end.value <= offset or end.value > start + limit:
                break
            last = offset = end.value
        return last if last > start else min(len(raw), start + limit)

    def count(self, instance):
        count = U()
        self.get_n_candidate(instance, C.byref(count))
        return count.value

    def lexical_score(self, instance, text):
        """Per-character phrase-frequency prior, used only between typo repairs.

        Native phrase segmentation supplies tokens and their stock/personal
        unigram counts. A fixed 1e9 mass normalizes counts (no target fitting).
        This is a lexical heuristic, not the backend's inaccessible N-best score.
        """
        if not text or not self.phrase_segment(instance, text.encode('utf-8')):
            return -math.inf
        count, token, freq = U(), U(), U()
        self.get_n_phrase(instance, C.byref(count))
        score = 0.0
        for i in range(count.value):
            self.get_phrase_token(instance, i, C.byref(token))
            if not token.value:
                continue  # continuation positions in the native segmentation
            if not self.token_get_unigram_frequency(instance, token.value, C.byref(freq)):
                return -math.inf
            score += math.log((freq.value + 1) / 1_000_000_000)
        return score / len(text)

    def candidate(self, instance, index):
        ptr = P()
        if not self.get_candidate(instance, index, C.byref(ptr)):
            raise IndexError(index)
        text, kind = S(), C.c_int()
        self.get_candidate_string(instance, ptr, C.byref(text))
        self.get_candidate_type(instance, ptr, C.byref(kind))
        return ptr, text.value.decode("utf-8"), kind.value

    def add_entries(self, context, entries):
        """In-memory only. Never train/save or open a writable personal model."""
        iterator = self.begin_add_phrases(context, 7)  # USER_DICTIONARY
        if not iterator:
            raise ValueError("cannot allocate dictionary iterator")
        try:
            for entry in entries:
                # Native import excludes length 16; exact-match overlay supports it.
                if len(entry["text"]) >= 16:
                    continue
                if not self.iterator_add_phrase(iterator, entry["text"].encode(),
                                                entry["pinyin"].encode(), entry["count"]):
                    raise ValueError("native dictionary rejected a validated entry")
        finally:
            self.end_add_phrases(iterator)

    def reading(self, instance, parsed, raw):
        """Canonical syllables from the parser, or None for an incomplete path.

        Callers also check character count: resplit/ambiguous paths must not be
        guessed into the persistent store. Native static key pointers stay local.
        """
        offset, parts = 0, []
        while offset < parsed:
            if not raw[offset:parsed].strip("'"):
                offset = parsed
                break
            # The ABI expects the position BEFORE separator zero-keys. It skips
            # them internally; advancing past an apostrophe triggers a native
            # assertion in get_pinyin_key/get_pinyin_key_rest (e.g. xi'an).
            key, rest, value = P(), P(), P()
            if not self.get_pinyin_key(instance, offset, C.byref(key)):
                return None
            if self.get_pinyin_is_incomplete(instance, key):
                return None
            if not self.get_pinyin_string(instance, key, C.byref(value)):
                return None
            try:
                parts.append(C.string_at(value).decode("ascii"))
            finally:
                self.glib.g_free(value)
            if not self.get_pinyin_key_rest(instance, offset, C.byref(rest)):
                return None
            begin, end = C.c_uint16(), C.c_uint16()
            self.get_pinyin_key_rest_positions(instance, rest, C.byref(begin), C.byref(end))
            if end.value <= offset:
                return None
            offset = end.value
        return "'".join(parts) if offset == parsed else None
