"""Synthetic CSV directory example with conservative organization ambiguity."""

import csv
from pathlib import Path

from kopii.resolvers import Resolution


class CsvResolver:
    """Read name/team/division/center; disambiguate at team before generalizing.

    Ambiguous teams stay ambiguous even when they share a parent organization.
    Multiple people with the same name and team cannot be distinguished here.
    """

    def __init__(self, path: Path, level: str = "team") -> None:
        if level not in {"team", "division", "center"}:
            raise ValueError("Organization level must be team, division, or center")
        self._rows: dict[str, list[dict[str, str]]] = {}
        self.level = level
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {"name", "team", level} <= set(reader.fieldnames or []):
                raise ValueError("Directory must include name, team, and selected level")
            for row in reader:
                if any(value is None for value in row.values()) or None in row:
                    raise ValueError("Malformed directory row")
                clean = {key: value.strip() for key, value in row.items()}
                if not clean["name"]:
                    raise ValueError("Directory names must be nonempty")
                self._rows.setdefault(clean["name"], []).append(clean)

    def resolve(self, names: list[str]) -> dict[str, Resolution]:
        """Map an unambiguous team to the requested explicit hierarchy column."""
        result: dict[str, Resolution] = {}
        for name in set(names):
            rows = self._rows.get(name, [])
            teams = {row["team"] for row in rows}
            values = {row[self.level] for row in rows}
            if not rows or "" in teams or "" in values:
                result[name] = Resolution("missing")
            elif len(teams) != 1 or len(values) != 1:
                result[name] = Resolution("ambiguous")
            else:
                result[name] = Resolution("resolved", next(iter(values)))
        return result
