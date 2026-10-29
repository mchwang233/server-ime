"""Framework-independent, synchronous conversion port (version 1).

An engine factory creates one session per IBus engine instance. This interface
intentionally contains no IBus/Gtk objects and no persistence policy.
"""
from dataclasses import dataclass
from typing import Protocol, Tuple


@dataclass(frozen=True)
class InputContext:
    purpose: int = 0
    hints: int = 0
    private: bool = False


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


class EngineSession(Protocol):
    backend_id: str
    deterministic: bool

    def set_context(self, context: InputContext) -> None:
        """Receive input purpose and hint bits, including unknown future bits."""

    def convert(self, composition: str, cursor: int) -> Conversion:
        """Return display preedit and an ordered, stable-ID candidate list."""

    def select(self, candidate_id: str) -> Selection:
        """Select a candidate from the most recent conversion; allow partial commits."""

    def reset(self) -> None:
        """Discard composition and transient candidates, without committing."""

    def close(self) -> None:
        """Release session resources."""
