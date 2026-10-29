"""Bounded alternative sentence decoding through libpinyin's public ABI.

SPDX-License-Identifier: GPL-3.0-or-later. No dictionary mutation or training.
"""
from .spelling import EDIT_RULES, hypotheses, split

MAX_REPAIR_READINGS = 4


class Expansion:
    def __init__(self, native, context):
        self.native = native
        self.context = context
        self.instance = native.alloc_instance(context)
        self.prefix_instance = native.alloc_instance(context)
        if not self.instance or not self.prefix_instance:
            self.close()
            raise MemoryError('could not allocate alternative decoder')

    def close(self):
        if self.prefix_instance:
            self.native.free_instance(self.prefix_instance)
            self.prefix_instance = None
        if self.instance:
            self.native.free_instance(self.instance)
            self.instance = None

    def reset(self):
        self.native.reset(self.instance)
        self.native.reset(self.prefix_instance)

    def parse(self, reading, phrases=False):
        n, instance = self.native, self.instance
        n.reset(instance)
        if n.parse_more_full_pinyins(instance, reading.encode('ascii')) != len(reading):
            return []
        if not n.guess_sentence(instance):
            return []
        # At the end of the matrix, the ABI returns the existing N-best without
        # searching every phrase in a fuzzy matrix. get_sentence(i) alone cannot
        # safely probe its count: the native API asserts for an out-of-range i.
        n.guess_candidates(instance, 0 if phrases else len(reading), 1)
        return [text for i in range(min(3, n.count(instance)))
                for _, text, kind in [n.candidate(instance, i)] if kind == 1]

    def repairs(self, raw, rules):
        n, instance = self.native, self.instance
        result = []
        # A deterministic beam bounds repeated whole-sentence decoding. All four
        # edit generators remain enabled; spelling priors choose the beam.
        for hypothesis in hypotheses(raw, rules)[:MAX_REPAIR_READINGS]:
            reading = hypothesis['pinyin']
            texts = self.parse(reading)
            if not texts or any(len(t) != len(reading.split("'")) for t in texts):
                continue
            score = n.lexical_score(instance, texts[0])
            for rank, text in enumerate(texts):
                result.append({'text': text, 'pinyin': reading, 'kind': 'correction',
                               'annotation': '纠错 · ' + reading,
                               '_rank': (hypothesis['cost'], -score, reading, rank)})
        result.sort(key=lambda row: row['_rank'])
        return result

    def sentences(self, raw, existing):
        """Two distinct first-syllable constraints diversify suffix-only N-best.

        The original three native candidates keep their order. A spare instance
        applies constraints and redecodes the whole sentence; the live selection
        state and raw input are untouched. Only complete readings are eligible.
        """
        path = split(raw)
        if path is None or len(path) < 4:
            return []
        reading = "'".join(path)
        # Two syllables keep one-character phrase candidates from being
        # deduplicated against the prefix's one-character N-best sentences.
        # Enumeration is bounded here; the complete sentence is still decoded.
        n, instance, prefix_instance = self.native, self.instance, self.prefix_instance
        prefix_reading = "'".join(path[:2])
        n.reset(prefix_instance)
        n.parse_more_full_pinyins(prefix_instance, prefix_reading.encode('ascii'))
        n.guess_sentence(prefix_instance)
        n.guess_candidates(prefix_instance, 0, 1)
        first_chars = {text[:1] for text in existing}
        choices = []
        for i in range(min(128, n.count(prefix_instance))):
            ptr, text, kind = n.candidate(prefix_instance, i)
            if kind != 1 and len(text) == 1 and text not in first_chars:
                choices.append((ptr, text))
                first_chars.add(text)
                if len(choices) == 2:
                    break
        if not choices or not self.parse(reading):
            return []
        result = []
        for ptr, prefix in choices:
            n.clear_constraint(instance, 0)
            end = n.choose_candidate(instance, 0, ptr)
            if end <= 0 or not n.guess_sentence(instance):
                continue
            text = n.sentence(instance)
            if text.startswith(prefix) and len(text) == len(path) and text not in existing:
                result.append({'text': text, 'pinyin': reading, 'kind': 'alternative',
                               'annotation': '整句 · 首音节约束'})
        return result

    def generate(self, raw, config, existing, alternatives=True):
        if config.schema != 'full_pinyin' or not 5 <= len(raw) <= 64:
            return [], False
        rules = config.correction['rules'] or EDIT_RULES
        edits = [r for r in EDIT_RULES if r in rules] if config.correction['enabled'] else []
        if edits:
            repairs = self.repairs(raw, edits)
            if repairs:
                return repairs, True
        return (self.sentences(raw, existing) if alternatives else []), False
