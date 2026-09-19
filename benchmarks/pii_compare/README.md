# 한국어 PII 모델 비교 재현

한국어 RoBERTa와 NVIDIA GLiNER-PII, Fastino GLiNER2-PII를 같은 데이터와 장치에서 평가합니다. [기록된 결과와 해석](../../docs/public/benchmark-results.md)을 먼저 확인할 수 있습니다.

## 설치

저장소 루트에서 Python 3.11과 `uv`를 사용합니다. 고정 의존성은 Apple M4 Pro에서 실행한 환경이며, 다른 플랫폼의 설치와 실행은 별도 확인이 필요합니다.

```bash
uv venv --python 3.11 benchmarks/pii_compare/.venv
uv pip install --python benchmarks/pii_compare/.venv/bin/python -r benchmarks/pii_compare/requirements.lock.txt
```

## 데이터와 모델 준비

```bash
benchmarks/pii_compare/.venv/bin/python benchmarks/pii_compare/prepare.py
```

- 평가 파일 두 개를 `data/ko_pii/`에 내려받고 기록된 SHA-256과 대조합니다.
- 모델 세 개를 고정 revision으로 Hugging Face 캐시에 내려받습니다. 네트워크 연결과 수 GB의 저장 공간이 필요합니다.
- 데이터만 준비하려면 `--skip-models`, 모델을 선택하려면 `--models roberta`를 사용합니다.
- `--data`로 다른 데이터 디렉터리를 지정할 수 있습니다. 준비·추론·채점에 같은 디렉터리를 지정합니다.
- 원문·가중치·가상환경·실행 로그는 Git에서 제외됩니다.

## 추론

같은 장치에서 모델을 **순차 실행**합니다. 동시 실행 시 속도 비교에 다른 모델의 부하가 섞입니다.

```bash
PYTORCH_ENABLE_MPS_FALLBACK=1 benchmarks/pii_compare/.venv/bin/python benchmarks/pii_compare/compare.py --model roberta --device mps
PYTORCH_ENABLE_MPS_FALLBACK=1 benchmarks/pii_compare/.venv/bin/python benchmarks/pii_compare/compare.py --model nvidia --device mps
PYTORCH_ENABLE_MPS_FALLBACK=1 benchmarks/pii_compare/.venv/bin/python benchmarks/pii_compare/compare.py --model fastino --device mps
```

CPU는 `--device cpu`, CUDA는 `--device cuda`를 사용합니다. 실행 시간은 장치와 런타임에 따라 달라지며 기록된 MPS 수치를 그대로 기대할 수 없습니다.

기본 결과 경로는 `benchmarks/pii_compare/output/`입니다. 실행 확인에는 `--limit 8 --out /tmp/kopii-smoke`처럼 별도 경로를 사용합니다. 표본 실행 결과는 전량 평가로 해석하지 않습니다.

## 채점과 경계 점검

```bash
benchmarks/pii_compare/.venv/bin/python benchmarks/pii_compare/score.py
benchmarks/pii_compare/.venv/bin/python benchmarks/pii_compare/audit.py
```

- `metrics.json`: 공통·주요 유형·개별 유형·대화/단문별 지표, 완료 수량, 실행 메타데이터
- `boundary_audit.json`: 입력 창 내 정답 포함 여부와 기본 단어 경계의 표현 제약
- 모델별 JSONL: 문서 ID와 예측 위치·유형·점수. 원문은 포함하지 않습니다.

추론은 같은 출력 경로에서 이미 기록된 문서 ID를 건너뜁니다. **같은 데이터·모델·설정의 중단 실행을 이어갈 때만** 사용합니다. 설정이 달라지면 새 `--out` 경로를 지정해야 합니다. 재개 시 시간 메타데이터는 마지막 실행분 기준이므로, 전체 처리 시간 비교에는 새 출력 경로의 완주 결과를 사용합니다. 공개된 점수는 재개 없이 전량 실행한 결과입니다.

채점 스크립트는 존재하는 예측 파일을 집계합니다. `completed == expected == 2586`인지 확인한 뒤 전체 결과로 사용해야 합니다. 공개 보고서는 2026-09-15의 고정 기록이며 재실행으로 자동 갱신되지 않습니다.

## 고정 평가 조건

- `test_kdpii.jsonl` 2,006건과 `test.jsonl`의 L4 580건, 총 2,586건을 사용합니다. 학습·검증 자료는 평가에 사용하지 않습니다.
- 홀드아웃에는 대화 458건과 그 대화의 단문 1,548건이 함께 있습니다. 모두 독립적인 대화는 아닙니다.
- 13개 공통 범주를 비교합니다. RRN·FOREIGNER_REG_NUM은 GOV_ID로 합치고 6개 비공통 유형은 제외합니다. 사업자등록번호는 정답 표본이 없어 재현율을 판단할 수 없습니다.
- 두 GLiNER 모델에는 같은 영문 라벨을 입력합니다. NVIDIA 임계값은 0.3, Fastino는 0.5이며 테스트셋에서 최적화하지 않았습니다.
- 모든 모델에 180자 창과 48자 겹침을 적용합니다. 정답 위치를 사용해 문서를 자르지 않습니다. 창 사이 중복은 경계에서 더 멀리 있는 예측을 우선합니다.
- RoBERTa는 256토큰·32토큰 겹침을 지원하는 토크나이저와 BIO 복원으로 구간을 얻습니다. 이번 공통 문자 창은 토큰 상한 이내였습니다.
- Exact는 시작·끝 위치와 라벨의 일치를 요구합니다. 문자 지표는 라벨을 무시하고 개인정보 문자를 덮은 범위를 비교하므로 과도한 탐지의 영향도 함께 봐야 합니다.
- 추론은 창 배치 4, 단건 지연은 동일하게 추출한 32개 문서를 배치 1로 측정합니다. 장치 동기화 이후 시간을 읽고 다운로드·로딩은 제외합니다.
- 정규식 보정, 조직정보 조회, 치환 정책과 운영 서버 HTTP 지연은 측정 범위에 포함하지 않습니다.

모델 라이브러리의 기본 추출 방식까지 포함한 비교입니다. 한국어 경계 처리나 라벨·임계값을 조정한 최적 성능 비교가 아닙니다.
