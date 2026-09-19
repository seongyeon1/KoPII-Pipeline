# 한국어 PII 모델 비교 실측 결과

평가일: 2026-09-15 · Apple M4 Pro / 통합 메모리 48 GiB / PyTorch MPS / float32

공개 문서 작성일: 2026-09-19. 평가 수치는 2026-09-15의 고정 기록이다.

## 결과 요약

현재 서빙에 사용한 revision의 KoPII RoBERTa가 이번 한국어 평가에서 가장 높은 정확도와 가장 낮은 단건 지연시간을 보였다. 이 결과는 현재 설정의 한국어 문서 처리 서비스에서 RoBERTa를 유지하는 판단을 뒷받침한다. **한국어로 파인튜닝한 RoBERTa와, 한국어용 추가 학습·설정 최적화 없이 적용한 공개 GLiNER 체크포인트를 비교한 결과이며 각 모델의 최적 성능이나 모든 언어에서의 우열을 뜻하지 않는다.** GLiNER의 낮은 점수에는 기본 추출기의 한국어 경계 제약도 포함된다.

**공개 모델의 고정 revision을 내려받아 로컬에서 수행한 비교다.** 운영 서버의 현재 출력과 HTTP 지연시간은 측정하지 않았다.

## 1. 공통 13개 범주 평가

KDPII 홀드아웃 2,006건에서 공통 범주의 정답 span 1,878개를 평가했다. Exact는 문자 시작·끝과 범주가 모두 일치해야 정답이다. 수치는 이번 실행에서 새로 측정했으며 모델 카드의 공개 점수를 섞지 않았다.

| 모델 | Precision | Recall | F1 | F5 | PII 문자 Recall | 무-PII 오탐 문서 |
| --- | --- | --- | --- | --- | --- | --- |
| KoPII RoBERTa base | 89.31% | 92.97% | 91.10% | 92.82% | 99.24% | 0/580 |
| NVIDIA GLiNER-PII | 6.25% | 14.48% | 8.73% | 13.78% | 88.53% | 559/580 |
| Fastino GLiNER2-PII | 19.04% | 20.77% | 19.87% | 20.69% | 81.45% | 182/580 |


PII 문자 Recall은 범주를 무시하고 정답 개인정보 문자 중 예측 영역이 덮은 비율이다. 이름에 조사를 포함하거나 긴 범위를 과도하게 잡아도 높게 나올 수 있으므로 Precision과 전체 span 보호율을 함께 봐야 한다. F5는 재현율을 더 중시하는 `26PR / (25P + R)`이다.

| 모델 | PII 문자 Precision | PII 문자 Recall | 정답 span 전체를 덮은 비율 |
| --- | --- | --- | --- |
| KoPII RoBERTa base | 98.45% | 99.24% | 96.81% |
| NVIDIA GLiNER-PII | 60.48% | 88.53% | 75.72% |
| Fastino GLiNER2-PII | 79.25% | 81.45% | 63.79% |


## 2. 문서 처리 서비스 기본 치환 범위와 이름 성능

현재 문서 처리 서비스의 기본 NER 치환 대상 10종에 해당하는 범위를 별도 집계했다. RRN·FOREIGNER_REG_NUM을 GOV_ID로 합쳐 평가상 9개 범주이고, 이 홀드아웃에는 사업자등록번호 정답이 없어 실질적으로 8개 범주의 정답 1,198개가 있다. 기존 정규식 필터·병합·마스킹·인사 DB 조회는 적용하지 않은 모델 결과다.

| 모델 | 기본 범위 Precision | 기본 범위 Recall | 기본 범위 F5 | 이름 Exact Recall | 이름 문자 Recall |
| --- | --- | --- | --- | --- | --- |
| KoPII RoBERTa base | 93.45% | 97.66% | 97.49% | 96.05% | 98.66% |
| NVIDIA GLiNER-PII | 5.18% | 15.44% | 14.35% | 12.43% | 54.13% |
| Fastino GLiNER2-PII | 19.51% | 26.71% | 26.34% | 18.36% | 75.00% |


