"""English words typed in Chinese mode: exact words and one-typo corrections.

The word list is engine/data/english-v1.txt (most frequent first; provenance in
its header). SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path

LETTERS = "abcdefghijklmnopqrstuvwxyz"
# Corrections are only offered for these most frequent words, so a rare word
# one letter away does not show up for every typo.
CORRECTION_RANK = 20000


def _load():
    path = Path(__file__).resolve().parents[2] / "data/english-v1.txt"
    words = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            words.setdefault(line.lower(), (len(words), line))
    return words


WORDS = _load()


def lookup(raw):
    """The word as it is written ("GitHub" for "github"), or None."""
    found = WORDS.get(raw)
    return found[1] if found else None


def edits(raw):
    """Every spelling one transposition, deletion, insertion or substitution away."""
    splits = [(raw[:i], raw[i:]) for i in range(len(raw) + 1)]
    result = {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1}
    result |= {a + b[1:] for a, b in splits if b}
    result |= {a + c + b for a, b in splits for c in LETTERS}
    result |= {a + c + b[1:] for a, b in splits if b for c in LETTERS if c != b[0]}
    result.discard(raw)
    return result


def corrections(raw, limit=2):
    """The most frequent words one typo away from raw, best first."""
    found = sorted(WORDS[word] for word in edits(raw) if WORDS.get(word, (CORRECTION_RANK,))[0] < CORRECTION_RANK)
    return [text for _, text in found[:limit]]
