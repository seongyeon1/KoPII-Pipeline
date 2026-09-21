# 재현 가능한 연구 실행

새 프레임워크의 실험과 2026-09-15의 도입 검토 벤치마크를 분리합니다. 기존 `benchmarks/pii_compare/` 코드·공개 결과는 보존했습니다. 아래 명령은 새 실행 경로이며 기존 숫자를 재현한다고 주장하지 않습니다.

## 데이터 계약

UTF-8 JSONL의 각 행에는 `id`, `text`, `spans`가 필요합니다. 각 span에는 `start`, `end`, `label`이 필요하며 위치는 정규화하지 않은 Python 문자열의 반개구간입니다. 음성 문서도 `spans: []`를 명시합니다. 중복 ID, 범위 오류, 중복 정답, 제공된 표면 문자열과 위치 불일치는 거부합니다.

`group_id`는 같은 원본 대화·문서에서 파생된 자료의 공통 ID입니다. 행 ID를 기계적으로 복사해 그룹 독립성을 가장해서는 안 됩니다. 새 학습과 그룹 부트스트랩에는 모든 행의 그룹 ID가 필요합니다. 기존 공개 데이터의 그룹은 원천 대응 관계를 확인해 변환해야 하며, 평가기가 임의 추정하지 않습니다.

## 가상 자료로 실행 확인

```bash
kopii synthesize --output output/fixture-data --seed 42 --per-template 12
kopii audit-splits \
  --train output/fixture-data/train.jsonl \
  --dev output/fixture-data/dev.jsonl \
  --test output/fixture-data/test.jsonl
kopii evaluate --config configs/eval-rules.json \
  --data output/fixture-data/test.jsonl --output output/rules-fixture
```

합성기는 6개 고정 템플릿을 4/1/1로 나누고, 이름·예약 도메인 이메일·음성 문장을 만듭니다. 동일 시드에서 동일 파일을 생성하며 템플릿 가족과 그룹을 분리합니다. **기존 100,851건 생성기의 재구현이 아니고 실제 업무 성능 평가셋도 아닙니다.** 출력 디렉터리가 비어 있지 않으면 덮어쓰지 않습니다. 데이터 확장은 [연구 계획](PLAN.md)의 별도 과제입니다.

`audit-splits`는 ID·그룹·정확한 원문 중복을 보고하며 중복이 있으면 종료 코드 1을 반환합니다. 그룹 ID 누락은 수량으로 보고합니다. 의미적 유사문장, 공유 템플릿, 사전학습 데이터 오염까지 검출하는 도구는 아닙니다.

## 신경망 모델 평가

```bash
python -m pip install -e '.[hf,gliner]'
kopii evaluate --config configs/eval-roberta.json \
  --data output/fixture-data/test.jsonl --output output/roberta-fixture
```

후보 모델은 `configs/eval-nvidia.json`, `configs/eval-fastino.json`을 사용합니다. 기본 장치는 CPU이며 필요에 따라 JSON의 `device`를 변경합니다. 두 모델의 초기 임계값은 과거 도입 검토 설정에서 가져왔으며 최적화 결과가 아닙니다. 세 신경망 설정의 비교 범주는 13개이며 주민·외국인등록번호를 `GOV_ID`로 합칩니다. 음성 문서 오탐은 선택 범주에 한정됩니다.

실제 연구 평가 파일에는 각 모델의 동일한 자료를 입력합니다. 새 HF 경로는 문서 전체의 토큰 창을 사용하고 GLiNER 경로는 문자 창을 사용하므로, 길이 처리 차이도 시스템 비교 조건의 일부입니다. 경계 방식만의 영향을 분리하는 공통 분할 실험은 추가 과제입니다.

## 결과와 이어쓰기

출력 디렉터리에는 다음 파일을 만듭니다.

- `manifest.json`: 데이터·패키지 소스 해시, 모델 revision, 명시적 설정, 주요 의존성 버전, Python·OS 정보
- `predictions.json`: 원문을 복제하지 않은 문서 ID별 예측 위치와 점수
- `metrics.json`: 완료 여부, 유형별 exact 점수, 문자 단위 지표, 전체 span 보호율, 음성 문서 오탐