이름의 정확한 문자열은 인사 DB 소속 조회의 입력이다. 문자 단위로 이름을 대부분 덮더라도 조사까지 포함하거나 이름 일부만 반환하면 소속 조회 결과가 달라질 수 있다. 이 평가는 그 영향의 전제인 이름 추출 품질을 측정했으며, 실제 HR 매칭 성공률은 측정하지 않았다.

## 3. 유형별 Exact Recall

| 평가 범주 | 정답 수 | KoPII RoBERTa base | NVIDIA GLiNER-PII | Fastino GLiNER2-PII |
| --- | --- | --- | --- | --- |
| PERSON_NAME | 354 | 96.05% | 12.43% | 18.36% |
| PHONE_NUM | 248 | 98.39% | 22.18% | 24.19% |
| EMAIL | 162 | 100.00% | 30.25% | 100.00% |
| ADDRESS | 202 | 82.18% | 12.87% | 4.46% |
| ACCOUNT_NUM | 154 | 96.10% | 0.00% | 0.00% |
| CARD_NUM | 156 | 99.36% | 17.95% | 16.03% |
| GOV_ID | 54 | 94.44% | 16.67% | 7.41% |
| PASSPORT_NUM | 36 | 100.00% | 0.00% | 2.78% |
| DRIVER_LICENSE_NUM | 34 | 100.00% | 0.00% | 8.82% |
| BIZ_REG_NUM | 0 | 평가 불가 | 평가 불가 | 평가 불가 |
| USER_ID | 316 | 79.75% | 12.97% | 12.03% |
| IP_ADDRESS | 22 | 100.00% | 27.27% | 27.27% |
| DOB | 140 | 97.14% | 10.00% | 12.14% |


사업자등록번호는 정답이 없어 재현율을 판단할 수 없다. 다른 희소 식별번호도 표본 수가 적으므로 수치를 실제 업무 전체의 보장으로 해석하지 않는다.

## 4. GLiNER 점수가 낮게 나온 이유와 해석 범위

### 4.1 확인된 제약: 한국어 이름·조사 경계

기본 GLiNER 단어 분리기는 한글 이름과 뒤에 붙는 조사를 같은 단어로 취급할 수 있다. 예를 들어 `김하늘의`에서 `김하늘`만을 반환하려면 단어 내부 경계가 필요하다. 설치한 두 라이브러리의 실제 기본 분리기로 정답 경계를 감사한 결과, **이름 정답 354개 중 244개는 공통 입력 창 어디에서도 기본 단어 시작·끝 경계로 표현할 수 없었다.**

따라서 GLiNER의 낮은 Exact 점수에는 모델 가중치의 한국어 적합성 외에 기본 추출 단위의 제약도 포함돼 있다. 가중치만의 우열을 분리해 측정한 실험은 아니다. Fastino 라이브러리는 이메일 전용 분리 규칙이 있어 NVIDIA 라이브러리와 이메일 경계 처리도 다르다. 모델을 그대로 도입했을 때의 라이브러리 동작 차이를 유지해 비교했다.

공통 정답 1,878개는 모두 하나 이상의 입력 창에 온전히 들어갔다. 정답 구간이 모든 창에서 잘려 점수가 낮아진 사례는 없었다. 창 내 최대 텍스트 토큰 수는 RoBERTa 109, NVIDIA 157, Fastino 141개로 확인했다.

### 4.2 개인정보를 일부 찾는 것과 정확히 추출하는 것의 차이

두 모델의 Exact F1은 NVIDIA 8.73%, Fastino 19.87%이지만, 범주를 무시한 개인정보 문자 Recall은 각각 88.53%, 81.45%다. 개인정보 문자를 덮은 예측도 범주가 틀리거나 조사·주변 문구를 포함하면 Exact에서는 오답이다. 따라서 낮은 Exact 점수를 개인정보를 전혀 인식하지 못한다는 의미로 읽으면 안 된다.

