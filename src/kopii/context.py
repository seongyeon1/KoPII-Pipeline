"""Build released text and private context without parsing replacement markers."""

from collections.abc import Mapping
from dataclasses import dataclass

from kopii.rendering import merge_entities, render
from kopii.resolvers import Resolution, Resolver
from kopii.retrieval import SearchDocument
from kopii.schemas import Detector, Entity


@dataclass(frozen=True)
class ContextField:
    """Map a detected entity type to an application-selected categorical field."""

    resolver: Resolver
    entity_label: str = "PERSON_NAME"

    def __post_init__(self) -> None:
        Entity(0, 1, self.entity_label)


@dataclass(frozen=True)
class PreparedDocument:
    """A masked document and aggregate resolution diagnostics, without raw surfaces."""

    document: SearchDocument
    resolution_counts: Mapping[str, Mapping[str, int]]


class ContextPipeline:
    """Mask all detected spans and resolve chosen attributes into a private index.

    Multiple mentioned entities contribute a union per field; this is document
    metadata, not person-level linking or a guarantee that all PII was detected.
    """

    def __init__(self, detector: Detector, fields: Mapping[str, ContextField]) -> None:
        if any(not isinstance(key, str) or not key for key in fields):
            raise ValueError("Context field names must be nonempty strings")
        self.detector, self.fields = detector, dict(fields)

    def process(self, text: str, document_id: str) -> PreparedDocument:
        """Detect once; unresolved attributes stay absent and errors never reveal values."""
        entities = merge_entities(text, self.detector.detect(text))
        output, _ = render(text, entities, lambda e, surface: (f"[{e.label}]", "mask"))
        metadata: dict[str, frozenset[str]] = {}
        diagnostics: dict[str, dict[str, int]] = {}
        for field, spec in self.fields.items():
            surfaces = sorted(
                {text[e.start : e.end] for e in entities if e.label == spec.entity_label}
            )
            try:
                resolved = spec.resolver.resolve(surfaces) if surfaces else {}
                if not isinstance(resolved, dict) or any(
                    not isinstance(value, Resolution) for value in resolved.values()
                ):
                    raise ValueError("Invalid resolver output")
            except Exception:
                resolved = {surface: Resolution("unavailable") for surface in surfaces}
            counts: dict[str, int] = {}
            values = set()
            for surface in surfaces:
                resolution = resolved.get(surface, Resolution("missing"))
                counts[resolution.status] = counts.get(resolution.status, 0) + 1
                if resolution.status == "resolved" and resolution.value:
                    values.add(resolution.value)
            diagnostics[field] = counts
            if values:
                metadata[field] = frozenset(values)
        return PreparedDocument(SearchDocument(document_id, output, metadata), diagnostics)
