"""Masking, document-scoped pseudonyms, and organization-level replacement."""

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Optional

from kopii.resolvers import Resolution
from kopii.schemas import Entity


@dataclass(frozen=True)
class Policy:
    """Configure actions per label, defaulting to masking every detected type.

    Pseudonyms are keyed and document-scoped; they are not encryption, person
    disambiguation, or a mathematical anonymity guarantee.
    """

    actions: dict[str, str] = field(default_factory=dict)
    default_action: str = "mask"
    key: Optional[bytes] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        valid = {"mask", "pseudonym", "organization"}
        if self.default_action not in valid or any(v not in valid for v in self.actions.values()):
            raise ValueError("Policy actions: mask, pseudonym, organization")
        if self.key is not None and len(self.key) < 16:
            raise ValueError("Pseudonym keys require at least 16 bytes")

    def action_for(self, label: str) -> str:
        """Choose a configured action for a detected type."""
        return self.actions.get(label, self.default_action)

    def replacement(
        self,
        entity: Entity,
        surface: str,
        document_id: str,
        resolution: Resolution,
    ) -> tuple[str, str]:
        """Return a replacement and actual action, falling back without raw PII."""
        action = self.action_for(entity.label)
        if action == "organization" and entity.label == "PERSON_NAME":
            value = resolution.value
            if resolution.status == "resolved" and value and self._safe_category(value):
                return f"[{entity.label}:{value}]", "organization"
            action = "pseudonym"
        elif action == "organization":
            action = "mask"
        if action == "pseudonym" and self.key and document_id:
            payload = json.dumps([document_id, entity.label, surface], ensure_ascii=False).encode()
            token = hmac.new(self.key, payload, hashlib.sha256).hexdigest()[:24]
            return f"[{entity.label}:{token}]", "pseudonym"
        return f"[{entity.label}]", "mask"

    @staticmethod
    def _safe_category(value: str) -> bool:
        return len(value) <= 80 and not any(c in "[]:" or not c.isprintable() for c in value)
