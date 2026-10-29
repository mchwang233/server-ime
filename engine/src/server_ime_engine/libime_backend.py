"""Full-pinyin sentence decoding and next-word prediction through libime (fcitx5).

SPDX-License-Identifier: GPL-3.0-or-later. libime is LGPL-2.1-or-later; its
dictionary and language model come from its release (vendor/libime/data).
The C++ glue is engine/native/sime_libime.cpp.
"""
import ctypes as C
import re
from pathlib import Path

LIBRARIES = ("libFcitx5Utils.so.2", "libIMECore.so.0", "libIMEPinyin.so.0")
DATA = ("sc.dict", "extb.dict", "zh_CN.lm", "zh_CN.lm.predict")
MAX_CANDIDATES = 200
NBEST, BEAM, FRAME = 2, 5, 10

# libime PinyinFuzzyFlag bits for the engine's named options (options.py).
# g_k has none: a session using it decodes with libpinyin (core.Session._libime).
INNER = 1 << 14 | 1 << 15  # xian -> xi'an and its short forms
FUZZY = {"c_ch": 1 << 8, "f_h": 1 << 9, "l_n": 1 << 10, "s_sh": 1 << 11, "z_zh": 1 << 12,
         "l_r": 1 << 20, "an_ang": 1 << 2, "en_eng": 1 << 3, "in_ing": 1 << 5}
CORRECTION = {"gn_ng": 1 << 0, "mg_ng": 1 << 0, "v_u": 1 << 1, "ue_ve": 1 << 13,
              "iou_iu": 1 << 18, "uei_ui": 1 << 18, "uen_un": 1 << 18, "on_ong": 1 << 18}
# Words the next-word list leaves out: punctuation is typed, not predicted.
PUNCTUATION = set("，。、！？；：“”‘’（）《》…—,.!?;:\"'()")


def available(root):
    root = Path(root)
    return all((root / "lib" / name).is_file() for name in LIBRARIES + ("libsime_libime.so",)) and \
        all((root / "data" / name).is_file() for name in DATA)


# libpinyin's spelling corrections libime lacks, as rewrites of the input before
# decoding (rule, pattern, replacement). Each only matches a misspelt final.
CONSONANT = "(?<=[bcdfghjklmnpqrstwxyz])"
REWRITES = [(name, re.compile(pattern), text) for name, pattern, text in (
    ("gn_ng", r"(?<=[aeiou])gn(?![aeiouv])", "ng"), ("mg_ng", r"(?<=[aeiou])mg(?![aeiouv])", "ng"),
    ("iou_iu", CONSONANT + "iou", "iu"), ("uei_ui", CONSONANT + "uei", "ui"),
    ("uen_un", CONSONANT + "uen", "un"), ("on_ong", r"on(?![aeiouvg])", "ong"),
    ("v_u", r"(?<=[jqxy])v", "u"))]


def rewrite(raw, correction):
    """(input to decode, positions): positions[i] is where its i-th letter starts in raw."""
    positions = list(range(len(raw) + 1))
    if not correction["enabled"]:
        return raw, positions
    rules = set(correction["rules"] or CORRECTION)
    for name, pattern, text in REWRITES:
        if name not in rules:
            continue
        out, mapped, last = [], [], 0
        for match in pattern.finditer(raw):
            out.append(raw[last:match.start()])
            mapped.extend(positions[last:match.start()])
            out.append(text)
            mapped.extend([positions[match.start()]] + [positions[match.end()]] * (len(text) - 1))
            last = match.end()
        if not out:
            continue
        out.append(raw[last:])
        mapped.extend(positions[last:])
        raw, positions = "".join(out), mapped
    return raw, positions


def supports(fuzzy):
    return not fuzzy["enabled"] or all(name in FUZZY for name in (fuzzy["rules"] or ("g_k",)))


def flags(fuzzy, correction):
    value = INNER
    if fuzzy["enabled"]:
        value |= sum({FUZZY[name] for name in (fuzzy["rules"] or FUZZY) if name in FUZZY})
    if correction["enabled"]:
        value |= sum({CORRECTION[name] for name in (correction["rules"] or CORRECTION) if name in CORRECTION})
    return value