데이터·설정·패키지 소스·기록된 환경이 달라지면 동일 디렉터리의 이어쓰기를 거부합니다. 변경하지 않은 실행은 완료된 문서를 재추론하지 않습니다. 체크포인트는 임시 파일을 완성한 뒤 원자적으로 교체합니다. 동시 쓰기는 `.run.lock`으로 거부하며, 비정상 종료 후에는 활성 프로세스가 없는지 확인한 다음 남은 잠금 파일만 수동으로 제거합니다.

실험 모델에는 Hub의 전체 40자리 commit SHA를 요구합니다. 가변 로컬 가중치는 이 실행기의 입력으로 허용하지 않습니다. 모델을 학습한 뒤 로컬 검증은 `train`이 수행하며, 후속 독립 실험은 모델 게시 revision을 고정한 다음 실행합니다. 모델 게시 자체는 자동 수행하지 않습니다.

`bootstrap_samples`를 양수로 설정하면 원본 그룹을 통째로 재표집하는 F1 구간을 계산합니다. 예제 신경망 설정은 기존 데이터의 그룹 정보를 임의로 가정하지 않도록 0으로 설정했습니다. 극소량 fixture의 구간은 실질적인 통계 근거가 아닙니다. 실행 중 문서별 시간은 워밍업·동기화·부하 통제를 갖춘 서비스 지연시간 벤치마크가 아닙니다.

## 새 학습 기준선

```bash
python -m pip install -e '.[train]'
kopii train --config configs/train-baseline.json \
  --train output/fixture-data/train.jsonl \
  --dev output/fixture-data/dev.jsonl \
  --output output/training-baseline
```

기반 모델과 토크나이저 revision을 고정하고, BIO 5클래스(예제의 이름·이메일 두 유형)를 학습합니다. 실제 20유형 학습에는 완전한 라벨 목록과 정제된 데이터를 별도 설정해야 합니다. train/dev의 그룹 ID 누락이나 중복이 있으면 학습 전에 거부합니다. 특수 토큰은 손실에서 제외하며 초과 입력도 겹치는 토큰 창으로 사용합니다.

**이번 학습기는 cross-entropy와 고정 epoch를 사용하는 새 기준선입니다.** 기존 배포 모델의 Focal loss·F5 체크포인트 선택·256토큰 절단 학습과 다릅니다. 자동 best checkpoint 선택과 학습 재개는 제공하지 않습니다. 이미 사용한 출력 디렉터리를 덮어쓰지 않습니다.

학습 후 모델·토크나이저를 저장하고 dev 전체를 추론해 점수를 기록합니다. manifest에는 train/dev 해시와 실행 설정, 결과에는 저장된 모델 파일들의 집계 해시를 남깁니다. 이 검증 결과는 최종 테스트 점수가 아닙니다. 기기별 완전한 비트 단위 재현성을 보장하지 않으며 복수 시드 실험은 별도로 수행해야 합니다.

## E2/E3 측정 실험 재현

[완료된 실험 보고서](RESULTS.md)와 [검토 노트북](01-Study-Results.ipynb)을 제공합니다. E2는 기존 테스트의 재평가, E3는 가상 조직의 통제 실험입니다. 운영 GPU/HTTP 서버는 변경하지 않습니다.

별도 신경망 환경에 과거 비교와 같은 고정 의존성을 설치합니다. 아래 예시는 저장소 루트에서 실행하며, 공개 모델 캐시와 데이터 약 수 GB를 사용합니다.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r benchmarks/pii_compare/requirements.lock.txt
python -m pip install --no-deps -e .
python - <<'PYCODE'
from huggingface_hub import hf_hub_download, snapshot_download
import json
revision = "660e03a454f7934261be41390744796565550ce2"
for filename in ("train.jsonl", "valid.jsonl", "test.jsonl", "test_kdpii.jsonl"):
    hf_hub_download("seongyeon1/ko-pii-ner-100k", repo_type="dataset",
                    filename=filename, revision=revision, local_dir="data/ko_pii")
for name in ("nvidia", "fastino", "roberta"):
    config = json.load(open(f"configs/eval-{name}.json"))["detector"]
    snapshot_download(config["model"], revision=config["revision"])
