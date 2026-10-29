"""Bounded spelling hypotheses from the pinned parser's syllable alphabet.

No words, evaluation references or input history are stored in this module.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
from pathlib import Path

SYLLABLES = frozenset(json.loads((Path(__file__).resolve().parents[2] /
                                'data/syllables-v1.json').read_text())['syllables'])
EDIT_RULES = ('transpose', 'delete', 'insert', 'substitute')
KEYBOARD = ('qwertyuiop', 'asdfghjkl', 'zxcvbnm')
KEY_POS = {c: (i, j) for i, row in enumerate(KEYBOARD) for j, c in enumerate(row)}


def split(text):
    """A shortest complete syllable path; explicit separators are hard boundaries."""
    result = []
    for chunk in text.split("'"):
        if not chunk:
            return None
        paths = [None] * (len(chunk) + 1)
        paths[0] = ()
        for end in range(1, len(chunk) + 1):
            for start in range(max(0, end - 6), end):
                if paths[start] is not None and chunk[start:end] in SYLLABLES:
                    candidate = paths[start] + (chunk[start:end],)
                    if paths[end] is None or len(candidate) < len(paths[end]):
                        paths[end] = candidate
        if paths[-1] is None:
            return None
        result.extend(paths[-1])
    return tuple(result)


def hypotheses(raw, rules=EDIT_RULES):
    """At most eight one-edit, complete readings; never correct valid full pinyin.

    A transposition costs less than insertion/deletion; substitutions are limited
    to adjacent QWERTY keys. Repeated-letter deletion costs less than other edits.
    Minimum syllable count prevents treating stray letters as whole extra words.
    These are spelling priors, independent of any Chinese target strings.
    """
    if len(raw) < 5 or len(raw) > 64 or "'" in raw or split(raw) is not None:
        return []
    # Reuse complete prefix/suffix paths: an edit touches only one syllable.
    # This avoids reparsing hundreds of whole-sentence edit variants per key.
    prefix = [None] * (len(raw) + 1)
    suffix = [None] * (len(raw) + 1)
    prefix[0] = suffix[-1] = ()
    for end in range(1, len(raw) + 1):
        for start in range(max(0, end - 6), end):
            if prefix[start] is not None and raw[start:end] in SYLLABLES:
                path = prefix[start] + (raw[start:end],)
                if prefix[end] is None or len(path) < len(prefix[end]):
                    prefix[end] = path
    for start in range(len(raw) - 1, -1, -1):
        for end in range(start + 1, min(len(raw), start + 6) + 1):
            if suffix[end] is not None and raw[start:end] in SYLLABLES:
                path = (raw[start:end],) + suffix[end]
                if suffix[start] is None or len(path) < len(suffix[start]):
                    suffix[start] = path
    found = {}

    def add(text, cost, rule, left, right):
        if text in SYLLABLES or not text:
            path = left + ((text,) if text else ()) + right
            if len(path) < 2:
                return
            key = "'".join(path)
            row = (len(path), cost, key, rule)
            if key not in found or row < found[key]:
                found[key] = row

    for start, left in enumerate(prefix):
        if left is None:
            continue
        for end in range(start + 1, min(len(raw), start + 7) + 1):
            right = suffix[end]
            if right is None:
                continue
            part = raw[start:end]
            for i, ch in enumerate(part):
                if 'transpose' in rules and i + 1 < len(part) and ch != part[i+1]:
                    add(part[:i] + part[i+1] + ch + part[i+2:], 0.5, 'transpose', left, right)
                if 'delete' in rules:
                    repeated = (i > 0 and part[i-1] == ch) or (i + 1 < len(part) and part[i+1] == ch)
                    add(part[:i] + part[i+1:], 0.5 if repeated else 1.0, 'delete', left, right)
                if 'substitute' in rules:
                    y, x = KEY_POS[ch]
                    for letter, (yy, xx) in KEY_POS.items():
                        if letter != ch and abs(y-yy) <= 1 and abs(x-xx) <= 1:
                            add(part[:i] + letter + part[i+1:], 1.0, 'substitute', left, right)
            if 'insert' in rules:
                for i in range(len(part) + 1):
                    for letter in 'abcdefghijklmnopqrstuvwxyz':
                        add(part[:i] + letter + part[i:], 1.0, 'insert', left, right)
    rows = sorted(found.values())
    if not rows:
        return []
    return [dict(pinyin=key, cost=cost, rule=rule) for length, cost, key, rule in rows
            if length == rows[0][0]][:8]
