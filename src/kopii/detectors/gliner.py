"""Optional GLiNER adapters; explicit label prompts and window settings."""

import re
from typing import Any, Iterator, Optional

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


def gliner2_input(text: str) -> str:
    """Make GLiNER2 2.0.0's implicit terminal punctuation explicit."""
    return text if text.endswith((".", "!", "?")) else text + "."


def restore_gliner2_span(text: str, item: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Invert only the known synthetic suffix; reject any other offset mismatch."""
    model_text = gliner2_input(text)
    start, end = item["start"], item["end"]
    if not 0 <= start < end <= len(model_text):
        raise ValueError("GLiNER2 span extends beyond the augmented input")
    if model_text[start:end].strip() != item["text"]:
        raise ValueError("GLiNER2 span surface disagrees with the augmented input")
    if start >= len(text):
        return None  # Prediction contains only model-added punctuation, no input character.
    return dict(item, end=min(end, len(text)))


class KoreanSyllableSplitter:
    """Split Hangul syllables inside native tokens; preserve original offsets.

    This is a boundary ablation, not a morphological analyzer. Non-Hangul
    portions retain native boundaries, including each backend's email handling.
    """

    def __init__(self, native: Any) -> None:
        self.native = native

    def __call__(self, text: str, lower: bool = False) -> Iterator[tuple[str, int, int]]:
        for _, start, end in self.native(text):
            for part in re.finditer(r"[가-힣]|[^가-힣]+", text[start:end]):
                value = part.group()
                yield value.lower() if lower else value, start + part.start(), start + part.end()


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
        boundary: str = "native",
    ) -> None:
        if boundary not in {"native", "ko_syllable"}:
            raise ValueError("Boundary must be native or ko_syllable")
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
        self._native_splitter = (
            self.model.data_processor.words_splitter
            if version == 1
            else self.model.processor.word_splitter
        )
        self.set_boundary(boundary)
        self.window_chars, self.overlap_chars, self.batch_size = (
            window_chars,
            overlap_chars,
            batch_size,
        )

    def set_boundary(self, boundary: str) -> None:
        """Select original or Hangul-syllable boundaries without changing weights."""
        if boundary not in {"native", "ko_syllable"}:
            raise ValueError("Boundary must be native or ko_syllable")
        splitter = self._native_splitter
        if boundary == "ko_syllable":
            splitter = KoreanSyllableSplitter(splitter)
        if self.version == 1:
            self.model.data_processor.words_splitter = splitter
        else:
            self.model.processor.word_splitter = splitter
        self.boundary = boundary

    def detect(self, text: str) -> list[Entity]:
        """Detect in one document with original Unicode offsets."""
        return self.detect_many([text])[0]

    def detect_many(self, texts: list[str]) -> list[list[Entity]]:
        """Batch windows across documents without merging their coordinate systems."""
        import torch

        windows = [
            (index, offset, part)
            for index, text in enumerate(texts)
            for offset, part in character_windows(text, self.window_chars, self.overlap_chars)
        ]
        unique: list[dict[tuple[int, int, str], Entity]] = [{} for _ in texts]
        with torch.inference_mode():
            for begin in range(0, len(windows), self.batch_size):
                group = windows[begin : begin + self.batch_size]
                parts = [part for _, _, part in group]
                if self.version == 1:
                    predictions = self.model.inference(
                        parts, list(self.labels), threshold=self.threshold, batch_size=len(group)
                    )
                else:
                    raw = self.model.batch_extract_entities(
                        [gliner2_input(part) for part in parts],
                        list(self.labels),
                        threshold=self.threshold,
                        batch_size=len(group),
                        include_spans=True,
                        include_confidence=True,
                    )
                    if len(raw) != len(parts):
                        raise ValueError("Model returned the wrong number of windows")
                    predictions = []
                    for part, row in zip(parts, raw, strict=True):
                        restored = []
                        for label, values in row["entities"].items():
                            for item in values:
                                mapped = restore_gliner2_span(part, item)
                                if mapped is not None:
                                    restored.append(
                                        dict(mapped, label=label, score=item["confidence"])
                                    )
                        predictions.append(restored)
                if len(predictions) != len(group):
                    raise ValueError("Model returned the wrong number of windows")
                for (index, offset, part), row in zip(group, predictions, strict=True):
                    for item in row:
                        span = Entity(
                            item["start"],
                            item["end"],
                            self.labels[item["label"]],
                            float(item["score"]),
                            f"gliner{self.version}",
                        )
                        span.validate_text(part)
                        entity = Entity(
                            offset + span.start,
                            offset + span.end,
                            span.label,
                            span.score,
                            span.source,
                        )
                        key = entity.start, entity.end, entity.label
                        if key not in unique[index] or entity.score > unique[index][key].score:
                            unique[index][key] = entity
        return [[values[key] for key in sorted(values)] for values in unique]