PYCODE
TOKENIZERS_PARALLELISM=false python research/run_korean_study.py
python research/audit_study_splits.py
TOKENIZERS_PARALLELISM=false python research/run_organization_study.py
```

공개 실행 설정은 Apple Silicon **MPS**입니다. E2의 장치를 바꾸려면 `studies/korean-settings.json`의 `device`를 수정하고 새 output 경로를 지정합니다. E3는 `--device cpu` 또는 `--device cuda`를 지원합니다. 장치와 소스·데이터·설정이 달라지면 동일 출력의 이어쓰기를 거부합니다. `local_files_only=True`이므로 먼저 위 다운로드를 완료해야 합니다. 기기별 비트 단위 동일 결과는 보장하지 않습니다.

실행기 하나당 하나의 프로세스만 사용합니다. 원문과 문서별 예측은 공개할 목적이 아니며 `output/`은 Git에서 제외합니다. 완료된 실행은 캐시된 예측을 재사용하지만 개발 임계값 동등성 검사는 다시 수행합니다. E2의 모델별 선택 파일은 테스트 추론 전에 저장합니다. E3는 정책을 튜닝하지 않습니다.

```bash
python -m pip install -r research/requirements-report.txt
python research/report_studies.py
python - <<'PYCODE'
from pathlib import Path
import nbformat
from nbclient import NotebookClient
path = Path("research/01-Study-Results.ipynb")
notebook = nbformat.read(path, as_version=4)
NotebookClient(notebook, timeout=120, kernel_name="python3",
               resources={"metadata": {"path": str(Path.cwd())}}).execute()
nbformat.write(notebook, path)
PYCODE
```

그림 생성기는 두 실험 모두 `complete: true`일 때만 집계 JSON·선택된 평가 설정·그림·노트북을 만듭니다. 이름/본문/문서별 예측은 복사하지 않습니다. 공개 비율 값은 소수점 6자리로 반올림하고 원래 정밀도는 로컬 실행 결과에 남깁니다. SVG는 접근 가능한 텍스트 레이블을 유지합니다. 생성된 `configs/eval-*-ko-tuned.json`은 이번 개발셋에서 선택한 범위 내 설정이며, 배포 기본값을 변경하지 않습니다.

E3의 이름 외 탐지 유형별 수와 업무참조 오인은 사후 진단입니다. 이름만 gold인 조건과 실제 NER의 모든 유형 치환 조건 차이를 이름 탐지 오류로 혼동하지 않습니다. E1 합성 데이터 학습 효과, 같은 자료 재학습 비교, 미사용 실제 업무셋, 운영 검색·LLM QA·강한 재식별 공격 검증은 [남은 연구](PLAN.md)입니다.

이번 공개 집계는 Fastino 위치 복원 수정 전후의 완료된 모델 실행을 연결합니다. `manifest.component_runs`에 원래 실행 ID·소스 해시가 있고, `studies/snapshots/`에는 수정 전 NVIDIA 실행의 소스가 있습니다. 중단된 Fastino 예측은 사용하지 않았습니다. 새 환경에서는 기본 명령으로 세 모델을 모두 수정 후 코드에서 실행하면 됩니다. 과거 두 실행을 그대로 결합할 때만 `research/combine_korean_runs.py`와 `report_studies.py --korean-results output/korean-settings-combined/results.json`을 사용합니다.

## 메타데이터 검색 후속 비교

[실행 안내](METADATA_STUDY.md)와 [측정 결과](results/metadata-tables.md)를 제공합니다. 같은 가상 문서에서 본문 조직 치환과 별도 메타데이터 필터를 비교하고, 본문만 보는 공격자와 검색 필터를 아는 공격자의 위험을 분리했습니다. 운영 임베딩용 HTTP·cosine 실행 경로도 제공하지만 실제 NPU 결과는 아직 없습니다.

## 가상 조직 없이 사용자 문서로 검색 평가

0.2.0의 `kopii prepare`, `kopii search`, `kopii evaluate-search`는 기존 세계 생성기를 사용하지 않습니다. [범용 문서 처리·검색 API](../docs/public/context-search.md)에 임의 속성 조회, JSONL 계약, 허용 문서 범위, 외부 임베딩 연결을 설명했습니다. 기본 검색기의 통계는 필터를 통과한 후보 안에서 계산하므로 기존 연구 BM25 결과와 설정을 구분합니다. 과거 실험 코드는 유지하며 코어/버전 변경 후에는 새 출력 경로로 실행합니다.
