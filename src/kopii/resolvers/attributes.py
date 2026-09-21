"""Configurable tabular lookup, with no built-in organization names or hierarchy."""

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path

from kopii.resolvers import Resolution


class AttributeResolver:
    """Resolve a key to one value only when all configured discriminator fields agree."""

    def __init__(
        self,
        rows: Sequence[Mapping[str, str]],
        *,
        key: str,
        value: str,
        ambiguity_fields: Sequence[str] = (),
    ) -> None:
        if isinstance(ambiguity_fields, str):
            raise ValueError("ambiguity_fields must be a sequence of column names")
        required = {key, value, *ambiguity_fields}
        if any(not isinstance(name, str) or not name for name in required):
            raise ValueError("Column names must be nonempty strings")
        self.value, self.ambiguity_fields = value, tuple(ambiguity_fields)
        self.rows: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            if not required <= set(row) or any(not isinstance(row[k], str) for k in required):
                raise ValueError("Missing or invalid attribute columns")
            clean = {k: row[k].strip() for k in required}
            if not clean[key]:
                raise ValueError("Lookup keys must be nonempty")
            self.rows.setdefault(clean[key], []).append(clean)

    @classmethod
    def from_csv(
        cls,
        path: Path,
        *,
        key: str,
        value: str,
        ambiguity_fields: Sequence[str] = (),
    ) -> "AttributeResolver":
        """CSV adapter for the same contract; database adapters implement Resolver directly."""
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {key, value, *ambiguity_fields} <= set(reader.fieldnames or []):
                raise ValueError("Missing CSV columns")
            rows = list(reader)
        if any(None in row or any(v is None for v in row.values()) for row in rows):
            raise ValueError("Malformed CSV rows")
        return cls(rows, key=key, value=value, ambiguity_fields=ambiguity_fields)

    def resolve(self, names: list[str]) -> dict[str, Resolution]:
        result = {}
        for name in set(names):
            rows = self.rows.get(name, [])
            fields = (self.value, *self.ambiguity_fields)
            if not rows or any(not row[field] for row in rows for field in fields):
                result[name] = Resolution("missing")
            elif any(len({row[field] for row in rows}) != 1 for field in fields):
                result[name] = Resolution("ambiguous")
            else:
                result[name] = Resolution("resolved", rows[0][self.value])
        return result
