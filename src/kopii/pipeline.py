"""Compose detectors, an optional context resolver, and replacement policies."""

from typing import Optional

from kopii.policies import Policy
from kopii.rendering import merge_entities, render
from kopii.resolvers import Resolution, Resolver
from kopii.schemas import Detector, Entity, ProcessingResult


class Pipeline:
    """Process text; detection failures propagate before any result is returned."""

    def __init__(
        self,
        detector: Detector,
        policy: Optional[Policy] = None,
        resolver: Optional[Resolver] = None,
    ) -> None:
        self.detector = detector
        self.policy = policy or Policy()
        self.resolver = resolver

    def process(self, text: str, document_id: str = "") -> ProcessingResult:
        """Detect, resolve context when requested, then replace the full union."""
        entities = merge_entities(text, self.detector.detect(text))
        names = sorted(
            {
                text[e.start : e.end]
                for e in entities
                if e.label == "PERSON_NAME" and self.policy.action_for(e.label) == "organization"
            }
        )
        resolutions: dict[str, Resolution] = {}
        events: list[str] = []
        if names and self.resolver:
            try:
                resolutions = self.resolver.resolve(names)
                if any(not isinstance(value, Resolution) for value in resolutions.values()):
                    raise ValueError("Invalid resolver result")
            except Exception:
                # Never log exception messages: a provider could embed raw names.
                resolutions = {name: Resolution("unavailable") for name in names}
                events.append("resolver_unavailable")

        def replace(entity: Entity, surface: str) -> tuple[str, str]:
            resolution = resolutions.get(surface, Resolution("missing"))
            return self.policy.replacement(entity, surface, document_id, resolution)

        output, replacements = render(text, entities, replace)
        return ProcessingResult(output, entities, replacements, events)
