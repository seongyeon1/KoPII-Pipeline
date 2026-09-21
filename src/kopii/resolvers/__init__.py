"""Replaceable external-context resolvers; no production HR database dependency."""

from dataclasses import dataclass
from typing import Literal, Optional, Protocol


@dataclass(frozen=True)
class Resolution:
    """An organization resolution, not a unique-person identity match."""

    status: Literal["resolved", "missing", "ambiguous", "unavailable"]
    value: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in {"resolved", "missing", "ambiguous", "unavailable"}:
            raise ValueError("Unknown resolution status")
        if (self.status == "resolved") != bool(self.value):
            raise ValueError("Only resolved results may contain a nonempty value")


class Resolver(Protocol):
    """Bulk context lookup; implementations should report unresolved names."""

    def resolve(self, names: list[str]) -> dict[str, Resolution]:
        """Resolve names without guessing across different organizations."""
        ...
