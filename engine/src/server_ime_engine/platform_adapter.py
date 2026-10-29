"""Structural implementation of platform/server_ime/port.py version 1.

This module has no IBus/Gtk dependency. Platform owns key/focus handling.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from dataclasses import dataclass
from typing import Tuple

from .core import Engine

# platform/server_ime/controller.py v1 accepts at most 200 candidates.
PLATFORM_CANDIDATE_LIMIT = 200


@dataclass(frozen=True)
class Candidate:
    id: str
    text: str
    annotation: str = ""


@dataclass(frozen=True)
class Conversion:
    preedit: str
    cursor: int
    candidates: Tuple[Candidate, ...] = ()
    literal_digits: bool = False


@dataclass(frozen=True)
class Selection:
    commit: str
    remaining: str = ""
    cursor: int = 0


class PlatformSession:
    backend_id = "libpinyin-2.6.0-api1"
    deterministic = False

    def __init__(self, config=None, **engine_options):
        self._engine = Engine(**engine_options)
        try:
            self._session = self._engine.create_session(config=config)
        except Exception:
            self._engine.close()
            raise
        self.context = None

    def set_context(self, context):
        self._session.set_context(private=getattr(context, "private", False),
                                  purpose=getattr(context, "purpose", 0),
                                  hints=getattr(context, "hints", 0))
        self.context = context

    def configure(self, patch):
        return self._session.configure(patch)

    def capabilities(self):
        return self._engine.capabilities()

    def convert(self, composition, cursor):
        state = self._session.set_composition(composition, cursor)
        # The engine's annotations name its internal candidate kinds (整句, 分段, 原文);
        # the candidate window shows only the text, like the Windows 11 IME.
        candidates = [Candidate(item["id"], item["text"], "")
                      for item in self._session.candidate_list(PLATFORM_CANDIDATE_LIMIT)]
        return Conversion(state["preedit"]["text"], state["preedit"]["cursor"], tuple(candidates),
                          state['composition']['literal_digits'])

    def select(self, candidate_id):
        state = self._session.select(candidate_id)
        if state["commits"]:
            return Selection(state["commits"][0]["text"])
        # The platform port accepts partial application commits; the core API keeps
        # these selections in preedit. Convert explicitly between the two policies.
        selected = self._session.selected
        remaining = self._session.raw[self._session.offset:]
        # The port has accepted this prefix for application submission. Record
        # precisely that prefix, once, via the same privacy and learning gates.
        self._session._finish_selected_for_platform(candidate_id)
        return Selection(selected, remaining, 0)

    def predict(self, history, limit=10):
        """Words to offer after the committed texts (most recent last)."""
        if self._session._private:
            return []
        return self._engine.predict(list(history), limit)

    def reset(self):
        self._session.reset()

    def close(self):
        self._engine.close()


def create_session(config=None, **engine_options):
    return PlatformSession(config=config, **engine_options)
