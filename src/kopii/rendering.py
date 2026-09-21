"""Conservative overlap handling and offset-preserving replacement."""

from typing import Callable

from kopii.schemas import Entity, Replacement


def merge_entities(text: str, entities: list[Entity]) -> list[Entity]:
    """Cover the union of overlaps; conflicting labels fall back to generic PII.

    No detected characters are discarded to prefer another detector. Adjacent
    spans remain separate. This intentionally differs from the legacy benchmark.
    """
    for entity in entities:
        entity.validate_text(text)
    merged: list[Entity] = []
    for entity in sorted(entities, key=lambda item: (item.start, item.end, item.label)):
        if merged and entity.start < merged[-1].end:
            previous = merged.pop()
            merged.append(
                Entity(
                    previous.start,
                    max(previous.end, entity.end),
                    previous.label if previous.label == entity.label else "PII",
                    min(previous.score, entity.score),
                    "+".join(
                        sorted(set(previous.source.split("+")) | set(entity.source.split("+")))
                    ),
                )
            )
        else:
            merged.append(entity)
    return merged


def render(
    text: str,
    entities: list[Entity],
    replace: Callable[[Entity, str], tuple[str, str]],
) -> tuple[str, list[Replacement]]:
    """Replace sorted disjoint spans while recording both coordinate systems."""
    parts: list[str] = []
    records: list[Replacement] = []
    cursor = output_cursor = 0
    for entity in entities:
        entity.validate_text(text)
        if entity.start < cursor:
            raise ValueError("Rendering requires disjoint, sorted entities")
        prefix = text[cursor : entity.start]
        replacement, action = replace(entity, text[entity.start : entity.end])
        parts.extend([prefix, replacement])
        output_cursor += len(prefix)
        records.append(
            Replacement(
                entity.start,
                entity.end,
                output_cursor,
                output_cursor + len(replacement),
                entity.label,
                action,
            )
        )
        output_cursor += len(replacement)
        cursor = entity.end
    parts.append(text[cursor:])
    return "".join(parts), records
