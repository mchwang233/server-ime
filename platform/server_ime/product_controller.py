"""Product key policy. employee_id=platform; conversion stays engine-owned."""
from .controller import (Controller, RELEASE, SHORTCUT, CONTROL, SHIFT, TAB,
                         LEFT, RIGHT, HOME, END, UP, DOWN, PAGE_UP, PAGE_DOWN, ESCAPE)
from .port import Candidate, Conversion
from ime_interface import keymap
from ime_interface.punctuation import Punctuation, ASCII_SAFE

# Only sentence stops terminate pinyin. Address/path operators (including :,
# / and @) and the pinyin apostrophe must reach the mixed-input engine intact.
SENTENCE_STOPS = frozenset(',.?!')
PREDICTIONS = 10  # next words offered after a commit (two pages of five)


class ProductController(Controller):
    def __init__(self, *args, settings, config_revision=1, **kwargs):
        super().__init__(*args, **kwargs)
        # Next-word suggestions after a commit: the texts committed in this
        # context since its last pause (never stored), and whether the shown
        # candidates are suggestions rather than conversions.
        self.history, self.predicting, self.last_commit = [], False, ""
        # While a commit and its suggestions are worked out, snapshots wait and go
        # out once, so the window does not empty and refill in between.
        self._holding, self._pending = False, False
        send = self.commit

        def commit(text):
            self.last_commit = text
            send(text)
        self.commit = commit
        self.configure_platform(settings, config_revision, emit=False)

    def configure_platform(self, settings, revision, emit=True):
        self.settings = settings
        self.config_revision = revision
        self.page_size = settings['input']['page_size']
        _, errors, self.bindings = keymap.validate_shortcuts(settings['shortcuts'])
        if errors:
            raise ValueError(errors)
        self.prediction = bool(settings['input'].get('prediction', False))
        p = settings['punctuation']
        self.punctuation = Punctuation(p['chinese'], p['use_full_width_pairs'])
        if emit:
            self.reset()

    def snapshot(self):
        state = super().snapshot()
        state['configuration_revision'] = getattr(self, 'config_revision', 1)
        state['candidate_presentation'] = 'custom'
        return state

    def clear(self):
        self.predicting = False
        super().clear()

    def focus_out(self):
        self.history = []
        self.punctuation.reset_pairs()
        super().focus_out()

    def suggest(self, text):
        """Offer the words likely to follow text, which was just committed."""
        self.history = (self.history + [text])[-2:]
        predict = getattr(self.session, 'predict', None)
        if not (self.prediction and predict and text and self.mode == 'zh'):
            return
        try:
            words = [w for w in predict(self.history, PREDICTIONS) if isinstance(w, str) and w][:PREDICTIONS]
        except Exception:
            words = []
        if not words:
            return
        self.conversion = Conversion("", 0, tuple(
            Candidate(f"predict:{self.revision}:{i}", word, "") for i, word in enumerate(words)))
        self.selected, self.predicting = 0, True
        self.emit()

    def dismiss(self):
        """Hide suggestions; the next key is handled as if none were shown."""
        if self.predicting:
            self.predicting = False
            self.conversion, self.selected = Conversion("", 0), 0
            self.emit()

    def emit(self):
        if self._holding:
            self._pending = True
            return
        super().emit()

    def select(self, candidate_id, revision=None):
        self._holding, self._pending = True, False
        try:
            return self._select(candidate_id, revision)
        finally:
            self._holding = False
            if self._pending:
                self.emit()

    def _select(self, candidate_id, revision=None):
        if self.predicting:
            chosen = next((c for c in self.conversion.candidates if c.id == candidate_id), None)
            if not self.allowed(revision) or chosen is None:
                return False
            self.predicting = False
            self.conversion, self.selected = Conversion("", 0), 0
            self.commit(chosen.text)
            self.emit()
            self.suggest(chosen.text)
            return True
        self.last_commit = ""
        done = super().select(candidate_id, revision)
        if done and self.last_commit and not self.composition:
            self.suggest(self.last_commit)
        return done

    def predicting_key(self, keyval, state):
        """Keys while suggestions show: digits pick, paging moves, anything else goes on."""
        if state & (SHIFT | SHORTCUT):
            self.dismiss()
            return None
        if ord('1') <= keyval <= ord('9'):
            index = self.selected // self.page_size * self.page_size + keyval - ord('1')
            if keyval - ord('1') < self.page_size and index < len(self.conversion.candidates):
                return self.select(self.conversion.candidates[index].id)
        if keyval in {UP, DOWN, PAGE_UP, PAGE_DOWN}:
            return self.move(1 if keyval in {PAGE_DOWN, DOWN} else -1, keyval in {PAGE_UP, PAGE_DOWN})
        if keyval == ESCAPE:
            self.dismiss()
            return True
        self.dismiss()
        if not (ord('a') <= keyval <= ord('z')):
            self.history = []  # a pause, punctuation or editing key ends the context
        return None

    def set_mode(self, mode, revision=None):
        self.punctuation.reset_pairs()
        return super().set_mode(mode, revision)

    def insert_text(self, text):
        """Insert raw text without numeric selection, using original coordinates."""
        if len(self.composition) + len(text) > 128:
            self.error = 'composition-limit-128'
            self.emit()
            return True
        self.composition = self.composition[:self.cursor] + text + self.composition[self.cursor:]
        self.cursor += len(text)
        self.convert()
        return True

    def ends_pinyin(self, char):
        """A sentence stop at the end of a lowercase pinyin composition.

        A lowercase token can also be an address prefix; KP_Decimal explicitly
        inserts its dot, and English mode/commit_raw remain literal escapes.
        Do not guess intent inside a mixed token or at an editing cursor.
        """
        return (char in SENTENCE_STOPS and bool(self.composition)
                and self.cursor == len(self.composition)
                and all('a' <= c <= 'z' or c == "'" for c in self.composition)
                and any(c.text != self.composition for c in self.conversion.candidates))

    def commit_sentence(self, char):
        # Honour the highlighted candidate, then finish only its unconsumed
        # suffix using each refreshed first candidate. Never replay the prefix.
        while self.composition:
            before = self.composition
            candidates = self.conversion.candidates
            if not candidates or not super().select(candidates[self.selected].id):
                self.commit_raw()
                break
            if self.composition and len(self.composition) >= len(before):
                # Defensive bound for a backend that fails to consume input.
                self.commit_raw()
                break
        self.commit(self.punctuation.map_char(char))
        self.history = []
        return True  # We submitted the symbol, including in ASCII mode.

    def key(self, keyval, keycode, state):
        if state & RELEASE or not self.active or self.blocked:
            return False
        if self.predicting and not self.composition:
            handled = self.predicting_key(keyval, state)
            if handled is not None:
                return handled
        # Reject extra modifiers before resolving UI bindings (Num/Caps Lock
        # remain harmless). All supported bindings are validated by interface.
        if state & (SHORTCUT & ~CONTROL):
            return super().key(keyval, keycode, state)
        # Platform owns exact modifier matching. Consume Binding objects,
        # since the UI convenience resolver also matches unmodified Space.
        action = None
        modifiers = state & (SHIFT | SHORTCUT)
        for name, binding in self.bindings.items():
            if binding.digit_range:
                low, high = binding.digit_range
                if not modifiers and ord(str(low)) <= keyval <= ord(str(high)):
                    action = name
            elif keyval == binding.keyval() and modifiers == binding.modifier_bits():
                action = name
            if action:
                break
        if action == 'toggle_mode':
            return self.set_mode('en' if self.mode == 'zh' else 'zh')
        if state & SHORTCUT or self.mode == 'en':
            return super().key(keyval, keycode, state)
        if action == 'commit_raw' and self.composition:
            self.commit_raw()
            return True
        # Respect the configured Return/KP_Enter choice, including the unbound key.
        if keyval in {0xFF0D, 0xFF8D} and action != 'commit_raw':
            self.reset()
            return False
        if keyval in {LEFT, RIGHT, HOME, END, TAB}:
            self.punctuation.reset_pairs()
        # Keypad digits explicitly insert text even at an ambiguous pinyin
        # boundary; top-row digits continue to select there. No mode toggle.
        if 0xFFB0 <= keyval <= 0xFFB9:
            return self.insert_text(str(keyval - 0xFFB0))
        if keyval == 0xFFAE and self.composition:  # KP_Decimal
            return self.insert_text('.')
        # Sentence stops finish pinyin; other composition symbols keep their
        # literal role in addresses, versions and mixed fragments.
        char = chr(keyval) if 0x21 <= keyval <= 0x7e else ''
        if self.ends_pinyin(char):
            return self.commit_sentence(char)
        if char in ASCII_SAFE and not self.composition:
            mapped = self.punctuation.map_char(char)
            if mapped != char:
                self.commit(mapped)
                return True
            return False
        if char:
            candidates = self.conversion.candidates
            # A list containing only the original text has no conversion to
            # select (e.g. "v" before "v2.0"); retain its following digit.
            raw_only = bool(candidates) and all(c.text == self.composition for c in candidates)
            if (action == 'select_digit' and self.composition
                    and not self.conversion.literal_digits and not raw_only):
                offset = keyval - ord('1')
                index = self.selected // self.page_size * self.page_size + offset
                if offset < self.page_size and index < len(candidates):
                    return self.select(candidates[index].id)
            return self.insert_text(char)
        return super().key(keyval, keycode, state)
