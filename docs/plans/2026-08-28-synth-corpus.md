# 합성 코퍼스 생성기 (synth/) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 가상 조직 하나를 통째로 만들어, 사람 단위로 일관된 PII가 박힌 한국어 문서 코퍼스를 정답 span과 함께 생성한다.

**Architecture:** 2단계 생성이다. Stage 1이 조직 트리·구성원·사번을 만들어 `Population`을 내고, Stage 2가 장르별 YAML 템플릿에 구성원을 꽂아 문서를 렌더링하면서 **치환 시점에 span 오프셋을 직접 기록**한다. 그 뒤 표기 흔들림(perturb)을 편집(Edit) 목록으로 적용하며 오프셋을 재계산한다. 외부 데이터·네트워크 없이 동작하고, 시드가 같으면 바이트 단위로 같은 결과를 낸다.

**Tech Stack:** Python 3.11+, pydantic v2 (설정 검증), PyYAML (템플릿), 표준 라이브러리 `random`. pytest + ruff.

**Spec:** [`docs/design/2026-08-28-pii-anonymize-design.md`](../design/2026-08-28-pii-anonymize-design.md) — 특히 §9(합성 데이터 생성기), §6(EntityKey), §1.3(오픈소스 제약).

## Global Constraints

설계에서 가져온 프로젝트 전역 요구사항이다. **모든 태스크의 요구사항에 암묵적으로 포함된다.**

- **Python 3.11+** (`requires-python = ">=3.11"`, ruff `target-version = "py311"`).
- **이 계획 단계의 런타임 의존성은 `pydantic>=2.6`, `pyyaml>=6.0` 둘뿐이다.** numpy·scikit-learn·sentence-transformers는 evaluation 계획에서 추가한다. PolyBed를 포함한 어떤 비공개 패키지도 import하지 않는다 (§1.3-a).
- **타입 힌트 필수** — 모든 함수의 파라미터와 반환값에 타입 힌트를 단다. `Optional[X]` 대신 `X | None`.
- **모듈 docstring 필수** — `__init__.py` 포함 모든 `.py` 첫 줄에 한 줄짜리 한글 docstring.
- **public 함수/클래스 docstring** — Google 스타일, 한글.
- ruff 설정: `line-length = 88`, `select = ["E","F","I","N","UP","B","C4","SIM"]`, `ignore = ["E501"]`, `quote-style = "double"`.
- **테스트 함수명은 영문 snake_case** — ruff `N802`가 한글 함수명을 반려한다. docstring과 주석은 한글로 쓴다.
- **시드 재현성** — 같은 설정·같은 시드면 산출 파일이 바이트 단위로 동일해야 한다 (§9.8).
- **생성 산출물은 커밋하지 않는다** — 전부 `data/` 아래에 쓰고, `data/`는 이미 gitignore돼 있다 (§1.3-b).
- **합성 주민등록번호는 체크섬이 유효해야 한다** — 탐지기가 체크섬으로 검증하므로(§4.5), 체크섬이 틀린 값만 있으면 탐지 평가가 무의미해진다. 유효한 값을 만들되 `data/` 밖으로 나가지 않게 한다.
- **시크릿 기본값 금지** (§1.3-d) — 이 계획 범위에는 시크릿이 없다. 도입하지 않는다.

---

## File Structure

```
pyproject.toml                       패키지 메타 + ruff/pytest 설정
kopii/__init__.py                    버전
kopii/span.py                        Span — 텍스트 안의 PII 한 조각
kopii/labels.py                      PII 타입 정본 + Kaggle 7-type 매핑
kopii/config/__init__.py
kopii/config/schema.py               SynthConfig 등 Pydantic 설정
kopii/synth/__init__.py
kopii/synth/__main__.py              python -m kopii.synth 진입점
kopii/synth/names.py                 한국어 이름·닉네임·조직명 풀
kopii/synth/idgen.py                 사번 채번 스킴 + 정답 메타데이터
kopii/synth/population.py            Stage 1 — 조직 트리와 구성원
kopii/synth/document.py              Stage 2 — 템플릿 렌더링 + span 기록
kopii/synth/perturb.py               표기 흔들림 + 오프셋 재계산
kopii/synth/cli.py                   생성 CLI
kopii/synth/validate.py              생성물 검증 CLI
kopii/synth/templates/*.yaml         장르별 문서 템플릿 6종
configs/synth.yaml                   기본 생성 설정
.github/workflows/test.yml           pytest + ruff
tests/                               태스크별 테스트
```

책임 분리 원칙: `population.py`는 **사람**만 알고 문서를 모른다. `document.py`는 **템플릿과 오프셋**만 알고 흔들림을 모른다. `perturb.py`는 **편집과 오프셋 재계산**만 안다. 이 경계 덕분에 각 파일이 독립적으로 테스트된다.

---

### Task 1: 패키지 골격 + Span/라벨 스키마

**Files:**
- Create: `pyproject.toml`
- Create: `kopii/__init__.py`
- Create: `kopii/span.py`
- Create: `kopii/labels.py`
- Create: `.github/workflows/test.yml`
- Test: `tests/__init__.py`, `tests/test_span.py`, `tests/test_labels.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `kopii.span.Span(start: int, end: int, type: str, surface: str, entity_key: str | None = None)` — frozen dataclass, `verify(text: str) -> bool`
  - `kopii.labels.PII_TYPES: tuple[str, ...]`, `KAGGLE_7_ENTITY_TYPES: tuple[str, ...]`, `ENTITY_MERGE_MAP: dict[str, str]`, `to_kaggle7(pii_type: str) -> str`

- [ ] **Step 1: 패키지 골격 파일을 만든다**

`pyproject.toml`:

```toml
[project]
name = "kopii"
version = "0.0.1"
description = "한국어 개인정보를 마스킹 대신 범주화(일반화)하는 비식별 파이프라인"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
    "pydantic>=2.6",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["kopii"]

