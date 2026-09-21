"""Detection adapters; neural dependencies are imported only when requested."""

from kopii.schemas import Detector, Entity


class CombinedDetector:
    """Combine predictions without swallowing detector errors."""

    def __init__(self, detectors: list[Detector]) -> None:
        if not detectors:
            raise ValueError("At least one detector is required")
        self.detectors = detectors

    def detect(self, text: str) -> list[Entity]:
        """Keep original predictions; the pipeline applies overlap policy."""
        entities = []
        for detector in self.detectors:
            for entity in detector.detect(text):
                entity.validate_text(text)
                entities.append(entity)
        return entities
