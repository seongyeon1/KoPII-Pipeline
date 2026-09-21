"""Optional GLiNER adapters; explicit label prompts and window settings."""

from typing import Any

from kopii.schemas import Entity


def character_windows(text: str, size: int, overlap: int) -> list[tuple[int, str]]:
    """Return overlapping character windows without consulting gold spans."""
    if size < 1 or not 0 <= overlap < size:
        raise ValueError("Require 0 <= overlap < window size")
    result = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        result.append((start, text[start:end]))
        if end == len(text):
            break
        start = end - overlap
    return result


class GlinerDetector:
    """Wrap GLiNER or GLiNER2; versioned checkpoints, configurable type prompts."""

    def __init__(
        self,
        model: str,
        revision: str,
        labels: dict[str, str],
        version: int = 1,
        threshold: float = 0.5,
        device: str = "cpu",
        window_chars: int = 180,
        overlap_chars: int = 48,
        batch_size: int = 4,
        local_files_only: bool = False,
    ) -> None:
        if not revision or not labels or version not in {1, 2}:
            raise ValueError("Require revision, label prompts, and GLiNER version 1 or 2")
        if not 0 <= threshold <= 1 or batch_size < 1:
            raise ValueError("Invalid threshold or batch size")
        character_windows("", window_chars, overlap_chars)
        for label in labels.values():
            Entity(0, 1, label)
        from huggingface_hub import snapshot_download

        path = snapshot_download(model, revision=revision, local_files_only=local_files_only)
        if version == 1:
            from gliner import GLiNER

            self.model: Any = GLiNER.from_pretrained(path).eval().to(device)
        else:
            from gliner2 import GLiNER2

            self.model = GLiNER2.from_pretrained(path).eval().to(device)
        self.version, self.labels, self.threshold = version, labels, threshold
        self.window_chars, self.overlap_chars, self.batch_size = (
            window_chars,
            overlap_chars,
            batch_size,
        )

    def detect(self, text: str) -> list[Entity]:
        """Restore offsets and deduplicate identical spans; retain conflicting predictions.

        Runtime union masking belongs to Pipeline. Applying it here would turn
        conflicting predictions into an out-of-schema label during evaluation.
        """
        import torch

        windows = character_windows(text, self.window_chars, self.overlap_chars)
        entities = []
        with torch.inference_mode():
            for begin in range(0, len(windows), self.batch_size):
                group = windows[begin : begin + self.batch_size]
                texts = [part for _, part in group]
                if self.version == 1:
                    predictions = self.model.inference(
                        texts,
                        list(self.labels),
                        threshold=self.threshold,
                        batch_size=len(group),
                    )
                else:
                    raw = self.model.batch_extract_entities(
                        texts,
                        list(self.labels),
                        threshold=self.threshold,
                        batch_size=len(group),
                        include_spans=True,
                        include_confidence=True,
                    )
                    predictions = [
                        [
                            dict(e, label=label, score=e["confidence"])
                            for label, values in row["entities"].items()
                            for e in values
                        ]
                        for row in raw
                    ]
                if len(predictions) != len(group):
                    raise ValueError("Model returned the wrong number of windows")
                for (offset, part), row in zip(group, predictions, strict=True):
                    for item in row:
                        span = Entity(
                            item["start"],
                            item["end"],
                            self.labels[item["label"]],
                            float(item["score"]),
                            f"gliner{self.version}",
                        )
                        span.validate_text(part)
                        entities.append(
                            Entity(
                                offset + span.start,
                                offset + span.end,
                                span.label,
                                span.score,
                                span.source,
                            )
                        )
        unique: dict[tuple[int, int, str], Entity] = {}
        for entity in entities:
            key = entity.start, entity.end, entity.label
            if key not in unique or entity.score > unique[key].score:
                unique[key] = entity
        return [unique[key] for key in sorted(unique)]