[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "C4", "SIM"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`kopii/__init__.py`:

```python
"""KoPII — 한국어 개인정보 탐지·범주화 파이프라인."""

__version__ = "0.0.1"
```

`tests/__init__.py`:

```python
"""KoPII 테스트 패키지."""
```

- [ ] **Step 2: Span 테스트를 먼저 쓴다**

`tests/test_span.py`:

```python
"""Span 데이터 구조 테스트."""

import pytest

from kopii.span import Span


def test_verify_matches_source_text() -> None:
    """span 오프셋이 원문과 정확히 대응해야 한다."""
    text = "이름은 김민수입니다."
    span = Span(start=4, end=7, type="NAME", surface="김민수")
    assert span.verify(text) is True


def test_verify_detects_offset_drift() -> None:
    """오프셋이 밀리면 verify가 False여야 한다."""
    text = "이름은 김민수입니다."
    span = Span(start=3, end=6, type="NAME", surface="김민수")
    assert span.verify(text) is False


def test_rejects_surface_length_mismatch() -> None:
    """surface 길이와 span 폭이 다르면 만들 수 없다."""
    with pytest.raises(ValueError, match="폭"):
        Span(start=0, end=3, type="NAME", surface="김민")


def test_rejects_non_positive_width() -> None:
    """빈 span은 허용하지 않는다."""
    with pytest.raises(ValueError, match="커야"):
        Span(start=5, end=5, type="NAME", surface="")
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_span.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kopii.span'`

- [ ] **Step 4: Span을 구현한다**

`kopii/span.py`:

```python
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
            raise ValueError(
                f"end({self.end})는 start({self.start})보다 커야 합니다."
            )
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
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_span.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: 라벨 테스트를 쓴다**

`tests/test_labels.py`:

```python
"""PII 타입 정본과 Kaggle 7-type 매핑 테스트."""

import pytest

from kopii.labels import (
    ENTITY_MERGE_MAP,
    KAGGLE_7_ENTITY_TYPES,
    PII_TYPES,
    to_kaggle7,
)


def test_every_fine_type_maps_to_kaggle7() -> None:
    """세밀 타입은 전부 Kaggle 7-type 중 하나로 내려가야 한다."""
    for pii_type in PII_TYPES:
        assert to_kaggle7(pii_type) in KAGGLE_7_ENTITY_TYPES


def test_merge_map_covers_exactly_the_fine_types() -> None:
    """매핑 키 집합이 PII 타입 정본과 일치해야 한다."""
    assert set(ENTITY_MERGE_MAP) == set(PII_TYPES)


def test_korean_specific_types_exist() -> None:
    """Kaggle 7-type에 없는 한국 타입이 정본에 있어야 한다."""
    for pii_type in ("RRN", "EMPLOYEE_ID", "NICKNAME"):
        assert pii_type in PII_TYPES


def test_unknown_type_raises() -> None:
    """정본에 없는 타입은 매핑을 거부한다."""
    with pytest.raises(KeyError):
        to_kaggle7("UNKNOWN_TYPE")
```

- [ ] **Step 7: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_labels.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kopii.labels'`

- [ ] **Step 8: 라벨 모듈을 구현한다**

`kopii/labels.py`:

```python
"""PII 타입 정본과 외부 데이터셋 라벨 매핑."""

from __future__ import annotations

# 익명화 계층이 타입마다 다르므로 세밀한 타입을 정본으로 둔다.
# 세밀 → 거침은 손실 없이 내려가지만 반대는 복구되지 않는다.
PII_TYPES: tuple[str, ...] = (
    "NAME",
    "NICKNAME",
    "RRN",
    "EMPLOYEE_ID",
    "PHONE",
    "EMAIL",
    "ADDRESS",
    "ACCOUNT",
    "CARD",
    "DOB",
    "URL",
    "USERNAME",
)

# 외부 PII 데이터셋(Nemotron, AI4Privacy 등)이 물리는 거친 스키마.
KAGGLE_7_ENTITY_TYPES: tuple[str, ...] = (
    "NAME_STUDENT",
    "EMAIL",
    "USERNAME",
    "ID_NUM",
    "PHONE_NUM",
    "URL_PERSONAL",
    "STREET_ADDRESS",
)

# 세밀 → 거침 매핑. Kaggle 7-type에는 RRN·EMPLOYEE_ID·NICKNAME이 없어
# 각각 ID_NUM·USERNAME으로 흡수된다. DOB도 전용 타입이 없어 ID_NUM으로 둔다.
ENTITY_MERGE_MAP: dict[str, str] = {
    "NAME": "NAME_STUDENT",
    "NICKNAME": "USERNAME",
    "USERNAME": "USERNAME",
    "RRN": "ID_NUM",
    "EMPLOYEE_ID": "ID_NUM",
    "ACCOUNT": "ID_NUM",
    "CARD": "ID_NUM",
    "DOB": "ID_NUM",
    "PHONE": "PHONE_NUM",
    "EMAIL": "EMAIL",
    "ADDRESS": "STREET_ADDRESS",
    "URL": "URL_PERSONAL",
}


def to_kaggle7(pii_type: str) -> str:
    """세밀 PII 타입을 Kaggle 7-type으로 내립니다.

    Args:
        pii_type: PII_TYPES 중 하나

    Returns:
        KAGGLE_7_ENTITY_TYPES 중 하나

    Raises:
        KeyError: 정본에 없는 타입인 경우
    """
    if pii_type not in ENTITY_MERGE_MAP:
        raise KeyError(f"매핑되지 않은 PII 타입입니다: {pii_type}")
    return ENTITY_MERGE_MAP[pii_type]
```

- [ ] **Step 9: 전체 테스트와 린트를 돌린다**

Run:
```bash
python -m pytest tests/ -v
python -m ruff check kopii tests
python -m ruff format --check kopii tests
```
Expected: 8 passed, ruff 통과

- [ ] **Step 10: 테스트 CI를 추가한다**

`.github/workflows/test.yml`:

```yaml
name: test

on:
  pull_request:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: 의존성 설치
        run: pip install -e ".[dev]"
      - name: 린트
        run: |
          ruff check kopii tests
          ruff format --check kopii tests
      - name: 테스트
        run: pytest tests -v
```

- [ ] **Step 11: 커밋한다**

```bash
git add pyproject.toml kopii tests .github/workflows/test.yml
git commit -m "feat: 패키지 골격과 Span/라벨 스키마

- Span: 오프셋과 surface 길이 일치를 생성 시점에 강제
- labels: 세밀 PII 타입 정본 + Kaggle 7-type 손실 매핑
- pytest/ruff CI 추가"
```

---

### Task 2: 사번 채번 스킴

**Files:**
- Create: `kopii/synth/__init__.py`
- Create: `kopii/synth/idgen.py`
- Test: `tests/synth/__init__.py`, `tests/synth/test_idgen.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `kopii.synth.idgen.IdSchemeInfo(scheme: str, variant_ids: tuple[str, ...], structural_digits: dict[str, int])` — frozen dataclass
  - `kopii.synth.idgen.IdScheme` — Protocol: `issue(rng: random.Random) -> tuple[str, str]`, `info() -> IdSchemeInfo`
  - `kopii.synth.idgen.SequentialBlockScheme(blocks: tuple[str, ...] = ("23", "24"), serial_digits: int = 5, project_ratio: float = 0.1, project_prefix: str = "K")`
  - `kopii.synth.idgen.OrgCodedScheme(years: tuple[int, ...] = (24, 25), divisions: str = "ABCDE", teams: str = "12345678", serial_digits: int = 4)`
  - `kopii.synth.idgen.build_scheme(name: str) -> IdScheme`

**왜 두 개의 스킴인가:** 설계 §5 장치 ①은 사번 포맷을 값 리스트에서 자동 추론한다고 주장한다. 한 포맷에서만 검증하면 오버피팅을 코퍼스로 옮긴 것에 불과하므로, 구조가 다른 두 포맷을 반드시 제공한다. `structural_digits`는 그 추론기를 채점할 **정답**이다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/synth/__init__.py`:

```python
"""synth 모듈 테스트 패키지."""
```

`tests/synth/test_idgen.py`:

```python
"""사번 채번 스킴 테스트."""

import random
import re

import pytest

from kopii.synth.idgen import (
    OrgCodedScheme,
    SequentialBlockScheme,
    build_scheme,
)


def test_sequential_block_format() -> None:
    """정규직 사번은 블록 접두 + 일련번호 형태여야 한다."""
    scheme = SequentialBlockScheme(blocks=("23",), serial_digits=5, project_ratio=0.0)
    rng = random.Random(0)
    value, variant = scheme.issue(rng)
    assert variant == "FULLTIME"
    assert re.fullmatch(r"23\d{5}", value)


def test_sequential_block_serials_are_unique() -> None:
    """같은 블록 안에서 일련번호가 겹치지 않아야 한다."""
    scheme = SequentialBlockScheme(blocks=("23",), serial_digits=5, project_ratio=0.0)
    rng = random.Random(0)
    values = [scheme.issue(rng)[0] for _ in range(500)]
    assert len(set(values)) == 500


def test_project_variant_uses_prefix() -> None:
    """프로젝트 사번은 접두 문자 + 6자리여야 한다."""
    scheme = SequentialBlockScheme(project_ratio=1.0, project_prefix="K")
    rng = random.Random(0)
    value, variant = scheme.issue(rng)
    assert variant == "PROJECT"
    assert re.fullmatch(r"K\d{6}", value)


def test_sequential_block_info_reports_structural_digits() -> None:
    """추론기 채점용 정답 메타를 돌려줘야 한다."""
    scheme = SequentialBlockScheme(blocks=("23", "24"), serial_digits=5)
    info = scheme.info()
    assert info.scheme == "sequential_block"
    assert info.structural_digits["FULLTIME"] == 2
    assert set(info.variant_ids) == {"FULLTIME", "PROJECT"}


def test_org_coded_format_and_info() -> None:
    """조직 코드 내장형은 구조 자릿수가 4다."""
    scheme = OrgCodedScheme(years=(25,), divisions="A", teams="3", serial_digits=4)
    rng = random.Random(0)
    value, variant = scheme.issue(rng)
    assert variant == "ORGCODED"
    assert re.fullmatch(r"25A3-\d{4}", value)
    assert scheme.info().structural_digits["ORGCODED"] == 4


def test_same_seed_reproduces_same_ids() -> None:
    """같은 시드면 같은 사번 열이 나와야 한다."""
    first = [SequentialBlockScheme().issue(random.Random(7))[0] for _ in range(1)]
    second = [SequentialBlockScheme().issue(random.Random(7))[0] for _ in range(1)]
    assert first == second


def test_build_scheme_rejects_unknown_name() -> None:
    """알 수 없는 스킴 이름은 거부한다."""
    with pytest.raises(ValueError, match="알 수 없는"):
        build_scheme("no_such_scheme")
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/synth/test_idgen.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kopii.synth'`

- [ ] **Step 3: 채번 스킴을 구현한다**

`kopii/synth/__init__.py`:

```python
"""합성 코퍼스 생성기 — 가상 조직과 문서를 만든다."""
```

`kopii/synth/idgen.py`:

```python
"""합성 사번 채번 스킴과 추론기 채점용 정답 메타데이터."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class IdSchemeInfo:
    """채번 스킴의 정답 메타데이터.

    설계 §5 장치 ①의 ID 스키마 추론기를 채점하려면 "정답 구조 자릿수"가
    필요하다. 생성 시점에 기록해 manifest로 내보낸다.

    Args:
        scheme: 스킴 이름
        variant_ids: 이 스킴이 발급하는 variant 식별자
        structural_digits: variant별 구조적(비일련) 선두 자릿수
    """

    scheme: str
    variant_ids: tuple[str, ...]
    structural_digits: dict[str, int]


class IdScheme(Protocol):
    """사번 채번 스킴 인터페이스."""

    def issue(self, rng: random.Random) -> tuple[str, str]:
        """사번을 하나 발급합니다.

        Args:
            rng: 난수 생성기

        Returns:
            (사번, variant 식별자)
        """
        ...

    def info(self) -> IdSchemeInfo:
        """정답 메타데이터를 돌려줍니다."""
        ...


class SequentialBlockScheme:
    """조직 코드가 없는 순차 채번 스킴.

    블록 접두 뒤에 일련번호가 붙는다. 사번만으로는 소속을 알 수 없고,
    선두 블록만이 구조적 정보다.

    Args:
        blocks: 채번 블록 접두 목록
        serial_digits: 일련번호 자릿수
        project_ratio: 프로젝트 인력 비율 (0.0~1.0)
        project_prefix: 프로젝트 사번 접두 문자
    """

    def __init__(
        self,
        blocks: tuple[str, ...] = ("23", "24"),
        serial_digits: int = 5,
        project_ratio: float = 0.1,
        project_prefix: str = "K",
    ) -> None:
        if not blocks:
            raise ValueError("blocks는 최소 하나가 필요합니다.")
        if len({len(b) for b in blocks}) != 1:
            raise ValueError(f"블록 길이가 서로 달라 구조 자릿수가 모호합니다: {blocks}")
        if not 0.0 <= project_ratio <= 1.0:
            raise ValueError(f"project_ratio는 0~1이어야 합니다: {project_ratio}")

        self._blocks = blocks
        self._serial_digits = serial_digits
        self._project_ratio = project_ratio
        self._project_prefix = project_prefix
        self._counters: dict[str, int] = dict.fromkeys(blocks, 0)
        self._project_counter = 0

    def issue(self, rng: random.Random) -> tuple[str, str]:
        """사번을 하나 발급합니다.

        Args:
            rng: 난수 생성기

        Returns:
            (사번, "FULLTIME" 또는 "PROJECT")
        """
        if rng.random() < self._project_ratio:
            self._project_counter += 1
            return f"{self._project_prefix}{self._project_counter:06d}", "PROJECT"

        block = rng.choice(self._blocks)
        self._counters[block] += 1
        serial = f"{self._counters[block]:0{self._serial_digits}d}"
        return f"{block}{serial}", "FULLTIME"

    def info(self) -> IdSchemeInfo:
        """정답 메타데이터를 돌려줍니다."""
        return IdSchemeInfo(
            scheme="sequential_block",
            variant_ids=("FULLTIME", "PROJECT"),
            structural_digits={
                "FULLTIME": len(self._blocks[0]),
                "PROJECT": len(self._project_prefix),
            },
        )


class OrgCodedScheme:
    """조직 코드를 사번에 담는 채번 스킴.

    입사연도 2자 + 본부 1자 + 팀 1자 + 하이픈 + 일련번호. 사번만 보고도
    소속을 파싱할 수 있는 대조군이며, 추론기가 포맷에 종속되지 않는지
    검증하는 두 번째 형태다.

    Args:
        years: 입사연도 두 자리 목록
        divisions: 본부 코드로 쓸 문자들
        teams: 팀 코드로 쓸 문자들
        serial_digits: 일련번호 자릿수
    """

    def __init__(
        self,
        years: tuple[int, ...] = (24, 25),
        divisions: str = "ABCDE",
        teams: str = "12345678",
        serial_digits: int = 4,
    ) -> None:
        if not years or not divisions or not teams:
            raise ValueError("years·divisions·teams는 비어 있을 수 없습니다.")
        self._years = years
        self._divisions = divisions
        self._teams = teams
        self._serial_digits = serial_digits
        self._counter = 0

    def issue(self, rng: random.Random) -> tuple[str, str]:
        """사번을 하나 발급합니다.

        Args:
            rng: 난수 생성기

        Returns:
            (사번, "ORGCODED")
        """
        year = rng.choice(self._years)
        division = rng.choice(self._divisions)
        team = rng.choice(self._teams)
        self._counter += 1
        serial = f"{self._counter:0{self._serial_digits}d}"
        return f"{year:02d}{division}{team}-{serial}", "ORGCODED"

    def info(self) -> IdSchemeInfo:
        """정답 메타데이터를 돌려줍니다."""
        # 연도 2자 + 본부 1자 + 팀 1자 = 4자리가 구조적 정보다.
        return IdSchemeInfo(
            scheme="org_coded",
            variant_ids=("ORGCODED",),
            structural_digits={"ORGCODED": 4},
        )


def build_scheme(name: str) -> IdScheme:
    """이름으로 채번 스킴을 만듭니다.

    Args:
        name: "sequential_block" 또는 "org_coded"

    Returns:
        해당 스킴 인스턴스

    Raises:
        ValueError: 알 수 없는 이름인 경우
    """
    if name == "sequential_block":
        return SequentialBlockScheme()
    if name == "org_coded":
        return OrgCodedScheme()
    raise ValueError(f"알 수 없는 채번 스킴입니다: {name}")
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/synth/test_idgen.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋한다**

```bash
git add kopii/synth tests/synth
git commit -m "feat(synth): 사번 채번 스킴 2종과 추론기 채점용 정답 메타

순차 채번(조직 코드 없음)과 조직 코드 내장형을 모두 제공해
ID 스키마 추론기가 한 포맷에 오버피팅되지 않는지 검증할 수 있게 한다."
```

---

### Task 3: 가상 조직과 구성원 생성 (Stage 1)

**Files:**
- Create: `kopii/synth/names.py`
- Create: `kopii/synth/population.py`
- Test: `tests/synth/test_population.py`

**Interfaces:**
- Consumes: `kopii.synth.idgen.IdScheme`, `IdSchemeInfo`, `build_scheme`
- Produces:
  - `kopii.synth.population.OrgUnit(code: str, name: str, level: str, parent: str | None)`
  - `kopii.synth.population.Person(person_id, name, nickname, employee_id, id_variant, division, team, title, birth_year, gender, rrn, phone, email, address)` — 전부 `str` (birth_year만 `int`, nickname만 `str | None`)
  - `kopii.synth.population.Population(people: tuple[Person, ...], org: tuple[OrgUnit, ...], id_scheme: IdSchemeInfo)` — 메서드 `hr_directory() -> dict[str, tuple[str, str, str]]`
  - `kopii.synth.population.generate_population(size: int, seed: int, scheme_name: str = "sequential_block", divisions: int = 5, teams_per_division: tuple[int, int] = (3, 8), nickname_ratio: float = 0.5) -> Population`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/synth/test_population.py`:

```python
"""가상 조직·구성원 생성 테스트."""

import re

from kopii.synth.population import generate_population


def _rrn_checksum_valid(rrn: str) -> bool:
    """주민등록번호 체크섬을 검증한다 (테스트용 독립 구현)."""
    digits = rrn.replace("-", "")
    weights = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
    total = sum(int(d) * w for d, w in zip(digits[:12], weights, strict=True))
    return (11 - total % 11) % 10 == int(digits[12])


def test_generates_requested_size() -> None:
    """요청한 인원 수만큼 만들어야 한다."""
    pop = generate_population(size=120, seed=1)
    assert len(pop.people) == 120


def test_employee_ids_are_unique() -> None:
    """사번은 조직 안에서 유일해야 한다."""
    pop = generate_population(size=300, seed=1)
    ids = [p.employee_id for p in pop.people]
    assert len(set(ids)) == len(ids)


def test_hr_directory_covers_everyone() -> None:
    """hr_directory는 모든 구성원을 담아야 한다 (지식 프로바이더 정답)."""
    pop = generate_population(size=80, seed=2)
    directory = pop.hr_directory()
    assert len(directory) == 80
    for person in pop.people:
        assert directory[person.employee_id] == (
            person.division,
            person.team,
            person.title,
        )


def test_every_team_belongs_to_a_division() -> None:
    """조직 트리에 고아 팀이 없어야 한다."""
    pop = generate_population(size=60, seed=3)
    division_codes = {u.code for u in pop.org if u.level == "division"}
    teams = [u for u in pop.org if u.level == "team"]
    assert teams
    for team in teams:
        assert team.parent in division_codes


def test_rrn_checksum_is_valid() -> None:
    """탐지기가 체크섬으로 검증하므로 합성 값도 유효해야 한다."""
    pop = generate_population(size=50, seed=4)
    for person in pop.people:
        assert re.fullmatch(r"\d{6}-\d{7}", person.rrn)
        assert _rrn_checksum_valid(person.rrn), person.rrn


def test_address_is_populated() -> None:
    """주소는 시·구·도로·번지가 모두 채워져야 한다."""
    pop = generate_population(size=30, seed=6)
    for person in pop.people:
        parts = person.address.split()
        assert len(parts) == 4, person.address
        assert parts[3].isdigit()


def test_some_people_have_no_nickname() -> None:
    """닉네임은 일부만 갖는다 — 템플릿의 requires 분기를 실제로 태운다."""
    pop = generate_population(size=200, seed=5, nickname_ratio=0.5)
    nicknames = [p.nickname for p in pop.people]
    assert any(n is None for n in nicknames)
    assert any(n is not None for n in nicknames)


def test_same_seed_is_reproducible() -> None:
    """같은 시드면 완전히 같은 인구가 나와야 한다."""
    first = generate_population(size=40, seed=9)
    second = generate_population(size=40, seed=9)
    assert first.people == second.people
    assert first.org == second.org


def test_different_seed_differs() -> None:
    """시드가 다르면 결과도 달라야 한다."""
    first = generate_population(size=40, seed=9)
    second = generate_population(size=40, seed=10)
    assert first.people != second.people
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/synth/test_population.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kopii.synth.population'`

- [ ] **Step 3: 이름 풀을 구현한다**

`kopii/synth/names.py`:

```python
"""합성 인구용 한국어 이름·닉네임·조직명 풀."""

from __future__ import annotations

SURNAMES: tuple[str, ...] = (
    "김", "이", "박", "최", "정", "강", "조", "윤", "장", "임",
    "한", "오", "서", "신", "권", "황", "안", "송", "전", "홍",
)

GIVEN_NAMES: tuple[str, ...] = (
    "민준", "서연", "도윤", "지우", "예준", "하윤", "시우", "서윤",
    "주원", "지호", "지민", "수아", "건우", "다은", "우진", "채원",
    "현우", "지아", "선우", "은서", "유준", "소율", "시윤", "지윤",
    "준서", "예린", "민재", "가은", "정우", "서아", "동현", "나윤",
    "태윤", "예은", "성민", "하린", "재원", "윤서", "승우", "지안",
)

NICKNAMES: tuple[str, ...] = (
    "MASON", "OLIVE", "RIVER", "NOVA", "PIPER", "ATLAS", "WREN",
    "ORION", "SAGE", "FINN", "IRIS", "JUNO", "KAI", "LUNA", "MILO",
    "NORA", "OTIS", "PEARL", "QUINN", "ROWAN", "SOLI", "TESS",
    "URSA", "VEGA", "WILLOW", "XENA", "YARA", "ZEPH", "BRIAR", "CLOVE",
)

DIVISION_NAMES: tuple[str, ...] = (
    "개발본부", "사업본부", "경영지원본부", "데이터본부", "고객경험본부",
    "전략본부", "품질본부", "인프라본부",
)

TEAM_NAMES: tuple[str, ...] = (
    "플랫폼개발팀", "서비스개발팀", "인프라팀", "데이터엔지니어링팀",
    "모델링팀", "QA팀", "기획팀", "디자인팀", "영업1팀", "영업2팀",
    "인사팀", "재무팀", "법무팀", "보안팀", "고객지원팀", "마케팅팀",
    "리서치팀", "SRE팀", "MLOps팀", "파트너십팀",
)

TITLES: tuple[str, ...] = ("사원", "선임", "책임", "수석", "팀장", "부장")

CITIES: tuple[str, ...] = ("서울시", "성남시", "고양시", "부산시", "대전시")

DISTRICTS: tuple[str, ...] = ("강남구", "서초구", "송파구", "마포구", "분당구")

ROADS: tuple[str, ...] = ("테헤란로", "판교로", "월드컵북로", "올림픽로", "가로수길")
```

- [ ] **Step 4: 인구 생성기를 구현한다**

`kopii/synth/population.py`:

```python
"""가상 조직과 구성원을 생성하는 Stage 1."""

from __future__ import annotations

import random
from dataclasses import dataclass

from kopii.synth import names
from kopii.synth.idgen import IdSchemeInfo, build_scheme

_RRN_WEIGHTS: tuple[int, ...] = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)


@dataclass(frozen=True, slots=True)
class OrgUnit:
    """조직 트리의 한 단위.

    Args:
        code: 단위 코드
        name: 표시 이름
        level: "division" 또는 "team"
        parent: 상위 단위 코드. 최상위면 None
    """

    code: str
    name: str
    level: str
    parent: str | None


@dataclass(frozen=True, slots=True)
class Person:
    """가상 구성원 한 명.

    Args:
        person_id: 정답 EntityKey. 같은 사람의 모든 span이 공유한다
        name: 한국어 이름
        nickname: 사내 영문 닉네임. 없을 수 있다
        employee_id: 사번
        id_variant: 사번 variant 식별자
        division: 소속 본부명
        team: 소속 팀명
        title: 직급
        birth_year: 출생 연도
        gender: "M" 또는 "F"
        rrn: 체크섬이 유효한 합성 주민등록번호
        phone: 휴대전화번호
        email: 사내 이메일
        address: 근무지 주소
    """

    person_id: str
    name: str
    nickname: str | None
    employee_id: str
    id_variant: str
    division: str
    team: str
    title: str
    birth_year: int
    gender: str
    rrn: str
    phone: str
    email: str
    address: str


@dataclass(frozen=True, slots=True)
class Population:
    """생성된 가상 조직 전체.

    Args:
        people: 구성원 목록
        org: 조직 트리
        id_scheme: 사번 채번 스킴의 정답 메타데이터
    """

    people: tuple[Person, ...]
    org: tuple[OrgUnit, ...]
    id_scheme: IdSchemeInfo

    def hr_directory(self) -> dict[str, tuple[str, str, str]]:
        """사번으로 소속을 조회하는 정답표를 만듭니다.

        설계 §4.3에서 "사번만으로는 소속을 알 수 없고 hr_directory 조회가
        필수"라고 한 그 조회표의 정답판이다.

        Returns:
            사번 → (본부, 팀, 직급)
        """
        return {p.employee_id: (p.division, p.team, p.title) for p in self.people}


def _make_rrn(birth_year: int, gender: str, rng: random.Random) -> str:
    """체크섬이 유효한 합성 주민등록번호를 만듭니다.

    탐지기가 체크섬으로 검증하므로(설계 §4.5) 합성 값도 유효해야
    탐지 평가가 의미를 갖는다. 산출물은 gitignore된 data/ 아래에만 둔다.

    Args:
        birth_year: 출생 연도 (1900~1999를 가정)
        gender: "M" 또는 "F"
        rng: 난수 생성기

    Returns:
        "YYMMDD-Gxxxxxc" 형태의 13자리 번호
    """
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    front = f"{birth_year % 100:02d}{month:02d}{day:02d}"
    gender_digit = 1 if gender == "M" else 2
    back6 = f"{gender_digit}{rng.randint(0, 99999):05d}"
    twelve = front + back6
    total = sum(int(d) * w for d, w in zip(twelve, _RRN_WEIGHTS, strict=True))
    check = (11 - total % 11) % 10
    return f"{front}-{back6}{check}"


def _build_org(
    rng: random.Random, divisions: int, teams_per_division: tuple[int, int]
) -> tuple[tuple[OrgUnit, ...], list[tuple[str, str]]]:
    """조직 트리를 만들고 (본부명, 팀명) 배치 후보를 함께 돌려줍니다.

    Args:
        rng: 난수 생성기
        divisions: 본부 수
        teams_per_division: 본부당 팀 수 범위 (최소, 최대)

    Returns:
        (조직 단위 목록, (본부명, 팀명) 쌍 목록)
    """
    if divisions > len(names.DIVISION_NAMES):
        raise ValueError(
            f"본부 수({divisions})가 준비된 이름 수({len(names.DIVISION_NAMES)})를 넘습니다."
        )

    units: list[OrgUnit] = []
    placements: list[tuple[str, str]] = []
    team_pool = list(names.TEAM_NAMES)
    rng.shuffle(team_pool)
    cursor = 0

    low, high = teams_per_division
    for index in range(divisions):
        division_name = names.DIVISION_NAMES[index]
        division_code = f"D{index}"
        units.append(
            OrgUnit(code=division_code, name=division_name, level="division", parent=None)
        )
        team_count = rng.randint(low, high)
        for offset in range(team_count):
            if cursor >= len(team_pool):
                cursor = 0  # 팀 이름이 모자라면 순환한다
            team_name = f"{team_pool[cursor]}"
            cursor += 1
            team_code = f"{division_code}T{offset}"
            units.append(
                OrgUnit(
                    code=team_code,
                    name=team_name,
                    level="team",
                    parent=division_code,
                )
            )
            placements.append((division_name, team_name))

    return tuple(units), placements


def generate_population(
    size: int,
    seed: int,
    scheme_name: str = "sequential_block",
    divisions: int = 5,
    teams_per_division: tuple[int, int] = (3, 8),
    nickname_ratio: float = 0.5,
) -> Population:
    """가상 조직과 구성원을 생성합니다.

    Args:
        size: 구성원 수
        seed: 난수 시드
        scheme_name: 사번 채번 스킴 이름
        divisions: 본부 수
        teams_per_division: 본부당 팀 수 범위
        nickname_ratio: 닉네임을 갖는 구성원 비율 (0.0~1.0)

    Returns:
        생성된 Population

    Raises:
        ValueError: size가 1 미만이거나 nickname_ratio가 범위를 벗어난 경우
    """
    if size < 1:
        raise ValueError(f"size는 1 이상이어야 합니다: {size}")
    if not 0.0 <= nickname_ratio <= 1.0:
        raise ValueError(f"nickname_ratio는 0~1이어야 합니다: {nickname_ratio}")

    rng = random.Random(seed)
    scheme = build_scheme(scheme_name)
    org, placements = _build_org(rng, divisions, teams_per_division)

    people: list[Person] = []
    for index in range(size):
        division, team = rng.choice(placements)
        surname = rng.choice(names.SURNAMES)
        given = rng.choice(names.GIVEN_NAMES)
        gender = rng.choice(("M", "F"))
        birth_year = rng.randint(1970, 1999)
        employee_id, variant = scheme.issue(rng)
        has_nickname = rng.random() < nickname_ratio
        nickname = rng.choice(names.NICKNAMES) if has_nickname else None
        people.append(
            Person(
                person_id=f"p_{index:05d}",
                name=f"{surname}{given}",
                nickname=nickname,
                employee_id=employee_id,
                id_variant=variant,
                division=division,
                team=team,
                title=rng.choice(names.TITLES),
                birth_year=birth_year,
                gender=gender,
                rrn=_make_rrn(birth_year, gender, rng),
                phone=f"010-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
                email=f"user{index:05d}@example.co.kr",
                address=(
                    f"{rng.choice(names.CITIES)} {rng.choice(names.DISTRICTS)} "
                    f"{rng.choice(names.ROADS)} {rng.randint(1, 300)}"
                ),
            )
        )

    return Population(people=tuple(people), org=org, id_scheme=scheme.info())
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/synth/test_population.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: 린트를 돌리고 커밋한다**

```bash
python -m ruff check kopii tests && python -m ruff format kopii tests
git add kopii/synth/names.py kopii/synth/population.py tests/synth/test_population.py
git commit -m "feat(synth): 가상 조직과 구성원 생성 (Stage 1)

- hr_directory()가 지식 프로바이더의 정답표를 제공
- 합성 주민번호는 체크섬 유효 — 탐지기 평가가 의미를 갖도록
- 닉네임은 일부만 부여해 템플릿 requires 분기를 실제로 태운다"
```

---

### Task 4: 템플릿 렌더링과 span 기록 (Stage 2)

**Files:**
- Create: `kopii/synth/document.py`
- Create: `kopii/synth/templates/meeting_note.yaml`
- Create: `kopii/synth/templates/email.yaml`
- Create: `kopii/synth/templates/hr_notice.yaml`
- Create: `kopii/synth/templates/approval_doc.yaml`
- Create: `kopii/synth/templates/chat_log.yaml`
- Create: `kopii/synth/templates/issue_ticket.yaml`
- Test: `tests/synth/test_document.py`

**Interfaces:**
- Consumes: `kopii.span.Span`, `kopii.synth.population.Person`, `Population`
- Produces:
  - `kopii.synth.document.Document(doc_id: str, genre: str, template_id: str, text: str, spans: tuple[Span, ...], person_ids: tuple[str, ...])`
  - `kopii.synth.document.FIELD_TYPES: dict[str, str]`
  - `kopii.synth.document.load_templates(directory: Path | None = None) -> list[DocumentTemplate]`
  - `kopii.synth.document.DocumentTemplate` — pydantic 모델: `id: str`, `genre: str`, `persons: tuple[int, int]`, `lines: list[TemplateLine]`
  - `kopii.synth.document.TemplateLine` — pydantic 모델: `text: str`, `repeat: str | None = None`, `requires: list[str] = []`
  - `kopii.synth.document.generate_documents(population: Population, templates: list[DocumentTemplate], count: int, genre_weights: dict[str, float], seed: int) -> list[Document]`

> **실행 중 개정** — 템플릿의 `persons` 범위는 그 템플릿이 실제로 참조하는 `personN`
> 슬롯 개수와 일치해야 한다. 어긋나면 (a) 참조보다 적게 뽑힐 때 렌더링이 예외로 죽고,
> (b) 많이 뽑힐 때 본문에 등장하지 않는 사람이 `person_ids`에 실려 메타가 사실과
> 달라진다. `repeat: person` 줄이 있는 템플릿은 모든 actor가 등장하므로 상한이 자유롭다.
> 위 YAML은 개정된 값이며, `test_every_template_renders_at_min_and_max_persons`가
> 이 규칙을 강제한다.

**핵심:** 렌더러는 슬롯을 치환하는 **그 순간에** 오프셋을 기록한다. 다 만들고 나서 텍스트를 되짚어 찾지 않는다 — 같은 이름이 두 번 나오면 되짚기는 틀린 위치를 잡는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/synth/test_document.py`:

```python
"""템플릿 렌더링과 span 기록 테스트."""

import pytest

from kopii.synth.document import (
    DocumentTemplate,
    TemplateLine,
    generate_documents,
    load_templates,
    render_document,
)
from kopii.synth.population import generate_population


def _template(lines: list[TemplateLine], persons: tuple[int, int] = (1, 1)) -> DocumentTemplate:
    """테스트용 템플릿을 만든다."""
    return DocumentTemplate(id="t_test", genre="test", persons=persons, lines=lines)


def test_records_span_for_pii_field() -> None:
    """PII 필드를 치환하면 span이 정확한 오프셋으로 기록돼야 한다."""
    pop = generate_population(size=1, seed=1)
    template = _template([TemplateLine(text="담당자는 {person0.name}입니다.")])
    doc = render_document("d_0", template, [pop.people[0]], {"date": "2026-01-02"})

    assert len(doc.spans) == 1
    span = doc.spans[0]
    assert span.type == "NAME"
    assert span.verify(doc.text)
    assert span.entity_key == pop.people[0].person_id


def test_repeated_name_gets_distinct_offsets() -> None:
    """같은 값이 두 번 나오면 서로 다른 오프셋으로 기록돼야 한다."""
    pop = generate_population(size=1, seed=1)
    template = _template(
        [TemplateLine(text="{person0.name} / {person0.name}")]
    )
    doc = render_document("d_0", template, [pop.people[0]], {"date": "2026-01-02"})

    assert len(doc.spans) == 2
    assert doc.spans[0].start != doc.spans[1].start
    for span in doc.spans:
        assert span.verify(doc.text)


def test_non_pii_field_produces_no_span() -> None:
    """소속·직급은 PII 타입 정본에 없으므로 span을 만들지 않는다."""
    pop = generate_population(size=1, seed=1)
    template = _template([TemplateLine(text="{person0.team} {person0.title}")])
    doc = render_document("d_0", template, [pop.people[0]], {"date": "2026-01-02"})
    assert doc.spans == ()


def test_requires_skips_line_when_field_missing() -> None:
    """닉네임이 없는 사람에게는 해당 줄을 건너뛴다."""
    pop = generate_population(size=200, seed=5, nickname_ratio=0.5)
    without = next(p for p in pop.people if p.nickname is None)
    template = _template(
        [
            TemplateLine(text="이름: {person0.name}"),
            TemplateLine(text="닉네임: {person0.nickname}", requires=["nickname"]),
        ]
    )
    doc = render_document("d_0", template, [without], {"date": "2026-01-02"})
    assert "닉네임" not in doc.text
    assert all(span.type != "NICKNAME" for span in doc.spans)


def test_repeat_emits_one_line_per_person() -> None:
    """repeat 줄은 등장 인물마다 한 줄씩 나와야 한다."""
    pop = generate_population(size=3, seed=1)
    template = _template(
        [TemplateLine(text="- {person.name}님", repeat="person")],
        persons=(3, 3),
    )
    doc = render_document("d_0", template, list(pop.people), {"date": "2026-01-02"})
    assert doc.text.count("\n") == 2
    assert len(doc.spans) == 3


def test_unknown_slot_raises() -> None:
    """정의되지 않은 슬롯은 조용히 남기지 않고 실패시킨다."""
    pop = generate_population(size=1, seed=1)
    template = _template([TemplateLine(text="{person0.no_such_field}")])
    with pytest.raises(ValueError, match="슬롯"):
        render_document("d_0", template, [pop.people[0]], {"date": "2026-01-02"})


def test_shipped_templates_load_with_expected_genres() -> None:
    """레포에 포함된 템플릿 6종이 전부 로드되고 장르가 맞아야 한다.

    렌더링 검증은 test_generate_documents_roundtrip_and_reproducible가
    전 템플릿에 대해 수행한다.
    """
    templates = load_templates()
    assert len(templates) == 6
    genres = {t.genre for t in templates}
    assert genres == {
        "meeting_note",
        "email",
        "hr_notice",
        "approval_doc",
        "chat_log",
        "issue_ticket",
    }


def test_generate_documents_roundtrip_and_reproducible() -> None:
    """생성된 모든 문서의 span이 텍스트와 일치하고 재현 가능해야 한다."""
    pop = generate_population(size=50, seed=1)
    templates = load_templates()
    weights = dict.fromkeys(
        ("meeting_note", "email", "hr_notice", "approval_doc", "chat_log", "issue_ticket"),
        1.0,
    )

    first = generate_documents(pop, templates, count=40, genre_weights=weights, seed=7)
    second = generate_documents(pop, templates, count=40, genre_weights=weights, seed=7)

    assert len(first) == 40
    assert first == second
    for doc in first:
        for span in doc.spans:
            assert span.verify(doc.text), f"{doc.doc_id}: {span}"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/synth/test_document.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kopii.synth.document'`

- [ ] **Step 3: 템플릿 6종을 만든다**

`kopii/synth/templates/meeting_note.yaml`:

```yaml
id: meeting_note_v1
genre: meeting_note
persons: [2, 5]
lines:
  - text: "# {doc.date} 주간 회의"
  - text: ""
  - text: "## 참석자"
  - text: "- {person.name}님({person.nickname}) · {person.employee_id}"
    repeat: person
    requires: [nickname]
  - text: "- {person.name}님 · {person.employee_id}"
    repeat: person
  - text: ""
  - text: "## 논의"
  - text: "{person0.name} {person0.title}이 {person0.team} 진행 상황을 공유했습니다."
  - text: "후속 확인은 {person1.name} {person1.title}이 맡기로 했습니다."
```

`kopii/synth/templates/email.yaml`:

```yaml
id: email_v1
genre: email
persons: [2, 2]
lines:
  - text: "받는 사람: {person1.email}"
  - text: "제목: {doc.date} 협업 요청"
  - text: ""
  - text: "{person1.name} {person1.title}님, 안녕하세요."
  - text: "{person0.team}의 {person0.name}입니다."
  - text: "말씀 주신 건은 이번 주 내로 회신드리겠습니다."
  - text: ""
  - text: "--"
  - text: "{person0.division} {person0.team} {person0.title} {person0.name}"
  - text: "{person0.phone} / {person0.email}"
  - text: "{person0.address}"
```

`kopii/synth/templates/hr_notice.yaml`:

```yaml
id: hr_notice_v1
genre: hr_notice
persons: [2, 4]
lines:
  - text: "[인사 공지] {doc.date}자 조직 개편"
  - text: ""
  - text: "- {person.name}({person.employee_id}) → {person.division} {person.team} {person.title}"
    repeat: person
  - text: ""
  - text: "문의: 인사팀 {person0.email}"
```

`kopii/synth/templates/approval_doc.yaml`:

```yaml
id: approval_doc_v1
genre: approval_doc
persons: [1, 1]
lines:
  - text: "결재 문서 번호: 2026-{doc.serial}"
  - text: "기안일: {doc.date}"
  - text: ""
  - text: "| 항목 | 값 |"
  - text: "| --- | --- |"
  - text: "| 기안자 | {person0.name} |"
  - text: "| 사번 | {person0.employee_id} |"
  - text: "| 소속 | {person0.team} |"
  - text: "| 집행 금액 | 1250000 |"
  - text: "| 처리 건수 | 3401277 |"
```

> 마지막 두 행의 숫자는 의도적이다. 설계 §4.5가 지적한 "앵커 없는 7자리 숫자를 사번으로 오탐하는 문제"를 재현하는 오탐 시험대다. 이 숫자에는 span을 달지 않는다.

`kopii/synth/templates/chat_log.yaml`:

```yaml
id: chat_log_v1
genre: chat_log
persons: [2, 2]
lines:
  - text: "[{doc.date}]"
  - text: "{person0.name}: 배포 언제 나가나요?"
  - text: "{person1.name}: 오후에 나갑니다"
  - text: "{person0.name}: 확인 부탁드려요 {person1.nickname}"
    requires: [nickname]
  - text: "{person0.name}: 확인 부탁드려요"
```

> `requires`는 해당 줄의 **모든** person 슬롯에 대해 검사한다. 위 줄은 `person1.nickname`을 참조하므로 person1에 닉네임이 없으면 건너뛰고 그다음 줄이 나간다.

`kopii/synth/templates/issue_ticket.yaml`:

```yaml
id: issue_ticket_v1
genre: issue_ticket
persons: [2, 2]
lines:
  - text: "## ISSUE-{doc.serial}"
  - text: "보고자: {person0.name} ({person0.email})"
  - text: "담당: {person1.name}"
  - text: ""
  - text: "재현 환경에서 로그인 후 500이 발생합니다."
  - text: "연락처: {person0.phone}"
```

- [ ] **Step 4: 렌더러를 구현한다**

`kopii/synth/document.py`:

```python
"""템플릿을 렌더링하며 PII span 오프셋을 기록하는 Stage 2."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from kopii.span import Span
from kopii.synth.population import Person, Population

# 슬롯 문법: {person0.name}, {person.name}(repeat 안), {doc.date}
_SLOT_RE = re.compile(r"\{(\w+)\.(\w+)\}")

# Person 필드 중 PII로 취급해 span을 기록할 것들.
# 소속·직급·출생연도는 준식별자지만 PII 타입 정본에 없으므로 span을 만들지 않는다.
FIELD_TYPES: dict[str, str] = {
    "name": "NAME",
    "nickname": "NICKNAME",
    "employee_id": "EMPLOYEE_ID",
    "rrn": "RRN",
    "phone": "PHONE",
    "email": "EMAIL",
    "address": "ADDRESS",
}

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class TemplateLine(BaseModel):
    """템플릿의 한 줄.

    Args:
        text: 슬롯이 포함된 줄 문자열
        repeat: "person"이면 등장 인물마다 한 줄씩 반복한다
        requires: 이 필드들이 비어 있는 인물에게는 줄을 건너뛴다
    """

    text: str
    repeat: str | None = None
    requires: list[str] = Field(default_factory=list)


class DocumentTemplate(BaseModel):
    """장르별 문서 템플릿.

    Args:
        id: 템플릿 식별자
        genre: 장르 이름
        persons: 등장 인물 수 범위 (최소, 최대)
        lines: 줄 목록
    """

    id: str
    genre: str
    persons: tuple[int, int]
    lines: list[TemplateLine]


@dataclass(frozen=True, slots=True)
class Document:
    """생성된 문서 한 건.

    Args:
        doc_id: 문서 식별자
        genre: 장르
        template_id: 사용한 템플릿 id
        text: 본문
        spans: 정답 PII span 목록
        person_ids: 등장 인물의 person_id 목록
    """

    doc_id: str
    genre: str
    template_id: str
    text: str
    spans: tuple[Span, ...]
    person_ids: tuple[str, ...]


def load_templates(directory: Path | None = None) -> list[DocumentTemplate]:
    """템플릿 YAML을 모두 읽어들입니다.

    Args:
        directory: 템플릿 디렉터리. None이면 패키지 내장 디렉터리

    Returns:
        파일명 순으로 정렬된 템플릿 목록
    """
    target = directory or _TEMPLATE_DIR
    templates: list[DocumentTemplate] = []
    for path in sorted(target.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        templates.append(DocumentTemplate.model_validate(raw))
    return templates


def _resolve(
    obj: str, field: str, actors: dict[str, Person], doc_ctx: dict[str, str]
) -> tuple[str, Person | None]:
    """슬롯 하나를 값으로 풉니다.

    Args:
        obj: 슬롯의 객체 부분 ("doc", "person", "person0" 등)
        field: 슬롯의 필드 부분
        actors: 별칭 → Person
        doc_ctx: 문서 수준 컨텍스트

    Returns:
        (치환할 문자열, 이 값의 주인 Person 또는 None)

    Raises:
        ValueError: 알 수 없는 슬롯이거나 값이 비어 있는 경우
    """
    if obj == "doc":
        if field not in doc_ctx:
            raise ValueError(f"알 수 없는 문서 슬롯입니다: {{doc.{field}}}")
        return doc_ctx[field], None

    person = actors.get(obj)
    if person is None:
        raise ValueError(f"알 수 없는 인물 슬롯입니다: {{{obj}.{field}}}")
    if not hasattr(person, field):
        raise ValueError(f"알 수 없는 인물 필드 슬롯입니다: {{{obj}.{field}}}")

    value = getattr(person, field)
    if value is None:
        raise ValueError(
            f"{obj}.{field}가 비어 있습니다. 템플릿의 requires로 걸러야 합니다."
        )
    return str(value), person


def _render_line(
    text: str,
    actors: dict[str, Person],
    doc_ctx: dict[str, str],
    base_offset: int,
) -> tuple[str, list[Span]]:
    """한 줄을 렌더링하며 span을 기록합니다.

    치환하는 순간에 오프셋을 적는다. 완성된 텍스트에서 값을 되짚어 찾으면
    같은 값이 여러 번 등장할 때 틀린 위치를 잡는다.

    Args:
        text: 슬롯이 포함된 줄
        actors: 별칭 → Person
        doc_ctx: 문서 수준 컨텍스트
        base_offset: 이 줄이 문서에서 시작하는 오프셋

    Returns:
        (렌더된 줄, 이 줄에서 생긴 span 목록)
    """
    parts: list[str] = []
    spans: list[Span] = []
    cursor = 0
    length = 0

    for match in _SLOT_RE.finditer(text):
        literal = text[cursor : match.start()]
        parts.append(literal)
        length += len(literal)

        value, person = _resolve(match.group(1), match.group(2), actors, doc_ctx)
        field = match.group(2)
        if person is not None and field in FIELD_TYPES:
            spans.append(
                Span(
                    start=base_offset + length,
                    end=base_offset + length + len(value),
                    type=FIELD_TYPES[field],
                    surface=value,
                    entity_key=person.person_id,
                )
            )
        parts.append(value)
        length += len(value)
        cursor = match.end()

    parts.append(text[cursor:])
    return "".join(parts), spans


def _line_is_renderable(line: TemplateLine, actors: dict[str, Person]) -> bool:
    """requires 조건을 만족해 이 줄을 낼 수 있는지 판정합니다.

    Args:
        line: 대상 줄
        actors: 별칭 → Person

    Returns:
        줄에서 참조하는 모든 인물이 requires 필드를 갖고 있으면 True
    """
    if not line.requires:
        return True
    referenced = {
        actors[obj]
        for obj, _field in _SLOT_RE.findall(line.text)
        if obj in actors
    }
    return all(
        getattr(person, field, None) is not None
        for person in referenced
        for field in line.requires
    )


def render_document(
    doc_id: str,
    template: DocumentTemplate,
    people: list[Person],
    doc_ctx: dict[str, str],
) -> Document:
    """템플릿과 인물로 문서 한 건을 만듭니다.

    Args:
        doc_id: 문서 식별자
        template: 사용할 템플릿
        people: 등장 인물 (순서가 person0, person1, ... 에 대응)
        doc_ctx: 문서 수준 컨텍스트 (date, serial 등)

    Returns:
        렌더된 Document

    Raises:
        ValueError: 템플릿이 없는 인물 슬롯이나 필드를 참조하는 경우
    """
    actors: dict[str, Person] = {
        f"person{index}": person for index, person in enumerate(people)
    }

    rendered: list[str] = []
    spans: list[Span] = []
    offset = 0
    emitted_repeat_keys: set[str] = set()

    for line in template.lines:
        if line.repeat == "person":
            # repeat 줄은 인물마다 한 번씩, "person" 별칭으로 낸다.
            for person in people:
                scoped = dict(actors)
                scoped["person"] = person
                if not _line_is_renderable(line, scoped):
                    continue
                if person.person_id in emitted_repeat_keys:
                    continue
                emitted_repeat_keys.add(person.person_id)
                text, line_spans = _render_line(line.text, scoped, doc_ctx, offset)
                rendered.append(text)
                spans.extend(line_spans)
                offset += len(text) + 1  # 줄바꿈 한 글자
            continue

        if not _line_is_renderable(line, actors):
            continue
        text, line_spans = _render_line(line.text, actors, doc_ctx, offset)
        rendered.append(text)
        spans.extend(line_spans)
        offset += len(text) + 1

    body = "\n".join(rendered)
    return Document(
        doc_id=doc_id,
        genre=template.genre,
        template_id=template.id,
        text=body,
        spans=tuple(spans),
        person_ids=tuple(p.person_id for p in people),
    )


def generate_documents(
    population: Population,
    templates: list[DocumentTemplate],
    count: int,
    genre_weights: dict[str, float],
    seed: int,
) -> list[Document]:
    """코퍼스를 생성합니다.

    Args:
        population: 인물 풀
        templates: 사용할 템플릿 목록
        count: 생성할 문서 수
        genre_weights: 장르별 가중치
        seed: 난수 시드

    Returns:
        생성된 문서 목록

    Raises:
        ValueError: 가중치가 걸린 장르의 템플릿이 하나도 없는 경우
    """
    usable = [t for t in templates if genre_weights.get(t.genre, 0.0) > 0.0]
    if not usable:
        raise ValueError("가중치가 0보다 큰 장르에 해당하는 템플릿이 없습니다.")

    weights = [genre_weights[t.genre] for t in usable]
    rng = random.Random(seed)
    documents: list[Document] = []

    for index in range(count):
        template = rng.choices(usable, weights=weights, k=1)[0]
        low, high = template.persons
        actor_count = min(rng.randint(low, high), len(population.people))
        actors = rng.sample(population.people, actor_count)
        doc_ctx = {
            "date": f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "serial": f"{rng.randint(0, 9999):04d}",
        }
        documents.append(
            render_document(f"doc_{index:06d}", template, actors, doc_ctx)
        )

    return documents
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/synth/test_document.py -v`
Expected: PASS (8 passed)

만약 `test_repeat_emits_one_line_per_person`이 실패하면 `emitted_repeat_keys` 로직을 확인한다. 이 집합은 **한 문서 안에서 같은 인물이 repeat 줄을 두 번 받지 않게** 하려는 것이며, 서로 다른 repeat 줄(닉네임 있는 줄 / 없는 줄)이 같은 인물에게 중복 적용되는 것을 막는 장치다.

- [ ] **Step 6: 커밋한다**

```bash
python -m ruff check kopii tests && python -m ruff format kopii tests
git add kopii/synth/document.py kopii/synth/templates tests/synth/test_document.py
git commit -m "feat(synth): 템플릿 렌더링과 span 오프셋 기록 (Stage 2)

- 치환 시점에 오프셋을 기록해 같은 값이 반복돼도 정확한 위치를 잡는다
- requires로 닉네임 없는 인물의 줄을 건너뛴다
- 결재 문서 템플릿에 앵커 없는 7자리 숫자를 넣어 오탐 시험대를 만든다"
```

---

### Task 5: 표기 흔들림과 오프셋 재계산

**Files:**
- Create: `kopii/synth/perturb.py`
- Test: `tests/synth/test_perturb.py`

**Interfaces:**
- Consumes: `kopii.span.Span`, `kopii.synth.document.Document`
- Produces:
  - `kopii.synth.perturb.Edit(start: int, end: int, text: str)` — frozen dataclass
  - `kopii.synth.perturb.apply_edits(text: str, spans: Sequence[Span], edits: Sequence[Edit]) -> tuple[str, list[Span]]`
  - `kopii.synth.perturb.PerturbRates(honorific_variation: float, partial_name: float, separator_variation: float, line_break_split: float, typo: float, space_insertion: float)` — frozen dataclass
  - `kopii.synth.perturb.perturb_document(doc: Document, rates: PerturbRates, rng: random.Random) -> Document`

**이 태스크가 회귀 위험 1순위다.** 편집이 span 안쪽을 건드리면 경계가 밀린다. `apply_edits`가 그 재계산을 한곳에서 책임지고, 부분 겹침은 예외로 잡아 조용한 손상을 막는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/synth/test_perturb.py`:

```python
"""표기 흔들림과 span 오프셋 재계산 테스트."""

import random

import pytest

from kopii.span import Span
from kopii.synth.document import generate_documents, load_templates
from kopii.synth.perturb import Edit, PerturbRates, apply_edits, perturb_document
from kopii.synth.population import generate_population

_NO_PERTURB = PerturbRates(
    honorific_variation=0.0,
    partial_name=0.0,
    separator_variation=0.0,
    line_break_split=0.0,
    typo=0.0,
    space_insertion=0.0,
)
_ALWAYS = PerturbRates(
    honorific_variation=1.0,
    partial_name=1.0,
    separator_variation=1.0,
    line_break_split=1.0,
    typo=1.0,
    space_insertion=1.0,
)


def test_edit_before_span_shifts_offsets() -> None:
    """span 앞쪽 편집은 오프셋만 민다."""
    text = "안녕 김민수님"
    spans = [Span(start=3, end=6, type="NAME", surface="김민수")]
    new_text, new_spans = apply_edits(text, spans, [Edit(start=0, end=2, text="반갑다")])

    assert new_text == "반갑다 김민수님"
    assert new_spans[0].verify(new_text)


def test_edit_inside_span_updates_surface() -> None:
    """span 안쪽 편집은 폭과 surface를 갱신한다."""
    text = "사번 2304118 확인"
    spans = [Span(start=3, end=10, type="EMPLOYEE_ID", surface="2304118")]
    new_text, new_spans = apply_edits(text, spans, [Edit(start=6, end=6, text="\n")])

    assert new_spans[0].surface == "230\n4118"
    assert new_spans[0].verify(new_text)


def test_space_insertion_keeps_phone_span_intact() -> None:
    """전화번호에 공백을 넣어도 span이 텍스트와 일치해야 한다."""
    pop = generate_population(size=5, seed=1)
    docs = generate_documents(
        pop, load_templates(), count=10, genre_weights={"issue_ticket": 1.0}, seed=3
    )
    rates = PerturbRates(
        honorific_variation=0.0,
        partial_name=0.0,
        separator_variation=0.0,
        line_break_split=0.0,
        typo=0.0,
        space_insertion=1.0,
    )
    rng = random.Random(5)
    for doc in docs:
        perturbed = perturb_document(doc, rates, rng)
        for span in perturbed.spans:
            assert span.verify(perturbed.text)
            if span.type == "PHONE":
                assert " - " in span.surface


def test_edit_replacing_whole_span_updates_surface() -> None:
    """span 전체를 바꾸면 새 surface가 반영된다."""
    text = "담당 김민수 확인"
    spans = [Span(start=3, end=6, type="NAME", surface="김민수")]
    new_text, new_spans = apply_edits(text, spans, [Edit(start=3, end=6, text="김")])

    assert new_text == "담당 김 확인"
    assert new_spans[0].surface == "김"
    assert new_spans[0].verify(new_text)


def test_partial_overlap_is_rejected() -> None:
    """span 경계를 반만 덮는 편집은 조용히 넘기지 않고 실패시킨다."""
    text = "담당 김민수 확인"
    spans = [Span(start=3, end=6, type="NAME", surface="김민수")]
    with pytest.raises(ValueError, match="부분적으로"):
        apply_edits(text, spans, [Edit(start=2, end=5, text="X")])


def test_overlapping_edits_are_rejected() -> None:
    """편집끼리 겹치면 실패시킨다."""
    text = "abcdef"
    with pytest.raises(ValueError, match="겹칩니다"):
        apply_edits(text, [], [Edit(start=0, end=3, text="X"), Edit(start=2, end=4, text="Y")])


def test_zero_rates_leave_document_unchanged() -> None:
    """확률이 0이면 문서가 그대로여야 한다."""
    pop = generate_population(size=20, seed=1)
    docs = generate_documents(
        pop, load_templates(), count=10, genre_weights={"meeting_note": 1.0}, seed=3
    )
    for doc in docs:
        assert perturb_document(doc, _NO_PERTURB, random.Random(0)) == doc


def test_all_spans_survive_full_perturbation() -> None:
    """모든 흔들림을 켜도 span이 텍스트와 일치해야 한다."""
    pop = generate_population(size=30, seed=1)
    weights = dict.fromkeys(
        ("meeting_note", "email", "hr_notice", "approval_doc", "chat_log", "issue_ticket"),
        1.0,
    )
    docs = generate_documents(pop, load_templates(), count=60, genre_weights=weights, seed=4)

    rng = random.Random(11)
    for doc in docs:
        perturbed = perturb_document(doc, _ALWAYS, rng)
        for span in perturbed.spans:
            assert span.verify(perturbed.text), f"{perturbed.doc_id}: {span}"


def test_perturbation_is_reproducible() -> None:
    """같은 시드면 같은 흔들림 결과가 나와야 한다."""
    pop = generate_population(size=20, seed=1)
    docs = generate_documents(
        pop, load_templates(), count=5, genre_weights={"chat_log": 1.0}, seed=3
    )
    first = [perturb_document(d, _ALWAYS, random.Random(2)) for d in docs]
    second = [perturb_document(d, _ALWAYS, random.Random(2)) for d in docs]
    assert first == second
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/synth/test_perturb.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kopii.synth.perturb'`

- [ ] **Step 3: perturb를 구현한다**

`kopii/synth/perturb.py`:

```python
"""표기 흔들림 주입과 span 오프셋 재계산."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, replace

from kopii.span import Span
from kopii.synth.document import Document

_HONORIFICS: tuple[str, ...] = ("님", "씨", "", " 선임", " 책임", " 프로")
_SEPARATORS: tuple[str, ...] = (" · ", " / ", " | ", "\t", ", ", " ")
_TYPO_POOL: str = "가나다라마바사아자차카타파하"


@dataclass(frozen=True, slots=True)
class Edit:
    """텍스트 편집 한 건.

    Args:
        start: 시작 오프셋 (포함)
        end: 끝 오프셋 (제외). start와 같으면 삽입
        text: 대체할 문자열
    """

    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class PerturbRates:
    """흔들림별 적용 확률.

    Args:
        honorific_variation: 호칭 접미사 변형 확률
        partial_name: 이름을 성만 남길 확률
        separator_variation: 구분자 변형 확률
        line_break_split: 사번 중간에 줄바꿈을 끼울 확률
        typo: 이름에 오타를 낼 확률
        space_insertion: 전화번호 하이픈 주위에 공백을 넣을 확률
    """

    honorific_variation: float
    partial_name: float
    separator_variation: float
    line_break_split: float
    typo: float
    space_insertion: float


def apply_edits(
    text: str, spans: Sequence[Span], edits: Sequence[Edit]
) -> tuple[str, list[Span]]:
    """편집을 적용하고 span 오프셋을 재계산합니다.

    편집은 세 가지만 허용한다 — span 바깥, span 안쪽, span 전체 치환.
    span 경계를 반만 덮는 편집은 정답 라벨을 조용히 망가뜨리므로 거부한다.

    Args:
        text: 원본 텍스트
        spans: 원본 span 목록
        edits: 적용할 편집 목록

    Returns:
        (편집된 텍스트, 재계산된 span 목록). 폭이 0이 된 span은 빠진다

    Raises:
        ValueError: 편집끼리 겹치거나 span 경계를 부분적으로 침범하는 경우
    """
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current.start < previous.end:
            raise ValueError(
                f"편집이 서로 겹칩니다: {previous} 와 {current}"
            )

    for edit in ordered:
        for span in spans:
            crosses_start = edit.start < span.start < edit.end
            crosses_end = edit.start < span.end < edit.end
            inside = span.start <= edit.start and edit.end <= span.end
            if (crosses_start or crosses_end) and not inside:
                raise ValueError(
                    f"편집이 span 경계를 부분적으로 침범합니다: {edit} / {span}"
                )

    # 텍스트를 뒤에서부터 고쳐 앞쪽 오프셋이 흔들리지 않게 한다.
    chunks: list[str] = []
    cursor = 0
    for edit in ordered:
        chunks.append(text[cursor : edit.start])
        chunks.append(edit.text)
        cursor = edit.end
    chunks.append(text[cursor:])
    new_text = "".join(chunks)

    new_spans: list[Span] = []
    for span in spans:
        start = span.start
        end = span.end
        for edit in ordered:
            delta = len(edit.text) - (edit.end - edit.start)
            if edit.end <= span.start:
                start += delta
                end += delta
            elif span.start <= edit.start and edit.end <= span.end:
                end += delta
        if end <= start:
            continue
        new_spans.append(
            replace(span, start=start, end=end, surface=new_text[start:end])
        )

    return new_text, new_spans


def _honorific_edits(doc: Document, rate: float, rng: random.Random) -> list[Edit]:
    """이름 뒤의 '님'을 다른 호칭으로 바꾸는 편집을 만듭니다."""
    edits: list[Edit] = []
    for span in doc.spans:
        if span.type != "NAME" or rng.random() >= rate:
            continue
        if doc.text[span.end : span.end + 1] == "님":
            edits.append(Edit(start=span.end, end=span.end + 1, text=rng.choice(_HONORIFICS)))
    return edits


def _partial_name_edits(doc: Document, rate: float, rng: random.Random) -> list[Edit]:
    """이름을 성 한 글자만 남기는 편집을 만듭니다."""
    return [
        Edit(start=span.start, end=span.end, text=span.surface[0])
        for span in doc.spans
        if span.type == "NAME" and len(span.surface) > 1 and rng.random() < rate
    ]


def _separator_edits(doc: Document, rate: float, rng: random.Random) -> list[Edit]:
    """' · ' 구분자를 다른 표기로 바꾸는 편집을 만듭니다."""
    edits: list[Edit] = []
    start = doc.text.find(" · ")
    while start != -1:
        if rng.random() < rate:
            edits.append(Edit(start=start, end=start + 3, text=rng.choice(_SEPARATORS)))
        start = doc.text.find(" · ", start + 3)
    return edits


def _line_break_edits(doc: Document, rate: float, rng: random.Random) -> list[Edit]:
    """사번 중간에 줄바꿈을 끼우는 편집을 만듭니다."""
    edits: list[Edit] = []
    for span in doc.spans:
        if span.type != "EMPLOYEE_ID" or len(span.surface) < 3:
            continue
        if rng.random() >= rate:
            continue
        cut = span.start + rng.randint(1, len(span.surface) - 1)
        edits.append(Edit(start=cut, end=cut, text="\n"))
    return edits


def _typo_edits(doc: Document, rate: float, rng: random.Random) -> list[Edit]:
    """이름 한 글자를 다른 음절로 바꾸는 편집을 만듭니다."""
    edits: list[Edit] = []
    for span in doc.spans:
        if span.type != "NAME" or rng.random() >= rate:
            continue
        offset = rng.randrange(len(span.surface))
        position = span.start + offset
        edits.append(Edit(start=position, end=position + 1, text=rng.choice(_TYPO_POOL)))
    return edits


def _space_insertion_edits(doc: Document, rate: float, rng: random.Random) -> list[Edit]:
    """전화번호 하이픈 주위에 공백을 넣는 편집을 만듭니다.

    "010-0000-0000"이 "010 - 0000 - 0000"처럼 쓰이는 실제 표기를 재현한다.
    (문서의 예시는 자리표시 값을 쓴다 — scripts/pii_scan.py가 그럴듯한 번호를 반려한다.)
    span 안쪽 편집이므로 폭과 surface가 함께 갱신된다.
    """
    edits: list[Edit] = []
    for span in doc.spans:
        if span.type != "PHONE" or rng.random() >= rate:
            continue
        for offset, char in enumerate(span.surface):
            if char == "-":
                position = span.start + offset
                edits.append(Edit(start=position, end=position + 1, text=" - "))
    return edits


def _drop_conflicts(edits: list[Edit]) -> list[Edit]:
    """겹치는 편집 중 앞선 것만 남깁니다.

    서로 다른 흔들림이 같은 구간을 노릴 수 있다. 우선순위를 두기보다
    먼저 생성된 것을 남기고 뒤엣것을 버린다 — 어느 쪽을 남겨도 흔들림의
    목적은 달성되고, 결정적으로 동작한다.

    Args:
        edits: 후보 편집 목록

    Returns:
        서로 겹치지 않는 편집 목록
    """
    kept: list[Edit] = []
    for edit in sorted(edits, key=lambda e: (e.start, e.end)):
        if kept and edit.start < kept[-1].end:
            continue
        kept.append(edit)
    return kept


def perturb_document(
    doc: Document, rates: PerturbRates, rng: random.Random
) -> Document:
    """문서에 표기 흔들림을 넣고 span을 재계산합니다.

    Args:
        doc: 원본 문서
        rates: 흔들림별 확률
        rng: 난수 생성기

    Returns:
        흔들림이 적용된 새 Document
    """
    candidates: list[Edit] = []
    candidates += _honorific_edits(doc, rates.honorific_variation, rng)
    candidates += _partial_name_edits(doc, rates.partial_name, rng)
    candidates += _separator_edits(doc, rates.separator_variation, rng)
    candidates += _line_break_edits(doc, rates.line_break_split, rng)
    candidates += _typo_edits(doc, rates.typo, rng)
    candidates += _space_insertion_edits(doc, rates.space_insertion, rng)

    edits = _drop_conflicts(candidates)
    if not edits:
        return doc

    new_text, new_spans = apply_edits(doc.text, doc.spans, edits)
    return Document(
        doc_id=doc.doc_id,
        genre=doc.genre,
        template_id=doc.template_id,
        text=new_text,
        spans=tuple(new_spans),
        person_ids=doc.person_ids,
    )
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/synth/test_perturb.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋한다**

```bash
python -m ruff check kopii tests && python -m ruff format kopii tests
git add kopii/synth/perturb.py tests/synth/test_perturb.py
git commit -m "feat(synth): 표기 흔들림 주입과 span 오프셋 재계산

apply_edits가 오프셋 재계산을 한곳에서 책임지고, span 경계를
부분적으로 침범하는 편집은 예외로 잡아 조용한 라벨 손상을 막는다."
```

---

### Task 6: 설정 스키마와 생성 CLI

**Files:**
- Create: `kopii/config/__init__.py`
- Create: `kopii/config/schema.py`
- Create: `kopii/synth/cli.py`
- Create: `kopii/synth/__main__.py`
- Create: `configs/synth.yaml`
- Test: `tests/test_config_schema.py`, `tests/synth/test_cli.py`

**Interfaces:**
- Consumes: 앞선 모든 태스크
- Produces:
  - `kopii.config.schema.PopulationConfig`, `PerturbConfig`, `CorpusConfig`, `SynthConfig` — pydantic 모델
  - `kopii.config.schema.load_synth_config(path: Path) -> SynthConfig`
  - `kopii.synth.cli.run(config: SynthConfig, output_dir: Path) -> dict[str, int]`
  - `kopii.synth.cli.main(argv: list[str] | None = None) -> int`
  - 산출 파일: `population.jsonl`, `corpus.jsonl`, `manifest.json`

- [ ] **Step 1: 설정 스키마 테스트를 쓴다**

`tests/test_config_schema.py`:

```python
"""합성 설정 스키마 테스트."""

import pytest
from pydantic import ValidationError

from kopii.config.schema import CorpusConfig, PerturbConfig, PopulationConfig


def test_defaults_are_valid() -> None:
    """기본값만으로 설정이 성립해야 한다."""
    assert PopulationConfig().size > 0
    assert CorpusConfig().size > 0


def test_rejects_out_of_range_probability() -> None:
    """확률은 0~1을 벗어날 수 없다."""
    with pytest.raises(ValidationError):
        PerturbConfig(typo=1.5)


def test_rejects_all_zero_genre_weights() -> None:
    """장르 가중치가 전부 0이면 문서를 만들 수 없다."""
    with pytest.raises(ValidationError, match="가중치"):
        CorpusConfig(genres={"email": 0.0})


def test_rejects_non_positive_size() -> None:
    """인원 수는 1 이상이어야 한다."""
    with pytest.raises(ValidationError):
        PopulationConfig(size=0)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_config_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kopii.config'`

- [ ] **Step 3: 설정 스키마를 구현한다**

`kopii/config/__init__.py`:

```python
"""KoPII 설정 스키마."""
```

`kopii/config/schema.py`:

```python
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
```

- [ ] **Step 4: 설정 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_config_schema.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: CLI 테스트를 쓴다**

`tests/synth/test_cli.py`:

```python
"""합성 생성 CLI 테스트."""

import json
from pathlib import Path

from kopii.config.schema import CorpusConfig, PopulationConfig, SynthConfig
from kopii.span import Span
from kopii.synth.cli import run


def _small_config() -> SynthConfig:
    """테스트용 소형 설정."""
    return SynthConfig(
        population=PopulationConfig(size=30, seed=1, divisions=2),
        corpus=CorpusConfig(size=25, seed=2),
    )


def test_run_writes_all_artifacts(tmp_path: Path) -> None:
    """population·corpus·manifest 세 파일을 낸다."""
    counts = run(_small_config(), tmp_path)

    assert (tmp_path / "population.jsonl").exists()
    assert (tmp_path / "corpus.jsonl").exists()
    assert (tmp_path / "manifest.json").exists()
    assert counts == {"people": 30, "documents": 25}


def test_corpus_records_have_expected_shape(tmp_path: Path) -> None:
    """코퍼스 레코드가 설계 §9.5 포맷을 따른다."""
    run(_small_config(), tmp_path)
    lines = (tmp_path / "corpus.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])

    assert set(record) == {"id", "genre", "text", "spans", "meta"}
    assert set(record["meta"]) == {"person_ids", "template"}
    for span in record["spans"]:
        assert set(span) == {"start", "end", "type", "surface", "entity_key"}


def test_written_spans_match_written_text(tmp_path: Path) -> None:
    """파일로 나간 뒤에도 span 오프셋이 본문과 맞아야 한다."""
    run(_small_config(), tmp_path)
    for line in (tmp_path / "corpus.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        for raw in record["spans"]:
            span = Span(**raw)
            assert span.verify(record["text"]), record["id"]


def test_manifest_carries_id_scheme_ground_truth(tmp_path: Path) -> None:
    """manifest가 추론기 채점용 정답 메타를 담아야 한다."""
    run(_small_config(), tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["id_scheme"]["scheme"] == "sequential_block"
    assert manifest["id_scheme"]["structural_digits"]["FULLTIME"] == 2
    assert manifest["counts"] == {"people": 30, "documents": 25}


def test_same_seed_produces_identical_bytes(tmp_path: Path) -> None:
    """같은 시드면 산출 파일이 바이트 단위로 같아야 한다."""
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    run(_small_config(), first_dir)
    run(_small_config(), second_dir)

    for name in ("population.jsonl", "corpus.jsonl", "manifest.json"):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes()
```

- [ ] **Step 6: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/synth/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kopii.synth.cli'`

- [ ] **Step 7: CLI를 구현한다**

`kopii/synth/cli.py`:

```python
"""합성 코퍼스 생성 CLI."""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict
from pathlib import Path

from kopii import __version__
from kopii.config.schema import SynthConfig, load_synth_config
from kopii.synth.document import Document, generate_documents, load_templates
from kopii.synth.perturb import PerturbRates, perturb_document
from kopii.synth.population import Population, generate_population


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """JSONL을 결정적으로 씁니다.

    Args:
        path: 출력 경로
        records: 레코드 목록
    """
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _document_record(doc: Document) -> dict[str, object]:
    """문서를 설계 §9.5 포맷의 레코드로 바꿉니다.

    Args:
        doc: 대상 문서

    Returns:
        JSONL 한 줄에 해당하는 딕셔너리
    """
    return {
        "id": doc.doc_id,
        "genre": doc.genre,
        "text": doc.text,
        "spans": [
            {
                "start": span.start,
                "end": span.end,
                "type": span.type,
                "surface": span.surface,
                "entity_key": span.entity_key,
            }
            for span in doc.spans
        ],
        "meta": {
            "person_ids": list(doc.person_ids),
            "template": doc.template_id,
        },
    }


def run(config: SynthConfig, output_dir: Path) -> dict[str, int]:
    """설정대로 코퍼스를 생성해 파일로 씁니다.

    Args:
        config: 합성 설정
        output_dir: 산출물 디렉터리 (없으면 만든다)

    Returns:
        {"people": 인원 수, "documents": 문서 수}
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    population: Population = generate_population(
        size=config.population.size,
        seed=config.population.seed,
        scheme_name=config.population.id_scheme,
        divisions=config.population.divisions,
        teams_per_division=config.population.teams_per_division,
        nickname_ratio=config.population.nickname_ratio,
    )

    documents = generate_documents(
        population=population,
        templates=load_templates(),
        count=config.corpus.size,
        genre_weights=config.corpus.genres,
        seed=config.corpus.seed,
    )

    rates = PerturbRates(**config.corpus.perturb.model_dump())
    rng = random.Random(config.corpus.seed + 1)
    documents = [perturb_document(doc, rates, rng) for doc in documents]

    _write_jsonl(
        output_dir / "population.jsonl",
        [asdict(person) for person in population.people],
    )
    _write_jsonl(
        output_dir / "corpus.jsonl",
        [_document_record(doc) for doc in documents],
    )

    manifest = {
        "kopii_version": __version__,
        "config": config.model_dump(),
        "counts": {"people": len(population.people), "documents": len(documents)},
        "id_scheme": asdict(population.id_scheme),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    return {"people": len(population.people), "documents": len(documents)}


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점입니다.

    Args:
        argv: 명령행 인자. None이면 sys.argv를 쓴다

    Returns:
        종료 코드 (0 = 성공)
    """
    parser = argparse.ArgumentParser(
        prog="python -m kopii.synth",
        description="한국어 PII 합성 코퍼스를 생성합니다.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="설정 YAML 경로 (생략 시 기본값으로 생성)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="산출물 디렉터리 (설정의 output_dir을 덮어쓴다)",
    )
    args = parser.parse_args(argv)

    config = load_synth_config(args.config) if args.config else SynthConfig()
    output_dir = args.out or Path(config.output_dir)

    counts = run(config, output_dir)
    print(
        f"생성 완료 — 구성원 {counts['people']}명, 문서 {counts['documents']}건 "
        f"→ {output_dir}"
    )
    return 0
```

`kopii/synth/__main__.py`:

```python
"""python -m kopii.synth 진입점."""

from kopii.synth.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

`configs/synth.yaml`:

```yaml
# 합성 코퍼스 생성 기본 설정.
# 실행: python -m kopii.synth --config configs/synth.yaml
#
# 산출물은 data/ 아래에 생성되며 gitignore 된다. 같은 시드면 언제든
# 같은 코퍼스가 재현되므로 파일을 공유할 필요가 없다.

population:
  size: 2000
  seed: 42
  id_scheme: sequential_block   # 또는 org_coded
  divisions: 5
  teams_per_division: [3, 8]
  nickname_ratio: 0.5

corpus:
  size: 20000
  seed: 42
  genres:
    meeting_note: 0.25
    email: 0.25
    hr_notice: 0.15
    approval_doc: 0.15
    chat_log: 0.10
    issue_ticket: 0.10
  perturb:
    honorific_variation: 0.3
    partial_name: 0.2
    separator_variation: 0.3
    line_break_split: 0.05
    typo: 0.02
    space_insertion: 0.10

output_dir: data
```

- [ ] **Step 8: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/ -v`
Expected: PASS (전체 통과)

- [ ] **Step 9: 실제로 한 번 돌려본다**

Run:
```bash
python -m kopii.synth --config configs/synth.yaml --out data/
head -c 600 data/corpus.jsonl
git status --short   # data/ 가 비어 있어야 한다 (gitignore 확인)
```
Expected: 생성 완료 메시지, `git status`에 `data/` 관련 항목이 없음

- [ ] **Step 10: 커밋한다**

```bash
python -m ruff check kopii tests && python -m ruff format kopii tests
git add kopii/config kopii/synth/cli.py kopii/synth/__main__.py configs/synth.yaml tests/
git commit -m "feat(synth): 설정 스키마와 생성 CLI

- python -m kopii.synth 로 population/corpus/manifest 생성
- manifest가 추론기 채점용 채번 정답 메타를 실어 나른다
- 같은 시드면 산출 파일이 바이트 단위로 동일"
```

---

### Task 7: 생성물 검증 명령과 사용법 문서

**Files:**
- Create: `kopii/synth/validate.py`
- Modify: `README.md` (「현재 상태」 절 아래에 사용법 추가)
- Test: `tests/synth/test_validate.py`

**Interfaces:**
- Consumes: Task 6의 산출 파일 3종
- Produces:
  - `kopii.synth.validate.ValidationReport(checks: dict[str, bool], errors: list[str])` — frozen dataclass, `ok` 프로퍼티
  - `kopii.synth.validate.validate_corpus(directory: Path) -> ValidationReport`
  - `kopii.synth.validate.main(argv: list[str] | None = None) -> int`

**왜 별도 명령인가:** 설계 §9.8은 "생성기가 틀리면 그 위의 모든 측정이 조용히 틀린다"고 못 박았다. pytest는 개발자만 돌리지만, 이 명령은 **코퍼스를 받은 사람이 그 코퍼스를 신뢰할 수 있는지** 확인하는 수단이다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/synth/test_validate.py`:

```python
"""생성물 검증 명령 테스트."""

import json
from pathlib import Path

from kopii.config.schema import CorpusConfig, PopulationConfig, SynthConfig
from kopii.synth.cli import run
from kopii.synth.validate import validate_corpus


def _generate(directory: Path) -> None:
    """검증 대상 코퍼스를 만든다."""
    config = SynthConfig(
        population=PopulationConfig(size=25, seed=1, divisions=2),
        corpus=CorpusConfig(size=20, seed=2),
    )
    run(config, directory)


def test_healthy_corpus_passes(tmp_path: Path) -> None:
    """정상 생성물은 모든 검사를 통과해야 한다."""
    _generate(tmp_path)
    report = validate_corpus(tmp_path)
    assert report.ok, report.errors
    assert report.checks["span_roundtrip"] is True
    assert report.checks["employee_id_unique"] is True
    assert report.checks["rrn_checksum"] is True
    assert report.checks["entity_key_resolvable"] is True


def test_detects_broken_span_offset(tmp_path: Path) -> None:
    """오프셋이 밀린 코퍼스를 잡아내야 한다."""
    _generate(tmp_path)
    corpus = tmp_path / "corpus.jsonl"
    lines = corpus.read_text(encoding="utf-8").splitlines()

    damaged = json.loads(lines[0])
    damaged["text"] = "머리말 " + damaged["text"]  # span만 그대로 두어 오프셋을 민다
    lines[0] = json.dumps(damaged, ensure_ascii=False, sort_keys=True)
    corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_corpus(tmp_path)
    assert report.ok is False
    assert report.checks["span_roundtrip"] is False


def test_detects_unknown_entity_key(tmp_path: Path) -> None:
    """인구에 없는 entity_key를 잡아내야 한다."""
    _generate(tmp_path)
    corpus = tmp_path / "corpus.jsonl"
    lines = corpus.read_text(encoding="utf-8").splitlines()

    damaged = json.loads(lines[0])
    if damaged["spans"]:
        damaged["spans"][0]["entity_key"] = "p_99999"
        lines[0] = json.dumps(damaged, ensure_ascii=False, sort_keys=True)
        corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")

        report = validate_corpus(tmp_path)
        assert report.ok is False
        assert report.checks["entity_key_resolvable"] is False
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/synth/test_validate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kopii.synth.validate'`

- [ ] **Step 3: 검증 명령을 구현한다**

`kopii/synth/validate.py`:

```python
"""생성된 합성 코퍼스를 검증하는 CLI."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

_RRN_WEIGHTS: tuple[int, ...] = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
_MAX_REPORTED_ERRORS = 20


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """검증 결과.

    Args:
        checks: 검사 이름 → 통과 여부
        errors: 사람이 읽을 수 있는 실패 설명 (상한을 둔다)
    """

    checks: dict[str, bool]
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """모든 검사를 통과했는지."""
        return all(self.checks.values())


def _rrn_checksum_valid(rrn: str) -> bool:
    """주민등록번호 체크섬을 검증합니다.

    Args:
        rrn: "YYMMDD-XXXXXXX" 형태 문자열

    Returns:
        체크섬이 맞으면 True
    """
    digits = rrn.replace("-", "")
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(digits[:12], _RRN_WEIGHTS, strict=True))
    return (11 - total % 11) % 10 == int(digits[12])


def validate_corpus(directory: Path) -> ValidationReport:
    """생성물 3종을 읽어 무결성을 검사합니다.

    설계 §9.8의 검증 항목을 코퍼스 소비자가 직접 돌릴 수 있게 옮긴 것이다.

    Args:
        directory: population.jsonl / corpus.jsonl / manifest.json 이 있는 디렉터리

    Returns:
        검사별 통과 여부와 실패 설명

    Raises:
        FileNotFoundError: 필요한 파일이 없는 경우
    """
    population_path = directory / "population.jsonl"
    corpus_path = directory / "corpus.jsonl"
    manifest_path = directory / "manifest.json"
    for path in (population_path, corpus_path, manifest_path):
        if not path.exists():
            raise FileNotFoundError(f"생성물을 찾을 수 없습니다: {path}")

    people = [
        json.loads(line)
        for line in population_path.read_text(encoding="utf-8").splitlines()
    ]
    documents = [
        json.loads(line)
        for line in corpus_path.read_text(encoding="utf-8").splitlines()
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    errors: list[str] = []

    employee_ids = [p["employee_id"] for p in people]
    employee_id_unique = len(set(employee_ids)) == len(employee_ids)
    if not employee_id_unique:
        errors.append(f"사번이 중복됐습니다: {len(employee_ids) - len(set(employee_ids))}건")

    rrn_ok = True
    for person in people:
        if not _rrn_checksum_valid(person["rrn"]):
            rrn_ok = False
            if len(errors) < _MAX_REPORTED_ERRORS:
                errors.append(f"{person['person_id']}: 주민번호 체크섬 불일치")

    known_keys = {p["person_id"] for p in people}
    span_roundtrip = True
    entity_key_resolvable = True
    for document in documents:
        text = document["text"]
        for span in document["spans"]:
            if text[span["start"] : span["end"]] != span["surface"]:
                span_roundtrip = False
                if len(errors) < _MAX_REPORTED_ERRORS:
                    errors.append(
                        f"{document['id']}: span 오프셋 불일치 "
                        f"({span['start']}, {span['end']}, {span['type']})"
                    )
            if span["entity_key"] is not None and span["entity_key"] not in known_keys:
                entity_key_resolvable = False
                if len(errors) < _MAX_REPORTED_ERRORS:
                    errors.append(
                        f"{document['id']}: 인구에 없는 entity_key {span['entity_key']}"
                    )

    counts_match = (
        manifest["counts"]["people"] == len(people)
        and manifest["counts"]["documents"] == len(documents)
    )
    if not counts_match:
        errors.append("manifest의 개수가 실제 파일과 다릅니다.")

    return ValidationReport(
        checks={
            "employee_id_unique": employee_id_unique,
            "rrn_checksum": rrn_ok,
            "span_roundtrip": span_roundtrip,
            "entity_key_resolvable": entity_key_resolvable,
            "manifest_counts_match": counts_match,
        },
        errors=errors,
    )


def main(argv: list[str] | None = None) -> int:
    """검증 CLI 진입점입니다.

    Args:
        argv: 명령행 인자

    Returns:
        종료 코드 (0 = 모든 검사 통과)
    """
    parser = argparse.ArgumentParser(
        prog="python -m kopii.synth.validate",
        description="생성된 합성 코퍼스의 무결성을 검사합니다.",
    )
    parser.add_argument("--dir", type=Path, default=Path("data"), help="생성물 디렉터리")
    args = parser.parse_args(argv)

    report = validate_corpus(args.dir)
    for name, passed in sorted(report.checks.items()):
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    for message in report.errors:
        print(f"  - {message}")

    if not report.ok:
        print("\n코퍼스가 손상됐습니다. 이 코퍼스로 측정한 값은 신뢰할 수 없습니다.")
        return 1
    print("\n모든 검사를 통과했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/synth/test_validate.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: README에 사용법을 추가한다**

`README.md`의 「현재 상태」 절 바로 아래, 「구현 순서」 표 앞에 다음을 삽입한다.
(아래 블록은 4중 백틱으로 감싸 안쪽 코드펜스를 그대로 보여준다 — README에는 안쪽 내용만 넣는다.)

````markdown
### 지금 돌려볼 수 있는 것

합성 코퍼스 생성기가 동작합니다. 외부 데이터도 네트워크도 필요 없습니다.

```bash
pip install -e ".[dev]"

# 가상 조직 2,000명 + 문서 20,000건 생성 (data/ 아래, gitignore됨)
python -m kopii.synth --config configs/synth.yaml

# 생성물 무결성 검사
python -m kopii.synth.validate --dir data/
```

산출물은 세 개입니다.

| 파일 | 내용 |
|---|---|
| `population.jsonl` | 구성원 — 이름·닉네임·사번·소속·직급·연락처 |
| `corpus.jsonl` | 문서 — 본문과 정답 PII span (`entity_key` 포함) |
| `manifest.json` | 시드·설정·개수, 그리고 사번 채번의 **정답 메타데이터** |

`manifest.json`의 채번 정답은 나중에 ID 스키마 추론기를 채점하는 데 쓰입니다.
시드가 같으면 언제든 같은 코퍼스가 재현되므로 파일을 공유할 필요가 없습니다.
````

- [ ] **Step 6: 전체 검증을 돌린다**

Run:
```bash
python -m pytest tests/ -v
python -m ruff check kopii tests
python -m ruff format --check kopii tests
python -m kopii.synth --config configs/synth.yaml --out data/
python -m kopii.synth.validate --dir data/
python scripts/pii_scan.py kopii tests configs docs scripts README.md
```
Expected: 전체 테스트 통과, ruff 통과, 검증 전 항목 PASS, pii_scan 통과

> `pii_scan`에 `data/`를 넘기지 않는 것이 의도적이다. 합성 주민번호는 체크섬이 유효하므로 스캐너가 잡는 것이 정상이며, `data/`는 커밋되지 않으므로 검사 대상이 아니다.

- [ ] **Step 7: 커밋한다**

```bash
git add kopii/synth/validate.py tests/synth/test_validate.py README.md
git commit -m "feat(synth): 생성물 검증 명령과 사용법 문서

코퍼스를 받은 사람이 그 코퍼스를 신뢰할 수 있는지 직접 확인할 수 있게
span 라운드트립·사번 유일성·주민번호 체크섬·entity_key 해석 가능성을 검사한다."
```

---

## 이 계획이 다루지 않는 것

설계 §9 중 다음은 의도적으로 뺐다.

- **`inject.py` (기존 IR 데이터셋에 PII 주입)** — §8.3(b) 검색 품질 delta 측정에 쓰이며, IR 데이터셋과 평가 코드가 있어야 의미가 있다. evaluation 계획으로 미룬다.
- **`IdSchemaInducer` 채점** — 추론기가 `detect/`에 생기는 다음 계획의 몫이다. 이 계획은 채점에 필요한 **정답을 `manifest.json`에 실어 두는 데까지**만 책임진다.
- **LLM을 이용한 템플릿 오프라인 확장** (§9.9) — 템플릿 6종으로 시작하고, uniformity 지표가 실제로 템플릿 때문에 나빠지는 것이 관측되면 그때 착수한다.

## 다음 계획

`detect/` — 규칙 기반 탐지기와 `IdSchemaInducer` 최소 버전. 이 계획의 `manifest.json`이 그 추론기의 채점표가 되고, `corpus.jsonl`의 정답 span이 `leak_rate`의 분모가 된다.
