"""BIO token-classification adapter with overlapping token windows."""

from typing import Any, Optional

from kopii.schemas import Entity


def decode_bio(text: str, tokens: list[tuple[int, int, str, float]]) -> list[Entity]:
    """Join I-tags across same-line whitespace; reject unknown label encodings."""
    result: list[Entity] = []
    active: Optional[Entity] = None
    for start, end, tag, score in sorted(tokens):
        if tag == "O":
            if active:
                result.append(active)
                active = None
            continue
        if not tag.startswith(("B-", "I-")):
            raise ValueError("Model must expose O/B-/I- labels")
        prefix, label = tag.split("-", 1)
        gap = text[active.end : start] if active else ""
        if (
            prefix == "I"
            and active
            and active.label == label
            and active.end <= start
            and not gap.strip()
            and "\n" not in gap
            and "\r" not in gap
        ):
            active = Entity(active.start, end, label, min(active.score, score), "huggingface")
        else:
            if active:
                result.append(active)
            active = Entity(start, end, label, score, "huggingface")
    if active:
        result.append(active)
    for entity in result:
        entity.validate_text(text)
    return result


class HuggingFaceDetector:
    """Load a versioned fast tokenizer and a token classifier on an explicit device."""

    def __init__(
        self,
        model: str,
        revision: str,
        device: str = "cpu",
        max_length: int = 256,
        stride: int = 32,
        batch_size: int = 4,
        local_files_only: bool = False,
    ) -> None:
        if not revision:
            raise ValueError("An explicit model revision is required")
        if max_length < 8 or not 0 <= stride < max_length - 2 or batch_size < 1:
            raise ValueError("Invalid token window or batch size")
        try:
            import torch
            from transformers import AutoModelForTokenClassification, AutoTokenizer
        except ImportError as exc:
            raise ImportError("Install kopii-pipeline[hf] for neural detection") from exc
        self._torch: Any = torch
        self.model: Any = (
            AutoModelForTokenClassification.from_pretrained(
                model,
                revision=revision,
                local_files_only=local_files_only,
            )
            .eval()
            .to(device)
        )
        self.tokenizer: Any = AutoTokenizer.from_pretrained(
            model,
            revision=revision,
            use_fast=True,
            local_files_only=local_files_only,
        )
        if not self.tokenizer.is_fast:
            raise ValueError("Character offsets require a fast tokenizer")
        self.tags = {int(key): value for key, value in self.model.config.id2label.items()}
        for tag in self.tags.values():
            if tag != "O":
                if not tag.startswith(("B-", "I-")):
                    raise ValueError("Checkpoint must expose BIO labels, not numeric LABEL_n")
                Entity(0, 1, tag[2:])
        self.device, self.max_length, self.stride = device, max_length, stride
        self.batch_size = batch_size

    def detect(self, text: str) -> list[Entity]:
        """Infer every token window and choose the most contextual copy of each token."""
        if not text:
            return []
        encoded = self.tokenizer(
            text,
            max_length=self.max_length,
            stride=self.stride,
            truncation=True,
            return_overflowing_tokens=True,
            return_offsets_mapping=True,
            return_special_tokens_mask=True,
            padding=True,
            return_tensors="pt",
        )
        offsets = encoded["offset_mapping"].tolist()
        specials = encoded["special_tokens_mask"].tolist()
        selected: dict[tuple[int, int], tuple[int, str, float]] = {}
        with self._torch.inference_mode():
            for begin in range(0, len(offsets), self.batch_size):
                inputs = {
                    key: encoded[key][begin : begin + self.batch_size].to(self.device)
                    for key in self.tokenizer.model_input_names
                    if key in encoded
                }
                probabilities = self.model(**inputs).logits.softmax(-1)
                scores, labels = probabilities.max(-1)
                batch_scores, batch_labels = scores.cpu().tolist(), labels.cpu().tolist()
                for local, (scores_row, label_row) in enumerate(
                    zip(batch_scores, batch_labels, strict=True)
                ):
                    row = begin + local
                    valid = [
                        i
                        for i, ((a, b), special) in enumerate(
                            zip(offsets[row], specials[row], strict=True)
                        )
                        if not special and a < b
                    ]
                    for rank, i in enumerate(valid):
                        a, b = offsets[row][i]
                        context = min(rank, len(valid) - rank - 1)
                        if (a, b) not in selected or context > selected[a, b][0]:
                            selected[a, b] = (context, self.tags[label_row[i]], scores_row[i])
        return decode_bio(
            text, [(a, b, tag, score) for (a, b), (_, tag, score) in selected.items()]
        )
