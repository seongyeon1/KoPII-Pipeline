"""합성 코퍼스 생성 설정 Pydantic 스키마."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class PopulationConfig(BaseModel):
    """가상 조직·구성원 생성 설정."""

    size: int = Field(default=2000, ge=1, description="구성원 수")
    seed: int = Field(default=42, description="난수 시드")
    id_scheme: Literal["sequential_block", "org_coded"] = Field(
        default="sequential_block", description="사번 채번 스킴"
    )
    divisions: int = Field(default=5, ge=1, description="본부 수")
    teams_per_division: tuple[int, int] = Field(
        default=(3, 8), description="본부당 팀 수 범위"
    )
    nickname_ratio: float = Field(
        default=0.5, ge=0.0, le=1.0, description="닉네임 보유 비율"
    )

    @model_validator(mode="after")
    def _check_team_range(self) -> PopulationConfig:
        low, high = self.teams_per_division
        if low < 1 or high < low:
            raise ValueError(
                f"teams_per_division 범위가 잘못됐습니다: {self.teams_per_division}"
            )
        return self


class PerturbConfig(BaseModel):
    """표기 흔들림 확률 설정."""

    honorific_variation: float = Field(default=0.3, ge=0.0, le=1.0)
    partial_name: float = Field(default=0.2, ge=0.0, le=1.0)
    separator_variation: float = Field(default=0.3, ge=0.0, le=1.0)
    line_break_split: float = Field(default=0.05, ge=0.0, le=1.0)
    typo: float = Field(default=0.02, ge=0.0, le=1.0)
    space_insertion: float = Field(default=0.10, ge=0.0, le=1.0)


class CorpusConfig(BaseModel):
    """문서 코퍼스 생성 설정."""

    size: int = Field(default=20000, ge=1, description="문서 수")
    seed: int = Field(default=42, description="난수 시드")
    genres: dict[str, float] = Field(
        default_factory=lambda: {
            "meeting_note": 0.25,
            "email": 0.25,
            "hr_notice": 0.15,
            "approval_doc": 0.15,
            "chat_log": 0.10,
            "issue_ticket": 0.10,
        },
        description="장르별 가중치",
    )
    perturb: PerturbConfig = Field(default_factory=PerturbConfig)

    @model_validator(mode="after")
    def _check_genre_weights(self) -> CorpusConfig:
        if sum(self.genres.values()) <= 0.0:
            raise ValueError("장르 가중치 합이 0보다 커야 합니다.")
        if any(weight < 0.0 for weight in self.genres.values()):
            raise ValueError("장르 가중치는 음수일 수 없습니다.")
        return self


class SynthConfig(BaseModel):
    """합성 코퍼스 생성 전체 설정."""

    population: PopulationConfig = Field(default_factory=PopulationConfig)
    corpus: CorpusConfig = Field(default_factory=CorpusConfig)
    output_dir: str = Field(default="data", description="산출물 디렉터리")


def load_synth_config(path: Path) -> SynthConfig:
    """YAML에서 합성 설정을 읽습니다.

    Args:
        path: 설정 YAML 경로

    Returns:
        검증된 SynthConfig

    Raises:
        FileNotFoundError: 파일이 없는 경우
    """
    if not path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return SynthConfig.model_validate(raw)
