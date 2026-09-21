"""Validated, half-open Unicode character offsets shared by all adapters."""

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Entity:
    """A typed span; offsets index the unnormalized Python input string."""

    start: int
    end: int
    label: str
    score: float = 1.0
    source: str = "custom"

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.end) is not int:
            raise ValueError("Offsets must be integers")
        if not 0 <= self.start < self.end:
            raise ValueError("Expected a nonempty half-open span")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", self.label):
            raise ValueError("Labels must be uppercase identifiers")
        if (
            isinstance(self.score, bool)
            or not math.isfinite(self.score)
            or not 0 <= self.score <= 1
        ):
            raise ValueError("Score must be finite and within [0, 1]")

    def validate_text(self, text: str) -> None:
        """Reject adapter output outside the input instead of silently clipping."""
        if self.end > len(text):
            raise ValueError("Entity extends beyond the input")

    def to_dict(self) -> dict[str, Any]:
        """Serialize positions and metadata without copying the original surface."""
        return asdict(self)


class Detector(Protocol):
    """Adapter contract; failures must raise, never become empty predictions."""

    def detect(self, text: str) -> list[Entity]:
        """Return entities positioned in the original text."""
        ...


@dataclass(frozen=True)
class Replacement:
    """Replacement ranges in both the input and output coordinate systems."""

    start: int
    end: int
    output_start: int
    output_end: int
    label: str
    action: str


@dataclass(frozen=True)
class ProcessingResult:
    """A successfully processed document, not a certificate of anonymity."""

    text: str
    entities: list[Entity]
    replacements: list[Replacement]
    events: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible metadata without the original input document."""
        return asdict(self)
