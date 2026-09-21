# 조직 메타데이터 기준선과 임베딩 실행

[결과 표](results/metadata-tables.md) · [사전 실행 설정](studies/metadata-retrieval.json) · [보강 계획](../docs/plans/submission-strengthening.md)

기존 E3와 같은 가상 조직·문서·질의·모델 예측으로 후속 비교를 실행했다. 본문 마스킹과 부서 메타데이터 필터를 결합하면 이 합성 과제에서 본문 조직 치환과 비슷한 검색 품질을 얻었다. 그러나 검색 필터를 아는 공격자에게 조직 정보가 드러나면 그 차이는 유지되지 않는다.

## 재현

저장소 루트에서 설치된 `kopii` 환경을 사용한다. 먼저 [기존 E3](README.md)의 `run_organization_study.py`를 완료해야 한다. `output/organization-study`의 완료 결과·manifest·예측이 필요하다. 새 추론은 하지 않으며 생성 문서 해시·예측 문서 ID·기존 실행 ID를 검증한다.

```bash
python research/run_metadata_study.py --output output/metadata-study-final
python research/report_metadata_study.py --results output/metadata-study-final/results.json
```

`results.json`에는 시드별 집계와 출처 해시만 담는다. `embedding-input.json`에는 합성 문서의 처리 결과와 질의가 들어가며 로컬 `output/`에만 둔다. 공개 집계 비율은 소수점 여섯 자리로 반올림한다. 원래 정밀도는 로컬 결과에 보존한다. 예전 결과를 다른 코드로 덮어쓰지 않도록 실행 ID가 다르면 새 출력 경로를 요구한다.

필터의 메타데이터는 서비스 명부 조회에 성공한 이름 치환 결과에서 얻는다. 정답 인물의 소속은 채점에서만 참조한다. 각 실험은 팀·본부·센터 중 한 수준만 저장한다. 원래 전체 질의로 BM25 순위를 계산한 뒤 조직 필터를 적용하고 top-5를 취한다. 요청 조직이 미허용이거나 메타데이터가 없으면 전체 검색으로 폴백하지 않는다.

권한 범위는 호출자가 제공하는 연구용 입력이다. 실제 인증·문서 ACL은 이 코드에서 구현하지 않는다. 실험에서는 모든 조직이 허용된 가상 사용자를 가정했다. 조직명이 없는 질의·복수 조직 질의·인물명 기반 질의·메타데이터 QA는 이번 검색 비교 범위에 포함하지 않았다.

## 운영 임베딩 API 연결 — 아직 미실행

API 주소·모델·배포 버전을 확인하면 **동일한 합성 입력**으로 비교할 수 있다. HTTP `/embeddings`의 OpenAI 호환 JSON 계약을 지원하며, 서버가 실제 어떤 하드웨어를 쓰는지는 이 도구가 검증하지 않는다. NPU라는 이름만으로 운영 NPU 측정이라고 보고하지 않는다.

1. `configs/embedding-study.example.json`을 `output/embedding-config.json`으로 복사한다.
2. 실제 모델 ID와 체크포인트·서빙 버전을 기록한다. 질의/문서 prefix가 필요한 모델이면 운영 설정과 맞춘다.
3. `KOPII_EMBEDDING_ENDPOINT`에 전체 endpoint를, 인증이 있으면 `KOPII_EMBEDDING_API_KEY`에 키를 설정한다. 인증이 없는 내부 서버는 설정의 `api_key_env`를 빈 문자열로 둔다. 값은 Git에 기록하지 않는다.

```bash
python research/embed_study.py \
  --input output/metadata-study-final/embedding-input.json \
  --config output/embedding-config.json \
  --output output/metadata-embeddings.json
python research/run_metadata_study.py \
  --embeddings output/metadata-embeddings.json \
  --output output/metadata-study-dense
```

입력별 ID·전체 입력 해시·임베딩 개수·응답 순서·차원·유한값을 검사한다. 문서/질의 벡터는 정규화 후 정확한 cosine 검색에 사용한다. 모델 ID와 서버가 반환한 모델 ID가 다르면 실패한다. 배포 revision은 운영자가 제공한 정보이며 가중치 원격 검증은 아니다. 임베딩 실행 시간은 초기 워밍업이 포함된 순차 HTTP 배치 시간으로, 운영 서버 지연시간이나 최대 처리량 벤치마크가 아니다.

BM25 공개 보고서 생성기는 dense 결과를 받으면 거부한다. 실제 임베딩 결과는 모델·전처리·배포 버전과 함께 별도 표로 작성해야 한다. API 계약 테스트의 로컬 고정 벡터는 품질 측정이나 NPU 실행 증거가 아니다.

## 독립 업무 자료 평가 — 아직 미실행

실제 문서·명부는 공개 저장소에 반입하지 않는다. 승인된 별도 환경에서 아래 평가 계약을 먼저 확정한다.

| 자료 | 필요한 정보 |
|---|---|
| 문서 | 비식별 ID, 원본 문서 가족 ID, 시점·문서 유형, 접근 가능한 저장 위치 |
| 탐지 정답 | 원문 기준 문자 구간·유형, 주석 지침, 이중 주석과 불일치 조정 기록 |
| 서비스 조직정보 | 평가 시점 조회 결과, 조회 실패·모호성·최종 갱신 시점 |
| 검색 과제 | 실제 업무에서 수집한 질의, 요청 조직·사용자 권한, 수동 검수한 관련 문서 집합 |
| 개인 추정 | 평가 허용된 후보 집합, 공격자에게 허용된 배경 지식, 문서/필터/결과 관찰 범위 |
| 분할 | 개발과 최종 평가의 원본 문서 가족·시점 분리, 중복 검사, 최종셋을 본 설정 변경 기록 |

새 평가셋을 기존 합성 템플릿 복제로 대체하지 않는다. 평가 수량과 검출 가능한 차이는 실제 자료 구성 및 개발 단계 분산을 보고 정하되, 최종 평가 결과를 보기 전에 고정한다. 문서 가족 단위 paired bootstrap으로 정책 차이를 보고하고, 실서비스 권한 통제를 검증한 경우에만 그 결과를 별도로 주장한다.
