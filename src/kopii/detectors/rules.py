"""Small explicit baseline, not a complete Korean PII rule catalog."""

import re

from kopii.schemas import Entity


class RuleDetector:
    """Detect common email and Korean mobile-number formats without identity checks."""

    patterns = {
        "EMAIL": re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
        "PHONE_NUM": re.compile(r"(?<!\d)01[016789][ .-]?\d{3,4}[ .-]?\d{4}(?!\d)"),
    }

    def detect(self, text: str) -> list[Entity]:
        """Return format matches; callers may add domain-specific validators."""
        return [
            Entity(match.start(), match.end(), label, source="rules")
            for label, pattern in self.patterns.items()
            for match in pattern.finditer(text)
        ]


class DictionaryDetector:
    """Exact-name fixture detector for demos; never an NER evaluation baseline."""

    def __init__(self, names: list[str]) -> None:
        if not names or any(not name or name != name.strip() for name in names):
            raise ValueError("Provide nonempty trimmed dictionary names")
        alternatives = "|".join(
            re.escape(name) for name in sorted(set(names), key=len, reverse=True)
        )
        self.pattern = re.compile(
            rf"(?<!\w)(?:{alternatives})(?=$|[^\w]|(?:에게|께서|으로|은|는|이|가|을|를|의|와|과|도)(?=$|[^\w]))"
        )

    def detect(self, text: str) -> list[Entity]:
        """Find configured fixture names, allowing listed Korean particles."""
        return [
            Entity(m.start(), m.end(), "PERSON_NAME", source="dictionary")
            for m in self.pattern.finditer(text)
        ]
