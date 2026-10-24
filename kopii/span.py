"""텍스트 안의 PII 한 조각을 나타내는 Span 데이터 구조."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Span:
    """텍스트 안에서 식별된 PII 한 조각.

    Args:
        start: 시작 오프셋 (포함)
        end: 끝 오프셋 (제외)
        type: PII 타입. kopii.labels.PII_TYPES 중 하나
        surface: 원문에 실제로 나타난 문자열
        entity_key: 같은 사람을 가리키는 span끼리 공유하는 키
    """

    start: int
    end: int
    type: str
    surface: str
    entity_key: str | None = None

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"start는 0 이상이어야 합니다: {self.start}")
        if self.end <= self.start:
            raise ValueError(f"end({self.end})는 start({self.start})보다 커야 합니다.")
        if len(self.surface) != self.end - self.start:
            raise ValueError(
                f"surface 길이({len(self.surface)})가 "
                f"span 폭({self.end - self.start})과 다릅니다."
            )

    def verify(self, text: str) -> bool:
        """이 span이 주어진 텍스트와 정확히 대응하는지 확인합니다.

        Args:
            text: 대조할 원문

        Returns:
            text[start:end]가 surface와 같으면 True
        """
        return text[self.start : self.end] == self.surface
