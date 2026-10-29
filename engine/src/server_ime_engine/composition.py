"""Lossless pinyin/literal composition; English words come from english.py.

SPDX-License-Identifier: GPL-3.0-or-later. All offsets are raw Unicode codepoints.
"""
from collections import OrderedDict
from copy import deepcopy
import re

from . import english
from .spelling import split, SYLLABLES

# Every start of a syllable ("zh", "zhu", "zhua"): what pinyin looks like mid-word.
PARTIAL = frozenset(s[:i] for s in SYLLABLES for i in range(1, len(s) + 1))
CHUNKS = re.compile(r'\s+|\S+')
PARTS = re.compile(r"[a-zü']+|[A-ZÜ]+[a-zü]*|[0-9]+(?:[._][0-9]+)*|[^a-zA-ZüÜ0-9']+")
ADDRESS = re.compile(r'(?:[^\s@]+@[^\s@]*|[A-Za-z][A-Za-z0-9+.-]*://\S*|'
                     r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.[A-Za-z]{2,}(?:[/:?#]\S*)?|/\S*)\Z')


def spans(text, base=0):
    result = []
    for chunk in CHUNKS.finditer(text):
        value = chunk.group()
        pieces = [(0, len(value), 'literal')] if value.isspace() or ADDRESS.fullmatch(value) else [
            (m.start(), m.end(), 'pinyin' if re.fullmatch("[a-zü']+", m.group()) else 'literal')
            for m in PARTS.finditer(value)]
        for start, end, kind in pieces:
            start += base + chunk.start(); end += base + chunk.start()
            if result and kind == 'literal' and result[-1]['kind'] == kind and result[-1]['end'] == start:
                result[-1]['end'] = end
                result[-1]['text'] += text[start-base:end-base]
            else:
                result.append({'start': start, 'end': end, 'kind': kind, 'text': text[start-base:end-base]})
    return result


def literal_key(text, cursor, key):
    """Digits after/in a literal span belong to that literal; pinyin digits select.

    Call input_text to insert a literal unconditionally, including a digit after
    pure pinyin. No heuristic can infer both intentions from an identical key.
    """
    if len(key) != 1 or not key.isprintable():
        return False
    if key not in '123456789':
        return True
    return not text or any(p['kind'] == 'literal' and p['start'] <= cursor <= p['end']
                           for p in spans(text))


class Composer:
    def __init__(self, owner):
        # An internal decoder is deliberately NOT registered as a public session.
        # Its lifetime is bounded by its owner, which closes it before context swaps.
        from .core import Session
        self.owner = owner
        self.decoder = Session(owner.engine, owner.session_id + '-fragment', owner.config)
        self.decoder.context = deepcopy(owner.context)
        self.decoder._rebind()
        self.cache = OrderedDict()

    def close(self):
        self.cache.clear()
        self.decoder.close()

    def reset(self):
        self.cache.clear()
        self.decoder._clear()

    def prepare(self, raw):
        d = self.decoder
        d.config = self.owner.config
        d._options()
        d.raw = raw.lower().replace('ü', 'v')
        d.cursor = len(d.raw)
        d._decode()
        return d

    def decode(self, raw):
        key = (raw, repr(self.owner.config))
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        d = self.prepare(raw)
        items = []
        for index in range(min(200, d.total)):
            item = d._candidate(index)
            source = d._order[index] if d._order is not None else index
            full = item['kind'] == 'sentence' and (d.parsed == len(d.raw) or isinstance(source, dict))
            reading = (source.get('pinyin') if isinstance(source, dict) else
                       d._n.reading(d._instance, d.parsed, d.raw)) if full else None
            items.append({'text': item['text'], 'annotation': item['annotation'],
                          'full': full, 'reading': reading, 'index': index,
                          'kind': item['kind']})
        self.cache[key] = items
        while len(self.cache) > 16:
            self.cache.popitem(last=False)
        return items

    @staticmethod
    def unit(text, reading):
        return [{'text': text, 'pinyin': reading}] if reading else []

    def choices(self, fragment):
        raw = fragment['text']
        literal = {'text': raw, 'units': [], 'annotation': '原文'}
        if fragment['kind'] == 'literal':
            return [literal]
        candidates = self.decode(raw)
        full = [r for r in candidates if r['full']][:5]
        complete = self.owner.config.schema == 'double_pinyin' or split(raw.replace('ü', 'v')) is not None
        # Incomplete/English-looking sequences keep an explicit literal choice.
        # Valid spellings and the documented correction rules remain selectable.
        readings = [dict(text=r['text'], units=self.unit(r['text'], r['reading']),
                         annotation=r['annotation']) for r in full
                    if complete or r['annotation'].startswith('纠错') or r['annotation'] == '用户短语']
        choices = readings + [literal]
        if not complete and self.owner.config.schema == 'full_pinyin' and len(raw) >= 6:
            # Ambiguous uninterrupted lowercase input: offer bounded prefix/suffix
            # combinations at grammatical syllable boundaries, without word lists.
            prefixes, suffixes = [], []
            for i in range(len(raw)-2, 3, -1):
                if split(raw[:i]) is not None:
                    prefixes.append((raw[:i], raw[i:], True))
                    if len(prefixes) == 2:
                        break
            for i in range(2, len(raw)-3):
                if split(raw[i:]) is not None:
                    suffixes.append((raw[i:], raw[:i], False))
                    if len(suffixes) == 2:
                        break
            for pinyin, rest, prefix in prefixes + suffixes:
                found = next((r for r in self.decode(pinyin) if r['full']), None)
                if found:
                    choices.append({'text': found['text'] + rest if prefix else rest + found['text'],
                                    'units': self.unit(found['text'], found['reading']),
                                    'annotation': '拼音 + 原文 · 有歧义'})
        return choices

    def render(self):
        owner = self.owner
        fragments = spans(owner.raw[owner.offset:], owner.offset)
        if not fragments:
            return []
        choices = [self.choices(p) for p in fragments]
        rows = []
        def combined(parts):
            rows.append({'text': ''.join(p['text'] for p in parts), 'kind': 'composition',
                         'annotation': '拼音与原文', 'end': len(owner.raw),
                         'units': [u for p in parts for u in p['units']], 'candidate_kind': 'sentence'})
        primary = [c[0] for c in choices]
        combined(primary)
        # Return commits the raw text too, so it waits until after the first page.
        literal = {'text': owner.raw[owner.offset:], 'kind': 'composition', 'annotation': '原文',
                   'end': len(owner.raw), 'units': [], 'candidate_kind': 'sentence'}
        # Vary one fragment at a time; do not form a Cartesian product.
        for i, alternatives in enumerate(choices):
            for alternative in alternatives[1:]:
                combined(primary[:i] + [alternative] + primary[i+1:])
                if len(rows) >= 18:
                    break
            if len(rows) >= 18:
                break
        first = fragments[0]
        native_rows = []
        if first['kind'] == 'pinyin':
            for item in self.decode(first['text']):
                if len(fragments) == 1 and item['full']:
                    native_rows.append({'text': item['text'], 'kind': 'composition',
                                        'annotation': item['annotation'], 'candidate_kind': item['kind'],
                                        'end': len(owner.raw), 'units': self.unit(item['text'], item['reading'])})
                else:
                    native_rows.append({'text': item['text'], 'kind': 'composition',
                                        'annotation': '分段 · ' + item['annotation'], 'candidate_kind': 'phrase',
                                        '_local': {'raw': first['text'], 'index': item['index'], 'start': first['start']}})
            # Merely entering the additive input API must not displace the old
            # first-page pinyin choices. Literal/ambiguous choices follow them.
            rows = native_rows[:5] + rows + native_rows[5:] if len(fragments) == 1 else rows + native_rows
        else:
            rows.append({'text': first['text'], 'kind': 'composition', 'annotation': '分段 · 原文',
                         'end': first['end'], 'units': [], 'candidate_kind': 'phrase'})
        if len(fragments) == 1 and first['kind'] == 'pinyin' and not owner.offset:
            self.english(rows, first['text'])
        rows.insert(min(len(rows), owner.config.page_size), literal)
        # Text alone is not a duplicate when consumption differs (whole vs prefix).
        seen, distinct = set(), []
        for row in rows:
            key = (row['text'], row.get('end'), row['candidate_kind'])
            if key not in seen:
                seen.add(key); distinct.append(row)
        return distinct[:200]

    @staticmethod
    def pinyin_shape(raw):
        """'complete' pinyin, 'typing' (complete syllables, then part of one), or None."""
        if split(raw) is not None:
            return 'complete'
        for cut in range(len(raw) - 1, max(-1, len(raw) - 7), -1):
            if raw[cut:] in PARTIAL and (cut == 0 or split(raw[:cut]) is not None):
                return 'typing'
        return None

    def english(self, rows, raw):
        """Put an English word typed as letters among the Chinese candidates.

        Input that cannot be pinyin ("hello", "python") puts the word first (second
        for three letters). Pinyin that is also a word keeps its Chinese first: the
        word is second while a syllable is being typed ("went"), and ends the first
        page when the pinyin is complete ("women"). A typo of a common word
        ("pyhton") is corrected only when the input cannot be pinyin.
        """
        if len(raw) < 3 or not raw.isascii() or not raw.isalpha():
            return
        size = self.owner.config.page_size
        shape = self.pinyin_shape(raw)
        word = english.lookup(raw)
        if word:
            if shape is None:
                places = [0 if len(raw) >= 4 else 1]
            elif shape == 'typing':
                places = [1]
            elif len(raw) >= 4 and raw not in SYLLABLES:
                # One syllable ("wang", "gong") is a Chinese word spelt in English.
                places = [size - 1]
            else:
                return
            words = [word]
        elif shape or len(raw) < 4:
            return
        else:
            places = [1, 2] if len(raw) >= 5 else [size - 1]
            words = english.corrections(raw, len(places))
            inside = self.embedded(raw)
            if inside:
                rows.insert(0, inside)
        for place, text in zip(places, words):
            rows.insert(min(len(rows), place), {
                'text': text, 'kind': 'composition', 'annotation': '英文', 'end': len(self.owner.raw),
                'units': [], 'candidate_kind': 'sentence'})

    @staticmethod
    def english_pieces(raw, most=3):
        """raw as complete pinyin and English words ("woyong", "Docker", "bushu"), or None.

        Fewest words first, then the most letters in words; no word is pinyin
        itself and two words never touch.
        """
        n = len(raw)
        # pinyin[start]: every end where raw[start:end] is whole syllables.
        pinyin = []
        for start in range(n):
            ends, frontier = set(), {start}
            while frontier:
                frontier = {i + size for i in frontier for size in range(1, 7)
                            if i + size <= n and raw[i:i + size] in SYLLABLES} - ends
                ends |= frontier
            pinyin.append(ends)
        # best[i]: (words, -letters, pieces, last piece was a word) for raw[:i]
        best = [None] * (n + 1)
        best[0] = (0, 0, (), True)
        for end in range(1, n + 1):
            for start in range(max(0, end - 64), end):
                before = best[start]
                if before is None:
                    continue
                piece = raw[start:end]
                word = english.lookup(piece) if 3 <= len(piece) <= 16 and end not in pinyin[start] else None
                if word and not before[3] or word and start == 0:
                    option = (before[0] + 1, before[1] - len(piece), before[2] + ((word, True),), True)
                elif before[3] and end in pinyin[start]:
                    option = (before[0], before[1], before[2] + ((piece, False),), False)
                else:
                    continue
                if option[0] <= most and (best[end] is None or option[:2] < best[end][:2]):
                    best[end] = option
        found = best[n]
        return found[2] if found and found[0] else None

    def embedded(self, raw):
        """Chinese around English words ("woyongdockerbushu" -> 我用Docker部署), or None."""
        if len(raw) < 6:
            return None
        pieces = self.english_pieces(raw)
        if not pieces or len(pieces) == 1:
            return None
        text, units = [], []
        for piece, word in pieces:
            if word:
                text.append(piece)
                continue
            found = next((r for r in self.decode(piece) if r['full']), None)
            if found is None:
                return None
            text.append(found['text'])
            units += self.unit(found['text'], found['reading'])
        return {'text': ''.join(text), 'kind': 'composition', 'annotation': '拼音与英文',
                'end': len(self.owner.raw), 'units': units, 'candidate_kind': 'sentence'}

    def resolve(self, row):
        if '_local' not in row:
            return row['end'], row['text'], row['units']
        local = row['_local']
        d = self.prepare(local['raw'])
        source = d._order[local['index']] if d._order is not None else local['index']
        if isinstance(source, dict):
            end, text, reading = source.get('end', len(d.raw)), source['text'], source['pinyin']
        else:
            ptr, text, _ = d._n.candidate(*d._source(source))
            end = d._n.choose_candidate(d._instance, 0, ptr)
            reading = d._n.reading(d._instance, end, d.raw)
        if not 0 < end <= len(local['raw']):
            from .core import EngineError
            raise EngineError('native_error', 'fragment did not advance')
        return local['start'] + end, text, self.unit(text, reading)
