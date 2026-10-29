"""Platform-owned key, focus, composition and UI state lifecycle; no GI needed."""
from dataclasses import asdict
from .port import Candidate, Conversion, InputContext

SHIFT, CONTROL, ALT = 1, 4, 8
SUPER, HYPER, META, RELEASE = 1 << 26, 1 << 27, 1 << 28, 1 << 30
MOD3, MOD4, MOD5 = 1 << 5, 1 << 6, 1 << 7
SHORTCUT = CONTROL | ALT | MOD3 | MOD4 | MOD5 | SUPER | HYPER | META
BACKSPACE, TAB, RETURN, ESCAPE = 0xFF08, 0xFF09, 0xFF0D, 0xFF1B
HOME, LEFT, UP, RIGHT, DOWN = 0xFF50, 0xFF51, 0xFF52, 0xFF53, 0xFF54
PAGE_UP, PAGE_DOWN, END, DELETE, KP_ENTER = 0xFF55, 0xFF56, 0xFF57, 0xFFFF, 0xFF8D
DIRECT_PURPOSES = {2, 3, 4, 8, 9}  # digits, number, phone, password, PIN
SENSITIVE_PURPOSES = {8, 9}
MAX_COMPOSITION = 256
MAX_CANDIDATES = 200


class Controller:
    def __init__(self, session, context_id, publish, commit, page_size=5):
        if not 1 <= page_size <= 9:
            raise ValueError("page_size must be 1..9")
        self.session, self.context_id = session, context_id
        self.publish, self.commit = publish, commit
        self.page_size = page_size
        self.focused = self.enabled = False
        self.mode = "zh"
        self.context = InputContext()
        self.composition, self.cursor = "", 0
        self.conversion = Conversion("", 0)
        self.selected, self.revision, self.error = 0, 0, ""
        self.closed = False
        self.cursor_rect = None

    @property
    def blocked(self):
        return self.context.private or self.context.purpose in DIRECT_PURPOSES

    @property
    def active(self):
        return self.enabled and self.focused and not self.closed

    def snapshot(self):
        page_start = self.selected // self.page_size * self.page_size
        visible = self.active and not self.blocked and self.mode == "zh"
        return {
            "schema_version": 1, "context_id": self.context_id,
            "revision": self.revision, "focused": self.focused,
            "enabled": self.enabled, "mode": self.mode,
            "purpose": self.context.purpose, "hints": self.context.hints,
            "private": self.context.private, "direct_input": self.blocked,
            "backend": self.session.backend_id,
            "deterministic": self.session.deterministic,
            "error": self.error,
            "cursor_rect": self.cursor_rect,
            "preedit": {"text": self.conversion.preedit if visible else "",
                        "cursor": self.conversion.cursor if visible else 0,
                        "visible": bool(visible and self.composition)},
            "candidates": [dict(asdict(c), index=i)
                           for i, c in enumerate(self.conversion.candidates)] if visible else [],
            "candidate_visible": bool(visible and self.conversion.candidates),
            "literal_digits": bool(visible and self.conversion.literal_digits),
            "selected_index": self.selected, "page_start": page_start,
            "page_size": self.page_size,
            "page_count": (len(self.conversion.candidates) + self.page_size - 1) // self.page_size,
            "status": "测试后端" if self.session.deterministic else "中文输入",
        }

    def emit(self):
        self.revision += 1
        self.publish(self.snapshot())

    def clear(self):
        self.composition, self.cursor = "", 0
        self.conversion, self.selected = Conversion("", 0), 0
        try:
            self.session.reset()
        except Exception:
            self.error = "backend-reset-failed"

    def focus_in(self):
        self.clear()
        self.focused = True
        self.emit()

    def focus_out(self):
        self.focused = False
        self.cursor_rect = None
        self.clear()
        self.emit()

    def set_cursor_location(self, x, y, width, height):
        """IBus absolute screen coordinates; unknown position stays null."""
        rect = {"x": int(x), "y": int(y), "width": max(0, int(width)),
                "height": max(0, int(height)), "coordinate_space": "screen"}
        if rect != self.cursor_rect:
            self.cursor_rect = rect
            self.emit()

    def enable(self):
        self.enabled = True
        self.clear()
        self.emit()

    def disable(self):
        self.enabled = False
        self.clear()
        self.emit()

    def reset(self):
        self.clear()
        self.emit()

    def set_content_type(self, purpose, hints):
        context = InputContext(purpose, hints, purpose in SENSITIVE_PURPOSES)
        if context != self.context:
            self.clear()
        self.context = context
        try:
            self.session.set_context(context)
        except Exception:
            self.error = "backend-context-failed"
            self.clear()
        self.emit()

    def convert(self):
        if not self.composition:
            self.clear()
            self.emit()
            return
        try:
            result = self.session.convert(self.composition, self.cursor)
            if not isinstance(result.preedit, str):
                raise ValueError("invalid conversion")
            if type(result.cursor) is not int or not 0 <= result.cursor <= len(result.preedit) or len(result.candidates) > MAX_CANDIDATES:
                raise ValueError("invalid cursor or candidate count")
            ids = [c.id for c in result.candidates]
            if len(ids) != len(set(ids)) or any(not isinstance(c.id, str) or not c.id
                    or not isinstance(c.text, str) or not c.text or not isinstance(c.annotation, str)
                    for c in result.candidates):
                raise ValueError("invalid candidate ids or text")
            literal_digits = getattr(result, 'literal_digits', False)
            if type(literal_digits) is not bool:
                raise ValueError("invalid digit policy")
            self.conversion = Conversion(result.preedit, result.cursor,
                tuple(Candidate(c.id, c.text, c.annotation) for c in result.candidates), literal_digits)
            self.selected, self.error = 0, ""
        except Exception:
            # Preserve already consumed characters for raw Return/Space commit.
            self.conversion = Conversion(self.composition, self.cursor)
            self.selected, self.error = 0, "backend-convert-failed"
        self.emit()

    def set_mode(self, mode, revision=None):
        if mode not in {"zh", "en"} or not self.allowed(revision):
            return False
        self.mode = mode
        self.clear()
        self.emit()
        return True

    def allowed(self, revision=None):
        return self.active and not self.blocked and (revision is None or revision == self.revision)

    def move(self, delta, page=False, revision=None):
        if not self.allowed(revision) or not self.conversion.candidates:
            return False
        self.selected = max(0, min(len(self.conversion.candidates) - 1,
                                   self.selected + delta * (self.page_size if page else 1)))
        self.emit()
        return True

    def select(self, candidate_id, revision=None):
        if not self.allowed(revision) or candidate_id not in {c.id for c in self.conversion.candidates}:
            return False
        try:
            result = self.session.select(candidate_id)
            if (not isinstance(result.commit, str)
                    or not isinstance(result.remaining, str)
                    or len(result.remaining) > MAX_COMPOSITION
                    or type(result.cursor) is not int or not 0 <= result.cursor <= len(result.remaining)):
                raise ValueError("invalid selection")
        except Exception:
            self.error = "backend-select-failed"
            self.emit()
            return False
        self.composition, self.cursor = result.remaining, result.cursor
        if result.commit:
            self.commit(result.commit)
        self.convert()
        return True

    def commit_raw(self):
        text = self.composition
        self.clear()
        if text:
            self.commit(text)
        self.emit()

    def key(self, keyval, keycode, state):
        # Return False to IBus; do not also call forward_key_event (would duplicate keys).
        if state & RELEASE or not self.active or self.blocked:
            return False
        if keyval == 32 and state & CONTROL and not state & ((SHORTCUT & ~CONTROL) | SHIFT):
            return self.set_mode("en" if self.mode == "zh" else "zh")
        if state & SHORTCUT:
            if self.composition:
                self.reset()
            return False
        if self.mode == "en":
            return False
        if ord('a') <= keyval <= ord('z') or (keyval == ord("'") and self.composition):
            if len(self.composition) < MAX_COMPOSITION:
                self.composition = self.composition[:self.cursor] + chr(keyval) + self.composition[self.cursor:]
                self.cursor += 1
                self.convert()
            return True
        if not self.composition:
            return False
        if keyval == ESCAPE:
            self.reset()
            return True
        if keyval == BACKSPACE:
            if self.cursor:
                self.composition = self.composition[:self.cursor-1] + self.composition[self.cursor:]
                self.cursor -= 1
            self.convert()
            return True
        if keyval == DELETE:
            self.composition = self.composition[:self.cursor] + self.composition[self.cursor+1:]
            self.convert()
            return True
        if keyval in {LEFT, RIGHT, HOME, END}:
            self.cursor = (0 if keyval == HOME else len(self.composition) if keyval == END
                           else max(0, min(len(self.composition), self.cursor + (1 if keyval == RIGHT else -1))))
            self.convert()
            return True
        if keyval in {PAGE_UP, PAGE_DOWN, UP, DOWN}:
            self.move(1 if keyval in {PAGE_DOWN, DOWN} else -1, keyval in {PAGE_UP, PAGE_DOWN})
            return True
        if keyval == 32:
            if self.conversion.candidates:
                self.select(self.conversion.candidates[self.selected].id)
            else:
                self.commit_raw()
            return True
        if ord('1') <= keyval <= ord('9'):
            offset = keyval - ord('1')
            index = self.selected // self.page_size * self.page_size + offset
            if offset < self.page_size and index < len(self.conversion.candidates):
                self.select(self.conversion.candidates[index].id)
                return True
        if keyval in {RETURN, KP_ENTER}:
            self.commit_raw()
            return True
        # Unhandled printable keys and navigation leave no hidden composition.
        # Commit raw text before punctuation; Tab cancels so it can change focus.
        if 0x20 <= keyval <= 0x7E:
            self.commit_raw()
        elif keyval == TAB:
            self.reset()
        return False

    def close(self):
        self.focus_out()
        self.closed = True
        try:
            self.session.close()
        except Exception:
            self.error = "backend-close-failed"