_SHARED = {}


def shared(root):
    """One loaded model per runtime folder in this process; release() when done."""
    key = str(Path(root).resolve())
    if key not in _SHARED:
        _SHARED[key] = [Libime(key), 0]
    _SHARED[key][1] += 1
    return _SHARED[key][0]


def release(model):
    for key, entry in list(_SHARED.items()):
        if entry[0] is model:
            entry[1] -= 1
            if entry[1] <= 0:
                del _SHARED[key]
                model.close()
            return


class Libime:
    """One dictionary + language model; decoding contexts are per session.

    Callers serialize all use (core.NATIVE_LOCK): fuzzy flags are model-wide.
    """

    def __init__(self, root):
        root = Path(root).resolve()
        self._handles = [C.CDLL(str(root / "lib" / name), mode=C.RTLD_GLOBAL) for name in LIBRARIES]
        lib = self.lib = C.CDLL(str(root / "lib/libsime_libime.so"))
        P, S, I = C.c_void_p, C.c_char_p, C.c_int
        for name, restype, argtypes in (
                ("sime_open", P, [S, S, S, I]), ("sime_close", None, [P]),
                ("sime_ctx_new", P, [P]),
                ("sime_ctx_free", None, [P]), ("sime_decode", I, [P, S, I, C.c_uint]),
                ("sime_text", S, [P, I]), ("sime_pinyin", S, [P, I]), ("sime_end", I, [P, I]),
                ("sime_predict", S, [P, S, I]), ("sime_tune", None, [P, I, I, I]),
                ("sime_known", I, [P, S])):
            function = getattr(lib, name)
            function.restype, function.argtypes = restype, argtypes
        data = root / "data"
        self.ime = lib.sime_open(str(data / "sc.dict").encode(), str(data / "extb.dict").encode(),
                                 str(data / "zh_CN.lm").encode(), 2)
        if not self.ime:
            raise OSError("libime could not load its dictionary or language model")
        # Two sentences, narrower search than fcitx's 20/40: the same first choices on the
        # quality corpus, and the slowest keystroke drops from 45 ms to about 14 ms.
        lib.sime_tune(self.ime, NBEST, BEAM, FRAME)

    def close(self):
        if self.ime:
            self.lib.sime_close(self.ime)
            self.ime = None

    def context(self):
        return self.lib.sime_ctx_new(self.ime)

    def free(self, context):
        self.lib.sime_ctx_free(context)

    def decode(self, context, raw, fuzzy_flags):
        """[(text, end, reading)] for raw: end is how much of raw the candidate covers."""
        count = self.lib.sime_decode(context, raw.encode("ascii"), 0, fuzzy_flags)
        result = []
        for i in range(min(max(count, 0), MAX_CANDIDATES)):
            text = self.lib.sime_text(context, i).decode()
            end = self.lib.sime_end(context, i)
            reading = self.lib.sime_pinyin(context, i).decode()
            if text and 0 < end <= len(raw):
                result.append((text, end, reading))
        return result

    def last_words(self, text):
        """Words the model knows at the end of text, longest (up to 4 characters) first."""
        return [text[-size:] for size in range(min(4, len(text)), 0, -1)
                if self.lib.sime_known(self.ime, text[-size:].encode())]

    def predict(self, history, limit=10):
        """Next words after the committed texts (most recent last), best first.

        The last text's longest known ending is the context, with the text before
        it when that is known too; when the model has nothing to follow it, a
        shorter ending is tried.
        """
        if not history:
            return []
        before = self.last_words(history[-2])[:1] if len(history) > 1 else []
        for position, word in enumerate(self.last_words(history[-1])):
            words = (before if position == 0 else []) + [word]
            found = self.lib.sime_predict(self.ime, "\t".join(words).encode(), limit * 2).decode()
            result = [item for item in found.split("\t") if item and not set(item) & PUNCTUATION][:limit]
            if result:
                return result
        return []
