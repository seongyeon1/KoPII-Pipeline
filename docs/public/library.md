# KoPII 라이브러리 사용과 확장

버전 0.1.0은 한국어 텍스트의 탐지·범주화와 연구 실행을 위한 로컬 Python 패키지입니다. Python 3.11 이상을 사용합니다. 웹 서버, 문서 파서, 실제 조직 DB, 검색 엔진은 포함하지 않습니다.

## 설치와 첫 실행

저장소를 내려받은 디렉터리에서 실행합니다. PyPI에 배포한 패키지라는 의미는 아닙니다.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
kopii process --config configs/demo.json --input examples/document.txt --document-id demo-1
```

기본 설치에는 외부 런타임 의존성이 없습니다. 데모는 **가상 조직 CSV와 사전 이름 탐지기**를 사용합니다. 실제 문서의 이름을 이해하는 모델이 아니며 정확도 벤치마크로 사용하지 않습니다. CSV에 이름이 있더라도 탐지 결과에 없는 이름은 조회하지 않습니다.

`김하늘이`는 `[PERSON_NAME:플랫폼개발팀]이`로 바뀝니다. 서로 다른 팀에 존재하는 예제 이름은 `[PERSON_NAME]`으로 바뀝니다. 이메일은 `[EMAIL]`로 표시합니다. 결과에는 처리된 텍스트, 원문·출력의 치환 위치, 실제 적용 행동이 포함됩니다. `entities`는 입력 좌표계이며 원문 표면 문자열은 결과 메타데이터에 복제하지 않습니다. 미탐 개인정보가 결과 본문에 남을 수 있습니다.

## 한국어 모델 사용

```bash
python -m pip install -e '.[hf]'
kopii process --config configs/roberta.json --input examples/document.txt --document-id demo-1
```

첫 실행에는 고정 revision의 모델과 토크나이저 다운로드가 필요합니다. 기본 장치는 CPU입니다. JSON의 `device`를 사용 가능한 `mps` 또는 `cuda`로 바꿀 수 있습니다. 운영 서버 주소는 필요하지 않습니다. 완전히 오프라인으로 사용할 때는 모델을 먼저 캐시하고 `local_files_only: true`를 설정합니다.

GLiNER 후보 실험에는 `python -m pip install -e '.[hf,gliner]'`로 선택 의존성을 설치합니다. 해당 모델들은 라이선스와 언어·라벨 조건을 각각 확인해야 합니다. 선택 의존성은 import 시점에 로드하지 않습니다.

## Python API

```python
from pathlib import Path
from kopii import Pipeline, Policy
from kopii.detectors.rules import DictionaryDetector
from kopii.resolvers.csv import CsvResolver

pipeline = Pipeline(
    detector=DictionaryDetector(["김하늘"]),  # 데모 전용
    resolver=CsvResolver(Path("examples/organizations.csv"), level="division"),
    policy=Policy(actions={"PERSON_NAME": "organization"}),
)
result = pipeline.process("김하늘의 검토 결과입니다.", document_id="demo-1")
print(result.text)
```

## 구성 요소의 계약

| 구성 요소 | 입력 → 출력 | 중요한 조건 |
|---|---|---|
| Detector | 원문 → Entity 목록 | 정규화하지 않은 Python 문자열의 `[start, end)` 문자 위치 |
| Resolver | 이름 목록 → Resolution 매핑 | 소속 확인/미확인/모호/사용 불가를 구분 |
| Policy | 유형·표면·문서 ID·조회 결과 → 치환 문자열 | `mask`, `pseudonym`, `organization` |
| Pipeline | 문서 → ProcessingResult | 탐지 실패 시 예외, 조회 실패 시 대체 표시 |

사용자 모델은 `detect(text) -> list[Entity]`를 구현해 연결합니다. 외부 디렉터리는 `resolve(names) -> dict[str, Resolution]`으로 연결합니다. 공개 패키지에는 고객별 DB 스키마나 연결 정보가 없습니다.

## 정책과 실패 처리

- 기본 정책은 **탐지된 모든 유형을 마스킹**합니다. 과거 서비스의 일부 유형만 치환하는 정책과 다릅니다.
- `organization`은 `PERSON_NAME`에만 적용합니다. 다른 유형에 지정하면 마스킹합니다.
- 조직 조회가 없거나 실패하거나 이름이 모호하면 가명 생성 조건을 확인하고, 조건을 충족하지 않으면 유형 마커를 사용합니다.
- 가명에는 16바이트 이상의 키와 문서 ID가 필요합니다. HMAC-SHA256의 앞 96비트를 사용합니다. 같은 문서·이름·키에서 일관되지만 동명이인을 구별하지 않으며 충돌 가능성이 수학적으로 0은 아닙니다.
- JSON 정책에 `key_env`를 지정하면 해당 환경변수에서 키를 읽습니다. 키 값은 설정 파일에 넣지 않습니다. 지정한 환경변수가 없으면 구성 오류입니다.
- CSV의 팀이 서로 다르면 상위 본부가 같아도 모호한 이름으로 유지합니다. 같은 이름·같은 팀의 중복 행은 개인 식별 없이 부서로 해석합니다.
- 잘못된 원문 위치나 탐지기 실패는 성공 결과를 만들지 않습니다. 조회기 예외 메시지는 출력에 포함하지 않습니다.
- 겹치는 탐지 구간은 런타임에서 합집합으로 덮습니다. 유형이 충돌하면 일반 `PII`로 마스킹합니다. 주변 문구를 더 넓게 덮을 수 있습니다.
- 한국어 조사 교정, 원문 복원 저장소, 재식별 방지 보증, 원본 파일 삭제는 제공하지 않습니다. 이미 처리된 문자열을 다시 넣는 동작의 멱등성도 보장하지 않으므로 원문 버전을 기준으로 처리합니다.

예를 들어 `policy`를 `{"actions": {"PERSON_NAME": "pseudonym"}, "key_env": "KOPII_PSEUDONYM_SECRET"}`로 설정하고 키를 환경변수로 전달할 수 있습니다. `.env.example`은 변수명 안내용이며 패키지가 `.env` 파일을 자동으로 읽지는 않습니다.

## 탐지기 범위

기본 규칙은 이메일과 한국 휴대전화 형식만 다룹니다. 체크섬 검증이나 전체 개인정보 유형 탐지를 제공하지 않습니다. 데모 이름 사전에는 제한된 조사 경계 규칙만 있습니다.

Hugging Face 어댑터는 BIO 토큰 분류 모델, fast tokenizer, 겹치는 토큰 창을 사용합니다. 창 중복에서는 문맥이 더 넓은 토큰 예측을 선택합니다. 잘린 장문 뒷부분을 조용히 버리지 않습니다.

GLiNER 어댑터는 설정된 문자 창으로 추론하고 완전히 같은 위치·유형의 중복 예측만 제거합니다. 충돌 예측을 평가 전에 `PII`로 변환하지 않습니다. 기본 단어 경계 추출기를 사용하며, 한국어 경계 최적화는 아직 구현하지 않았습니다.

## 서비스 연결

호출 서비스가 원문 접근 권한·저장·승인·재시도를 관리합니다. 작업 큐와 API의 실패 처리는 이 라이브러리의 예외와 결과를 기준으로 구현합니다. GPU/NPU 배치, 검색 벡터 생성, 운영 서버 배포는 독립적인 통합 범위입니다. 본 패키지에는 HTTP 추론 서버를 추가하지 않았습니다.