반대로 넓은 범위를 잘못 잡아도 문자 Recall은 높아진다. NVIDIA의 문자 Precision은 60.48%이고 무-PII 문서 580건 중 559건에서 오탐이 있었다. Fastino도 182건에서 오탐이 있었다. **경계 제약만으로 전체 성능 차이를 설명할 수 없으며, 미탐·유형 혼동·과도한 탐지가 함께 반영된 결과다.** 이름 244개의 경계 표현 불가능성은 확인한 사실이지만, 경계 처리만 바꿨을 때 F1이 얼마나 회복되는지는 실험하지 않았다.

### 4.3 학습 언어·데이터 분포의 차이

KoPII RoBERTa는 한국어 PII 데이터로 파인튜닝했다. NVIDIA 모델 카드는 영어 모델로 표시돼 있고, Fastino가 공개한 추가 학습 언어는 영어·프랑스어·스페인어·독일어·이탈리아어·포르투갈어·네덜란드어다. Fastino의 7개 언어에 한국어는 포함되지 않는다. 이는 베이스 모델이 한국어를 전혀 사전학습하지 않았다는 뜻은 아니다. [NVIDIA 모델 카드](https://huggingface.co/nvidia/gliner-PII), [Fastino 모델 카드](https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi)

공개 SPY·Argilla·AI4Privacy 결과와 이번 KDPII 결과는 언어, 도메인, 라벨 구성, 경계 주석과 평가 설정이 다르다. 공개 점수보다 낮다는 사실만으로 모델 로딩 실패나 서빙 중 성능 저하를 결론낼 수 없다. 이번 비교에는 한국어 도메인 적합성 차이가 반영될 수 있지만, 학습 언어만 바꾼 대조 실험을 하지 않아 그 기여도를 수치로 분리하지는 못했다.

### 4.4 라벨 표현·임계값을 최적화하지 않은 비교

GLiNER는 추론할 때 전달하는 라벨 목록을 조건으로 사용한다. 두 모델에는 같은 영문 목록을 전달했지만, 같은 표현이 두 체크포인트에서 동일하게 적합하다는 보장은 없다. 이름에 사용할 라벨 표현이나 한국식 식별번호의 설명을 바꾸는 탐색은 하지 않았다.

NVIDIA 0.3과 Fastino 0.5는 각각 공개 평가·사용 예시에서 가져온 임계값이다. 두 모델의 confidence가 같은 기준으로 보정됐다는 뜻은 아니며 한국어에서 최적인 값도 아니다. 임계값을 올리면 오탐을 줄이는 대신 미탐이 늘 수 있다. 이번 테스트 점수를 보고 임계값을 선택하지 않았으므로, 이 결과는 한국어용 설정을 최적화하기 전의 적용 기준선으로 사용한다.

### 4.5 이번 결과로 판단할 수 있는 범위

| 구분 | 해석 |
| --- | --- |
| 직접 확인한 사실 | 동일 한국어 평가 데이터에서의 점수·오탐·로컬 지연시간, 기본 단어 경계로 표현할 수 없는 이름 244개 |
| 영향을 줄 수 있으나 기여도를 분리하지 않은 요인 | 학습 언어·도메인 차이, 라벨 프롬프트와 confidence 임계값의 적합성 |
| 현재 적용 판단 | 현재 설정 그대로 한국어 문서 처리 서비스에 연결할 때는 RoBERTa가 적합하다는 근거 |
| 이번 평가로 판단하지 않은 항목 | 각 모델의 최적 성능, 한국어 경계 보정·재학습 이후의 성능, 다른 언어의 우열, 실제 운영 GPU의 품질·지연시간 |


추가 비교는 한국어 경계 처리를 검토하고 별도 검증셋에서 라벨 표현·임계값을 선택한 뒤, 그 선택에 사용하지 않은 업무 테스트셋에서 수행한다. 기존 기본 설정 결과도 함께 남겨 어떤 변경이 경계 정확도·문자 보호율·오탐·HR 이름 조회 입력에 영향을 주었는지 비교한다. 개선 여부와 크기는 재평가 전에는 확정하지 않는다.

## 5. 추론 시간

세 모델은 같은 로컬 장치에서 순차 실행했다. 로딩·다운로드 시간은 제외했다. 전체 처리에는 2,586개 문서에서 만든 3,179개 창을 chunk batch 4로 처리했고, 단건 지연시간은 고정 난수 seed로 선택한 동일한 32개 문서를 batch 1로 실행했다. 매 측정에서 MPS 동기화 후 시간을 읽었다.

| 모델 | 실제 로딩 파라미터 | 2,586건 배치 처리 | 단건 중앙값 | 단건 p95 |
| --- | --- | --- | --- | --- |
| KoPII RoBERTa base | 110,059,049 | 12.09초 | 12.08 ms | 137.35 ms |
| NVIDIA GLiNER-PII | 445,463,040 | 122.83초 | 75.85 ms | 258.05 ms |
| Fastino GLiNER2-PII | 307,098,645 | 60.71초 | 38.56 ms | 186.12 ms |


이는 M4 Pro MPS의 단일 실행 관찰값이다. CUDA/vLLM 서버의 지연시간·처리량·메모리 사용량으로 환산할 수 없다. 단건 p95도 32건 표본이며 부하 테스트 결과가 아니다. Fastino는 DeBERTa의 SDPA 미지원으로 eager attention을 사용했다. 실행에는 MPS 미지원 연산의 CPU fallback 허용 환경변수를 두었으며, 세 모델의 실행 로그에서 CPU fallback 경고는 관찰되지 않았다.

## 6. 데이터와 공정 비교 조건

### 6.1 실제 테스트에 사용한 데이터셋과 파일

평가 데이터셋은 [seongyeon1/ko-pii-ner-100k](https://huggingface.co/datasets/seongyeon1/ko-pii-ner-100k)다. 구축 시 보관한 평가 파일을 사용했으며, 공개 데이터셋의 고정 버전에서 내려받은 파일과 SHA-256을 대조한다. 사용한 파일의 해시는 8절에 기록했다.

| 사용 파일·구간 | 평가 수량 | 출처와 평가 목적 |
| --- | --- | --- |
| `test_kdpii.jsonl` 전량 | 2,006건 | KDPII 공식 test에서 구성한 홀드아웃. 개인정보 탐지 성능 측정 |
| `test.jsonl` 중 `meta.layer == "L4"` | 580건 | 개인정보가 없는 합성 문서. 오탐 여부 측정 |
| 합계 | 2,586건 | 세 모델에 동일한 레코드 적용 |


**공개 데이터셋 전체 약 10만 건을 평가한 것이 아니다.** 학습용 `train.jsonl`과 검증용 `valid.jsonl`은 이번 비교 평가에 사용하지 않았으며, `test.jsonl`도 L4 580건만 선택했다. KDPII 2,006건은 대화 458건과 그 대화에서 추출한 단문 1,548건으로 구성돼 모두 독립적인 대화는 아니다.

### 6.2 평가 조건과 해석 시 주의점

- KDPII 홀드아웃: 대화 458건 + 해당 대화에서 추출한 단문 1,548건 = 2,006건. 전체를 사용했지만 2,006개가 모두 통계적으로 독립적인 대화는 아니다.
- 무-PII 평가: 내부 test의 L4 580건 전량. RoBERTa 학습 데이터와 동일한 합성 파이프라인 계열이므로 자연 발생 업무 문서의 오탐률로 일반화하지 않는다.
- 세 모델에 같은 13개 범주를 적용했다. GLiNER 두 모델에는 같은 영문 라벨 프롬프트 목록을 제공했다. 범주별 최적 라벨 표현을 탐색한 결과는 아니다.
- RRN·FOREIGNER_REG_NUM은 `national_id_number`에 대응하는 GOV_ID로 통합했다. 나머지 명칭 매핑은 아래 표와 같다.
- AFFILIATION, SENSITIVE_ATTR, POSITION, AGE, PLATE_NUM, URL_PERSONAL은 공통 평가에서 제외했다. 이들 영역을 공통 범주로 잘못 예측하면 오탐으로 센다.
- NVIDIA threshold는 모델 카드 평가에 명시된 0.3, Fastino는 quick start의 0.5를 사용했다. 테스트 데이터로 threshold나 라벨 표현을 조정하지 않았다. RoBERTa는 토큰 argmax 및 BIO 복원을 사용했다.
- 모든 모델에 동일한 180자/48자 겹침 창을 적용하고 끝점은 가능하면 공백으로 조정했다. 이는 문서 처리 서비스의 기존 256토큰 창과 별개인 이번 비교용 공통 전처리다.
- RoBERTa의 라벨·토크나이저는 서빙 revision과 같고 BIO 복원은 배포 시 사용한 구간 복원 방식을 따랐다. HTTP/vLLM의 수치적 동일성이나 운영 전체 파이프라인을 검증한 것은 아니다.
- 창 사이 예측 충돌은 창 가장자리에서 더 멀리 떨어진 예측을 우선하고 동률일 때 confidence로 정리했다.
- 영어 가상 문장 smoke test에서 두 GLiNER 모델의 이메일·전화번호 탐지를 확인한 후 한국어 평가를 실행했다.

| 평가 범주 | GLiNER 입력 라벨 |
| --- | --- |
| PERSON_NAME | person |
| PHONE_NUM | phone_number |
| EMAIL | email |
| ADDRESS | address |
| ACCOUNT_NUM | account_number |
| CARD_NUM | card_number |
| GOV_ID | national_id_number |
| PASSPORT_NUM | passport_number |
| DRIVER_LICENSE_NUM | drivers_license_number |
| BIZ_REG_NUM | tax_id |
| USER_ID | username |
| IP_ADDRESS | ip_address |
| DOB | date_of_birth |


대화/단문별 공통 범주 결과는 다음과 같다.

| 구간 | 모델 | 레코드 | Precision | Recall | F5 |
| --- | --- | --- | --- | --- | --- |
| L1 | KoPII RoBERTa base | 458 | 87.53% | 92.65% | 92.44% |
| L1 | NVIDIA GLiNER-PII | 458 | 5.94% | 14.06% | 13.35% |
| L1 | Fastino GLiNER2-PII | 458 | 18.12% | 21.41% | 21.26% |
| L1b | KoPII RoBERTa base | 1548 | 91.16% | 93.29% | 93.21% |
| L1b | NVIDIA GLiNER-PII | 1548 | 6.57% | 14.91% | 14.22% |
| L1b | Fastino GLiNER2-PII | 1548 | 20.13% | 20.13% | 20.13% |


별도 학습 실험의 홀드아웃 F5 0.9344와 이번 수치는 평가 범주, 문자 경계 기준, 길이 처리 방식이 달라 직접 증감 비교하지 않는다. 공개 SPY·Argilla·AI4Privacy 점수도 한국어 KDPII 점수와 같은 표본의 결과가 아니다.

## 7. 적용 판단

현재 문서 처리 서비스에서는 한국어 RoBERTa를 유지하고 기존 정규식·인사 DB 범주화와 결합하는 구성이 이번 결과에 부합한다. Fastino/NVIDIA를 검토한다면 먼저 한국어 조사 경계를 처리할 수 있도록 추출 단위를 조정하고, 별도 검증셋에서 라벨 표현과 threshold를 선택한 뒤 손대지 않은 업무 테스트셋으로 다시 평가해야 한다.

한국어 홀드아웃 결과만으로 영어·유럽 언어의 모델 우열까지 판단하지 않는다. Fastino 카드의 fine-tuning 언어는 영어·프랑스어·스페인어·독일어·이탈리아어·포르투갈어·네덜란드어이고 한국어는 포함되지 않는다. NVIDIA 카드는 영어 모델로 표시돼 있다. 두 GLiNER에는 한국어 추가 학습을 하지 않았다. 이번 비교는 한국어 PII에 파인튜닝한 RoBERTa와 공개 GLiNER 체크포인트를 그대로 적용한 조건의 비교다.

## 8. 모델과 재현 자료

| 모델 | 고정 revision |
| --- | --- |
| [seongyeon1/ko-pii-ner-roberta-base](https://huggingface.co/seongyeon1/ko-pii-ner-roberta-base/tree/95a3af685dccf4bb3f7fff6fc81146fed71500bb) | `95a3af685dccf4bb3f7fff6fc81146fed71500bb` |
| [nvidia/gliner-PII](https://huggingface.co/nvidia/gliner-PII/tree/bd23e8ef4425fd04e34c5204ab49ffaa706eae79) | `bd23e8ef4425fd04e34c5204ab49ffaa706eae79` |
| [fastino/gliner2-privacy-filter-PII-multi](https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi/tree/c153999da5f4c509df4322b0c6a1baf3d2c284d7) | `c153999da5f4c509df4322b0c6a1baf3d2c284d7` |


- [NVIDIA 모델 카드](https://huggingface.co/nvidia/gliner-PII): 공식 평가 threshold와 사용 방법.
- [Fastino 모델 카드](https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi): 기본 사용 방법·라벨·학습 언어.
- [KoPII 데이터셋](https://huggingface.co/datasets/seongyeon1/ko-pii-ner-100k): 평가 데이터 출처.
- [실행 방법](../../benchmarks/pii_compare/README.md), [비교 실행 코드](../../benchmarks/pii_compare/compare.py), [채점 코드](../../benchmarks/pii_compare/score.py), [경계 감사 코드](../../benchmarks/pii_compare/audit.py), [고정 의존성](../../benchmarks/pii_compare/requirements.lock.txt).
- [전체 수치·실행 메타데이터](benchmark-results.json). 원문은 결과 파일에 복사하지 않았다.

주요 패키지: torch 2.14.0, transformers 4.57.6, tokenizers 0.22.2, gliner 0.2.29, gliner2 2.0.0. 공통 채점 함수는 경계가 어긋난 예측의 Exact 실패와 문자 Recall 성공을 구분하는 작은 정답 사례로 확인했고, 모든 입력 창의 문자 범위 포함 여부와 모든 정답 좌표를 검사했다.

데이터 파일 SHA-256:

| 파일 | SHA-256 |
| --- | --- |
| test_kdpii.jsonl | `2bde2d83474a2d43aef33eef0b606b0acf3ac9270e6e67bc56e13b19c17ca379` |
| test.jsonl | `2ca9f92cee0c2ce1cd15fee9993584d927c6e533ba66f941d8b1d72ff800c87c` |


## 공개 자료의 재현 범위

[평가 준비 스크립트](../../benchmarks/pii_compare/prepare.py)는 데이터셋과 모델 버전을 고정해 내려받고 평가 파일의 해시를 검사한다. [실행 안내](../../benchmarks/pii_compare/README.md)에 따라 같은 파일을 준비할 수 있다. 추론과 채점 코드에는 개인별 로컬 경로를 요구하지 않도록 데이터 경로를 인자로 제공한다.

함께 제공한 JSON의 `script_sha256`은 측정 당시 스크립트의 해시다. 공개 준비 과정에서 데이터 경로 기본값과 설명을 정리한 현재 파일의 해시와는 다를 수 있다. 평가를 다시 실행하거나 결과를 조정하지 않았다. 공개 JSON의 실수 표기는 소수점 여섯 자리로 반올림했으며 정답·오탐·미탐 건수는 그대로 보존했다. 원문 데이터, 실행별 예측 파일, 모델 가중치는 저장소에 포함하지 않는다.
