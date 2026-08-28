# 한국어 PII 탐지 · 범주화(일반화) 파이프라인 설계

- 작성일: 2026-08-28
- 상태: §1~§5 작성 완료 — 전체 설계 초안 완료, 사용자 리뷰 대기
- 이 문서는 KoPII-Pipeline 레포로 함께 이관한다
- 레포: `KoPII-Pipeline` (독립 오픈소스, MIT)
- 패키지 루트: `kopii/`

> **주의** — 이 문서에는 실제 사번·실명을 싣지 않는다. 모든 예시는 형태만 보존한 가상 값이다.
> 실제 샘플이 담긴 파일은 `data/` 밖 또는 gitignore 경로에 둔다.

> **`PolyBed-Pipeline`과의 관계** — 이 프로젝트는 PolyBed에서 분리된 **독립 공개 레포**다.
> PolyBed는 비공개이므로 **공개 레포가 그것을 의존할 수 없다.** 의존 방향은 반대다 —
> KoPII가 자립하고, 필요하면 PolyBed가 KoPII를 설치해 쓴다. 상세는 §1.3.

---

## 1. 배경과 목표

사내 문서에서 개인정보·민감정보를 탐지하고, **값을 지우는 대신 추상화 계층을 한 칸씩 올려** 의미를
남긴 채 비식별화한다. `[MASK]`로 뭉개면 문장의 의미가 사라져 다운스트림 태스크가 망가지므로,
"사번 → 소속 팀 → 본부 → 고용 형태" 처럼 **단계적으로 일반화**한다.

### 확정된 요구사항

| 항목 | 결정 |
|---|---|
| 용도 | ① 외부 LLM API 호출 전 마스킹 ② 사내 RAG/검색 인덱싱 |
| 조직 도메인 지식 | 현재 없음 — 지식 없이도 동작해야 하고, 채워질수록 좋아져야 함 |
| 한국어 데이터 | 합성 생성기 구축 + AI Hub 등 공개 데이터 |
| 1차 스코프 | **범주화 엔진 + 규칙 기반 탐지** (한국어 NER 모델 학습은 2차) |

### 1.3 프로젝트 형태 — 독립 오픈소스 레포

`KoPII-Pipeline` (MIT). 이 결정이 설계에 세 가지 제약을 건다.

**(a) 자립해야 한다.** PolyBed가 비공개라 그 `core/modules/evaluation/`을 import할 수 없다.
§8의 유틸리티 지표는 KoPII 안에서 numpy/scikit-learn만으로 구현한다 — alignment·uniformity는
100줄대, IR 지표는 200줄대라 재구현 비용이 의존성 부담보다 작다. 알고리즘은 PolyBed 구현과
동일하게 맞춰 두 레포의 수치가 비교 가능하도록 한다. NER 라벨 스키마(`ENTITY_MERGE_MAP`,
Kaggle 7-type 매핑)도 KoPII가 자체 보유한다.

의존 방향은 **KoPII ← PolyBed**다. PolyBed가 익명화가 필요해지면 `pip install kopii`로 쓴다.

**(b) 사내 지식이 레포에 들어가면 안 된다.** 조직도·`hr_directory`·실제 사번 포맷·실문서는
어느 것도 커밋하지 않는다. §5의 `KnowledgeProvider` 분리와 로케일 팩 설계가 이미 이 요구를
만족한다 — 오픈소스화는 그 일반화가 실제로 됐는지에 대한 검증이다. 레포에는 `synthetic.py`가
만드는 가상 조직만 들어간다.

**(c) 누구나 clone해서 바로 돌릴 수 있어야 한다.** 공개 한국어 PII 코퍼스가 사실상 없고 AI Hub
데이터는 재배포가 제한되므로, **§9의 합성 생성기가 부가 기능이 아니라 1급 시민**이다.
`git clone && python -m kopii.synth && python -m kopii.eval`이 외부 데이터 없이 끝까지 돌아야
한다. 구현 순서에서 `synth/`를 맨 앞에 둔 이유가 여기서 하나 더 늘어난다.

**(d) 시크릿에 기본값을 두지 않는다.** 가명 HMAC 키와 vault 키는 환경변수로만 주입하고,
없으면 **기동을 거부한다.** 공개 레포에 예시 키가 박히면 그 키로 만든 가명은 전부 역산 가능하다.
`.env.example`에는 키 이름만 두고 값은 비운다.

**(e) 실데이터 반입 방지 CI.** 공개 레포에 실수로 실 PII가 들어가는 것을 막는다. PR마다
`kopii.detect`를 diff에 돌려 주민번호·전화·사번 형태가 감지되면 실패시킨다 — **이 프로젝트의
탐지기를 이 프로젝트 자신에게 쓰는 것**이므로 dogfooding이자 탐지기 회귀 테스트가 된다.
gitleaks로 일반 시크릿도 함께 훑는다.

### 1차 스코프에서 제외

- 한국어 PII NER 모델 학습 — `Detector` 인터페이스 뒤에 자리만 비워둔다
- **런타임** `min_k` 자동 레벨 상향 — 코퍼스 전역 통계 수집이 딸려온다 (§10 결정 대기).
  오프라인 평가에서 k를 재는 것(§8.2(b))과 실행 중에 레벨을 자동으로 올리는 것은 다른 기능이며,
  전자는 1차에 포함하고 후자는 제외한다.
- LLM 기반 온라인 범주화 — 비결정적이라 일관성이 깨진다 (아래 접근 3 참조)

---

## 2. 핵심 개념 — 일반화 계층 (Generalization Hierarchy)

각 PII 타입마다 추상화 레벨을 정의하고, 정책이 "어느 층까지 올릴지"를 정한다.

```
사번 25A3-0417                          이름 홍길동 (플랫폼개발팀 부장)
 L0  25A3-0417          (원본)           L0  홍길동              (원본)
 L1  [플랫폼개발팀 사원]  (팀)            L1  홍 부장             (성+직급)
 L2  [개발본부 사원]      (본부)          L2  [플랫폼개발팀 부장]  (소속+직급)
 L3  [2025년 입사자]      (연차)          L3  [부장]              (직급만)
 L4  [사번]              (완전억제)       L4  [이름_A7]           (색인 자리표시)

주민번호 900101-1234567                  주소 서울시 강남구 테헤란로 123 4층
 L1  [1990년생 남성]                      L1  서울시 강남구 테헤란로
 L2  [30대 남성]                          L2  서울시 강남구
 L3  [주민번호]                           L3  서울시
```

위 사번 예시는 조직 코드가 박힌 가상 포맷이다. 실제 대상 사번은 조직 코드가 없는 순차 채번이라
계층이 달라진다 — §4.3 참조.

레벨을 올릴수록 **재식별 위험 ↓, 의미 보존(유틸리티) ↓.** 이 트레이드오프 곡선을 측정해
레벨을 고르는 것이 이 프로젝트의 실질 산출물이다.

### 접근 비교

| 접근 | 평가 |
|---|---|
| **① 선언적 계층 + 정책 엔진** | **채택.** 조직 지식 미정 + 레벨 스윕 실험 필요 + 감사 추적, 세 조건이 모두 선언적 구조를 가리킨다. YAML만 고치면 되고 코드 변경이 없다. |
| ② 타입별 명령형 트랜스포머 | 탈락. 레벨이 코드에 박혀 정책 실험이 어렵다 — 그런데 그게 이 프로젝트의 핵심 실험이다. |
| ③ LLM이 문맥 보고 범주화 | 온라인 경로 배제. 비결정적이라 같은 사람이 문서마다 달라져 RAG 검색과 복원이 무너진다. 외부 LLM 전 마스킹에 LLM을 쓰는 것도 순환. 단, **오프라인 사전 구축**(조직명→상위 범주 매핑표 생성)에는 유용하므로 그 용도로만 남긴다. |

---

## 3. §1 — 아키텍처

PolyBed에서 이어받은 관례(도메인별 서브패키지, Pydantic 설정 스키마, 한글 docstring)를 따르되,
패키지 루트를 `kopii/`로 두어 `pip install kopii` 후 `import kopii` 로 쓰이게 한다.

```
kopii/
├── span.py               # Span, EntityKey, Replacement, AnonymizationReport
│
├── detect/               # ① 탐지 — 인터페이스 뒤에 격리
│   ├── base.py           #   Detector 프로토콜: detect(text) -> list[Span]
│   ├── regex_ko.py       #   한국 포맷 + 체크섬 (주민/외국인/사업자/법인/카드)
│   ├── gazetteer.py      #   사전 기반 (성씨, 행정구역, 조직명)
│   ├── pattern_spec.py   #   설정 주입형 커스텀 패턴 (사번 등)
│   ├── id_inducer.py     #   ID 스키마 자동 추론기          (§5 장치 ①)
│   ├── structural_id.py  #   구조적 미지 식별자 탐지        (§5 장치 ③)
│   ├── locales/ko_KR.yaml#   한국 고유 지식 (체크섬·행정구역·성씨·호칭·구분자)
│   └── ensemble.py       #   겹침 해소 + detector 우선순위
│
├── identity/             # ② 동일인 연결 — 일관성의 근거
│   ├── linker.py         #   정규화 후 span → EntityKey
│   ├── cooccurrence.py   #   앵커 인접 동반 식별자 묶기      (§5)
│   └── pseudonym.py      #   HMAC 결정적 가명 생성
│
├── hierarchy/            # ③ 일반화 계층 — 이 설계의 심장
│   ├── schema.py         #   계층 YAML Pydantic 스키마
│   ├── primitives.py     #   계층 프리미티브                (§5 장치 ②)
│   ├── registry.py       #   레벨 transform 함수 레지스트리
│   └── transforms/       #   rrn.py, address.py, employee_id.py, name.py, date.py
│
├── knowledge/            # ④ 조직 지식 — 교체 가능한 프로바이더
│   ├── base.py           #   KnowledgeProvider 프로토콜
│   ├── config_org.py     #   YAML 주입 (사번 스펙 + 조직 트리 + hr_directory)
│   └── synthetic.py      #   합성 조직도 (테스트·데모용)
│
├── policy/               # ⑤ 정책 — 타입을 어느 레벨까지 올릴지
│   ├── schema.py
│   └── engine.py         #   프로파일별 결정 + fallback
│
├── vault/                # ⑥ 가역성 — 외부 LLM 경로 전용
│   ├── base.py           #   MappingStore 프로토콜
│   ├── memory.py         #   세션 스코프 인메모리
│   └── crypto.py         #   AES-GCM 봉인
│
├── synth/                # ⑩ 합성 데이터 생성기                (§9)
│   ├── population.py     #   가상 조직·인구 (Stage 1)
│   ├── templates/        #   장르별 문서 템플릿
│   ├── document.py       #   템플릿 × 인구 → 문서 (Stage 2)
│   ├── perturb.py        #   표기 흔들림 + span offset 재계산
│   ├── inject.py         #   기존 IR 데이터셋에 PII 주입
│   └── cli.py
│
├── render.py             # ⑦ 치환 + 오프셋 재계산
├── josa.py               # ⑦-a 한국어 조사 교정            (§7)
├── restore.py            # ⑧ 외부 LLM 응답 원복
├── pipeline.py           # Anonymizer 파사드 (조립)
└── evaluation/           # ⑨ 위험·유틸리티 평가            (§8)
    ├── privacy_metrics.py   #   leak_rate, k-익명성, 프로필 유일성, 잔여 상관
    ├── utility_metrics.py   #   임베딩·검색 지표 (numpy/sklearn 자체 구현)
    ├── sweep.py             #   레벨 스윕 + 파레토 선택
    └── evaluator.py
```

### 설계 결정 4가지

**1. Detector를 인터페이스 뒤에 둔다.**
1차는 정규식+사전만 쓴다. 나중에 한국어 NER 모델이 나오면 `ModelDetector`를 추가해 앙상블에
끼우기만 하면 되고, **범주화 엔진은 한 줄도 바뀌지 않는다.** 탐지(A)와 범주화(B)를 분리해
순차 진행할 수 있는 근거가 이것이다.

**2. 지식이 없으면 위로 올린다 (fail-closed).**
`KnowledgeProvider`가 조직도를 못 주면 사번을 팀 단위(L1)로 내리지 못한다. 이때 **더 추상적인
레벨로 올라간다.** 절대 원본 노출 쪽으로 떨어지지 않는다. 지식이 미정인 지금도 안전하게 동작하고,
지식이 채워질수록 결과가 자연스러워지는 구조다.

**3. 일관성과 가역성을 분리한다.**
같은 사람이 항상 같은 값이 되는 것은 `HMAC(secret, EntityKey)`로 계산한다 — **저장소 없이
결정적**이다. Vault는 *원복이 필요할 때만* 쓴다. 따라서 RAG 인덱싱 경로는 vault 없이 돌고,
**PII 저장소가 외부 LLM 경로에만 존재**한다. 보안 표면이 크게 줄어든다.

**4. 평가 모듈이 레벨 선택의 근거를 만든다.**
레벨을 스윕하며 (재식별 위험 ↓, 의미 보존 ↑) 곡선을 뽑는다. 유틸리티 측정에 **이 레포의 임베딩
파이프라인을 재사용**한다 — 원문 임베딩 vs 범주화문 임베딩 유사도가 그대로 지표가 된다.

### 데이터 흐름

```
원문
 ├→ Detector.detect()          → [Span]                 탐지
 ├→ Ensemble.resolve()         → [Span] 겹침 제거·정렬
 ├→ Linker.link()              → [Span + EntityKey]      동일인 묶기
 ├→ PolicyEngine.decide()      → + TargetLevel           프로파일별 목표 레벨
 ├→ Hierarchy.apply()          → + Replacement           ← Knowledge 조회, 실패 시 레벨 상향
 ├→ Renderer.render()          → (범주화문, Report)       치환 + 조사 교정 + 오프셋 재계산
 └→ [가역 필요시] Vault.seal() → handle

복원:  Restorer.restore(LLM응답, handle) → 원문 복원
```

---

## 4. §2 — 계층 DSL과 정책 프로파일

### 4.1 계층 정의 `configs/hierarchy.yaml`

```yaml
version: 1

types:
  RRN:                                    # 주민등록번호
    levels:
      - { id: L0, name: 원본,        transform: identity }
      - { id: L1, name: 생년+성별,   transform: rrn.birth_year_gender }
      - { id: L2, name: 연령대+성별, transform: rrn.age_band_gender, params: { band: 10 } }
      - { id: L3, name: 완전억제,    transform: constant, params: { value: "[주민번호]" } }
    default_level: L2
```

레벨의 `requires` 필드가 fail-closed의 실제 동작부다(용례는 §4.3). 필요한 지식 프로바이더가
없으면 해당 레벨이 **unavailable** 판정을 받고 다음 후보로 넘어간다. **항상 위로만 간다.**
위 `RRN`처럼 외부 지식이 필요 없는 타입은 `requires`를 생략한다.

### 4.2 레벨 인덱스는 위험 순서가 아니다

이름 계층을 짜다 발견한 문제다.

```yaml
  NAME:
    levels:
      - { id: L0, transform: identity }
      - { id: L1, name: 성+직급,   transform: name.surname_title, requires: [hr_directory] }
      - { id: L2, name: 소속+직급, transform: name.org_title,     requires: [hr_directory, org_tree] }
      - id: L3
        name: 직급만
        transform: name.title_only
        requires: [hr_directory]
        fallback: L5                       # ← L4를 건너뜀
      - id: L4
        name: 일관 가명
        transform: name.pseudonym
        params:   { pool: ko_person_names }
        requires: []                       # ← 지식 불필요, 항상 가능
      - { id: L5, name: 색인 자리표시, transform: indexed_placeholder,
          params: { template: "[이름_{n}]" } }
    default_level: L4
```

**L4 가명이 L3 "직급만"보다 프라이버시가 약하다.** `[부장]`은 모든 부장이 한 덩어리로 뭉개져
k-익명성이 높은 반면, 가명은 일관되기 때문에 **여러 문서에 흩어진 언급을 이어 붙이는 링크
공격**에 노출된다 — 프로필이 조립된다.

그래서 레벨 인덱스 순서를 위험 순서로 가정하지 않고, **레벨마다 `fallback`을 명시**할 수 있게
한다. 미지정이면 다음 인덱스가 기본값이다.

### 4.3 EMPLOYEE_ID — 사번만으로는 소속을 알 수 없다

실제 사번 샘플을 확인한 결과 **조직 코드가 박혀 있지 않은 순차 채번**이었다. 조직도를 100%
확보해도 사번에서 팀을 파싱할 방법이 없다. 소속을 알려면 **`hr_directory`(사번→소속 조회)가
반드시 필요**하다. 초기 설계에서 `org_tree` 파싱으로 잡았던 것은 오류이며 아래처럼 정정한다.

| 축 | 근거 | 필요 지식 |
|---|---|---|
| **고용 형태** | 접두 문자 유무 = 프로젝트 vs 정규직 | 없음 ✅ |
| **채번 블록** | 상위 자릿수 대역 | 없음 ✅ |
| **소속(팀/파트)** | — | `hr_directory` 필수 ❌ |

고용 형태는 그 자체로 민감한 축(계약 형태 노출)이라 오히려 유용한 범주화 단위다.

```yaml
  EMPLOYEE_ID:
    induce_from: data/employee_ids.txt        # variants·블록 경계 자동 추론 (§5 장치 ①)
    levels:
      - { id: L0, name: 원본, transform: identity }
      - { id: L1, name: 소속 팀,   transform: employee_id.org_unit, params: { depth: team },
          requires: [hr_directory], fallback: L4 }
      - { id: L2, name: 소속 본부, transform: employee_id.org_unit, params: { depth: division },
          requires: [hr_directory], fallback: L4 }
      - { id: L3, name: 채번 블록, transform: employee_id.number_block,
          params: { keep_digits: auto }, requires: [] }
      - { id: L4, name: 고용 형태만, transform: employee_id.variant_only, requires: [] }
      - { id: L5, name: 완전억제,   transform: constant, params: { value: "[사번]" } }
    default_level: L4
    min_k: 5
```

`L1 → fallback: L4`인 이유: L1(소속)과 L3(채번 블록)은 **서로 다른 축**이라 어느 쪽이 더
안전한지 비교되지 않는다. fail-closed 원칙상 비교 불가능하면 두 축을 모두 덮는 위쪽으로 보낸다.
현재는 `hr_directory`가 없으므로 모든 사번이 L4(고용 형태)로 떨어진다.

**L3(채번 블록)은 기본 체인에서 제외한다.** 순차 채번이면 채번 블록이 입사 시기를 간접 노출하는데,
그 상관관계가 확인되지 않았다. 보수적으로 뺀다.

### 4.4 NICKNAME — 사내 닉네임도 식별자다

사내에서 사람을 지목하는 영문 닉네임은 PII다.

```yaml
  NICKNAME:
    levels:
      - { id: L0, transform: identity }
      - { id: L1, name: 일관 가명, transform: nickname.pseudonym,
          params: { pool: en_nicknames }, requires: [] }
      - { id: L2, name: 색인 자리표시, transform: indexed_placeholder,
          params: { template: "[닉네임_{n}]" } }
    default_level: L1
```

### 4.5 탐지 쪽 관찰 — 얻은 것과 위험

**얻은 것 ① 호칭 접미사는 강력한 이름 경계 신호다.**
`(?<![가-힣])([가-힣]{2,4})님(?![가-힣])` 은 사내 문서에서 정밀도가 매우 높다. 한국어 NER 모델
없이도 이름 recall을 상당히 확보할 수 있다는 뜻이며, 1차 스코프 판단(규칙 우선)을 뒷받침한다.

**얻은 것 ② `이름(닉네임) · 사번` 동시 출현이 linker의 최고 신호다.** → §5 앵커 동반 식별자.

**위험: 순수 숫자 사번을 무조건 잡으면 오탐이 폭발한다.**
7자리 숫자는 형태상 금액·수량·날짜·전화번호 조각과 구별되지 않는다. 세 조건을 겹친다.

1. 추론된 채번 블록 접두로 한정
2. 문맥 앵커 — 호칭/닉네임 인접, 또는 `사번`·`사원번호`·`구성원` 키워드 근처
3. 앵커 없는 단독 숫자는 **낮은 confidence로 표시만** 하고, 정책이 `suppress_low_confidence: true`면 억제

접두 문자가 있는 variant는 형태가 명확해 앵커 없이도 잡는다.

### 4.6 조직 지식 `configs/knowledge.yaml`

```yaml
hr_directory:                 # 사번 → 소속 조회 (현재 비어 있음)
  source: null

org_tree:
  - code: A
    name: 개발본부
    level: division
    children:
      - { code: A3, name: 플랫폼개발팀, level: team }
```

지식이 확보되면 **이 파일만 채우면 된다. 코드 변경은 없다.** 그 전까지는 `synthetic.py`의
합성 조직도로 테스트와 데모를 돌린다.

### 4.7 정책 프로파일 `configs/policy.yaml`

```yaml
profiles:
  external_llm:                    # 외부 LLM 호출 전 마스킹
    reversible: true
    vault:            { scope: session, ttl: 3600 }
    pseudonym_scope:  session      # 세션 내 일관, 세션 간 무관
    rules:
      RRN:         L3
      EMPLOYEE_ID: L4
      NAME:        L5              # 색인 자리표시 — 복원 신뢰도 우선 (§7.4)
      NICKNAME:    L2
      ADDRESS:     L2
      PHONE:       L3
      EMAIL:       L4
    restore_policy:
      strategy:        exact_then_partial
      on_unrestored:   report
    unknown_type: suppress         # 미지의 타입은 억제 (fail-closed)

  rag_index:                       # 사내 검색 인덱싱
    reversible: false              # vault 자체를 만들지 않음
    pseudonym_scope: global        # 교차 문서 검색을 위해 전역 일관
    rules:
      RRN:         L3
      EMPLOYEE_ID: L4
      NAME:        L2              # [플랫폼개발팀 부장] — 검색되는 의미 유지
      NICKNAME:    L1              # 전역 일관 가명
      ADDRESS:     L2
    unknown_type: suppress
```

두 프로파일은 **의도적으로 다르다.** `pseudonym_scope`가 실제 트레이드오프다. RAG는 특정 인물
관련 문서가 교차 검색돼야 하므로 전역 일관성이 필요하고 그만큼 링크 공격에 노출된다. 외부 LLM은
한 세션만 일관하면 충분하므로 `session`으로 위험을 끊는다.

### 4.8 기존 설정 체계와의 접합

`kopii/config/schema.py`에 `KoPIIConfig`를 둔다. PolyBed의 `PipelineConfig` 관례(Pydantic
모델 + `model_validator` 교차 검증)를 그대로 따르되 타입은 KoPII가 자체 정의한다.

```yaml
kopii:
  hierarchy: configs/hierarchy.yaml
  knowledge: configs/knowledge.synthetic.yaml
  policy:    configs/policy.yaml
  profile:   rag_index
```

---

## 5. 일반화 장치 — 특정 조직에 오버피팅하지 않기

초기 설계에는 특정 회사의 사번 대역·호칭·표기 관습이 하드코딩돼 있었다. 아래 장치로 걷어낸다.

| 하드코딩된 것 | 일반화 방식 |
|---|---|
| 사번 정규식 | **ID 스키마 자동 추론** — 사번 값 리스트에서 포맷 유도 |
| 채번 블록·`keep_digits` | **자릿수별 엔트로피**로 구조/일련 경계 자동 검출 |
| 손으로 나열한 레벨 YAML | **계층 프리미티브 조합** — 레벨 자동 생성·자동 정렬 |
| 특정 호칭 접미사 | 호칭 사전 + 로케일 팩 |
| 특정 괄호 표기 | **앵커 인접 동반 식별자** 일반 규칙 |
| 알려진 타입만 탐지 | **구조적 미지 식별자** 탐지 |

### 장치 ① — ID 스키마 자동 추론기 (`IdSchemaInducer`)

사번 **값 리스트만** 주면(이름 불필요 → 프라이버시 부담이 낮다) 포맷을 유도한다.

**1단계 — shape 클러스터링.** 문자 클래스 시퀀스로 정규화해 variant를 자동 발견한다.

```
2304118 → D7          ┐
2305772 → D7          ├─ variant A
2309460 → D7          ┘
K530918 → L1·D6       ─── variant B
```

**2단계 — 자릿수별 엔트로피로 구조/일련 경계 검출.**

```
자리      1     2     3     4     5     6     7
H(bits) 0.00  0.50  1.35  2.42  2.95  2.75  2.95
        └──── 구조적 ────┘ └──────── 일련번호 ────────┘
```

상위 자릿수는 엔트로피가 바닥이므로 **채번 블록**, 하위는 포화되므로 **일련번호**. 경계 자릿수는
후보로 남긴다.

**3단계 — 레벨 자동 생성 + k 실측.** 접두 길이가 그대로 일반화 레벨이 되고, **각 레벨의 그룹
크기를 샘플에서 직접 센다.**

```
prefix=3  → k=3, k=5, k=1   ← k=1 위험 노출
prefix=2  → k=8, k=1
prefix=0  → k=9
```

이 k 실측이 **`min_k`를 코퍼스 통계 없이 해결**한다. 사번 리스트만으로 계산되므로 실시간
경로에서도 쓸 수 있다. `min_k: 5`면 위 예에서 `prefix=3`은 자동 탈락하고 `prefix=2`가 선택된다.

표본이 수십 개 수준이면 엔트로피 추정이 거칠다. 부족하면 inducer가 `low_confidence`를 반환하고
정책이 가장 보수적인 레벨로 고정한다.

### 장치 ② — 계층 프리미티브

타입마다 레벨을 손으로 나열하는 대신 **파라미터를 갖는 프리미티브**를 고른다. 레벨은 파라미터
스윕으로 자동 생성되고 **자동으로 단조 정렬**된다.

```
numeric_prefix(n)     n을 줄이며 자동 체인
date_granularity(g)   day → month → quarter → year → decade
geo_level(g)          건물 → 도로 → 동 → 구 → 시 → 도
bucket(w)             수치 구간 폭을 넓히며
lookup(src, depth)    외부 지식 조회 (팀 → 본부 → 전사)
pseudonym(pool,scope) 일관 가명
suppress(label)       억제
```

타입 정의가 이렇게 줄어든다.

```yaml
types:
  EMPLOYEE_ID:
    induce_from: data/employee_ids.txt
    generalize:
      - lookup(hr_directory, [team, division])
      - numeric_prefix(auto)
      - variant_only
      - suppress("[사번]")
    min_k: 5
```

**새 PII 타입이 생기면 프리미티브만 고르면 된다.** 계약번호·주문번호·사내 시스템 ID가 전부
`induce_from` + `numeric_prefix(auto)` 조합으로 커버된다.

### 장치 ③ — 구조적 미지 식별자 탐지 (`StructuralIdDetector`)

어떤 사전도 못 잡는 새 식별자는 항상 생긴다. recall이 무너지는 지점이다. 타입을 몰라도
**"이건 식별자다"** 를 판정한다. 신호는 타입 독립적이다.

- 문자 클래스가 혼합되고 길이가 문서 내에서 일정한 토큰
- 문서 내 반복 출현하되 자연어 어휘 사전에 없음
- 문자 단위 엔트로피가 자연어 대비 높음
- **알려진 PII span 근처에 반복 등장**

여기서 잡힌 것은 타입이 `UNKNOWN_ID`가 되고 정책의 `unknown_type: suppress`가 받아 억제한다.
**모르는 것도 일단 막고 나중에 타입을 붙인다.**

### 앵커 동반 식별자

특정 표기 대신 보편 원리를 쓴다: **확정된 PII span에 구분자로 인접한 토큰은 같은 사람의 다른
식별자일 가능성이 높다.**

```
홍길동님(GILDONG) · 2304118      ┐
홍길동 / GILDONG / 2304118        ├─ 전부 같은 규칙으로 커버
홍길동  GILDONG  2304118          │   구분자: ( ) · / - | 탭 쉼표 공백
[홍길동] GILDONG, 2304118         ┘
```

구분자 집합과 윈도우 크기만 로케일 팩 파라미터다. 여기서 묶인 span들이
`identity/cooccurrence.py`로 넘어가 하나의 EntityKey가 된다.

### 로케일 팩

한국 고유 지식을 `detect/locales/ko_KR.yaml`로 분리한다 — 주민번호·사업자번호 체크섬, 행정구역
계층, 성씨 사전, 호칭 사전(`님 씨 선임 책임 프로 매니저 팀장 부장 …`), 구분자 관습.
**엔진 코드에 한국 지식이 남지 않는다.**

### 대가

`IdSchemaInducer`와 `StructuralIdDetector`는 실제 구성요소라 1차 스코프가 커진다. 대신
`knowledge.yaml`을 사람이 쓰지 않아도 되고, 레벨을 사람이 정렬하지 않아도 되며, `min_k`가
데이터 기반으로 작동한다. 1차에는 inducer를 **최소 버전**(shape 클러스터링 + 엔트로피 세그먼트
+ k 실측)으로만 넣는다. 자동 호칭 발견 같은 것은 뺀다.

---

## 6. §3-a — EntityKey: "같은 사람"의 정의

일관성의 단위다. 여기가 틀리면 아래 전부가 틀린다.

```
정규화:  "홍길동님"  → 홍길동             (호칭 제거)
         "GILDONG"   → gildong            (케이스 폴딩)
         "2304118"   → FULLTIME:2304118   (variant 접두)

키 선정: 공동출현으로 묶인 span 집합에서 가장 강한 식별자를 canonical로
         EMPLOYEE_ID > EMAIL > NICKNAME > NAME
```

강한 식별자가 하나라도 붙으면 그것이 키가 되고, 이름만 단독 등장한 span은 **문서 스코프 안에서만**
이름 기반 키를 쓴다.

두 방향의 오류가 비대칭이기 때문이다.

| 오류 | 결과 | 심각도 |
|---|---|---|
| **과잉 병합** (동명이인 2명 → 1명) | A의 문장이 B에게 귀속 → 유틸리티 손상 | 중 |
| **과소 병합** (같은 사람 → 2명) | 문서마다 다른 가명 → **RAG 검색 붕괴, 복원 실패** | 높음 |

기본은 병합 쪽으로 기울이되, 이름 단독 키를 **문서 스코프로 제한**해 과잉 병합이 코퍼스 전체로
번지지 않게 막는다. 사번이 붙은 언급은 전역에서 안전하게 묶인다.

---

## 7. §3-b — 결정적 가명, 조사 교정, 가역성

### 7.1 결정적 가명 — 저장소 없이

```
pseudonym(key) = pool[ HMAC-SHA256(secret, scope_salt ‖ entity_key) mod |pool| ]

scope_salt:  global   → ""            (코퍼스 전역 일관)
             session  → session_id     (세션 간 링크 차단)
             document → doc_id         (문서 간 링크 차단)
```

`secret`은 환경변수/KMS로 주입한다. **회전하면 전체 가명이 재배정**되므로 이미 인덱싱된 코퍼스가
있으면 회전은 재색인을 동반한다 — 운영 비용으로 문서화한다.

### 7.2 가명 충돌

풀 5,000개, 문서 하나에 인물 50명이면 생일 문제로 충돌 확률이 약 22%다. 두 사람이 같은 가명을
받으면 과잉 병합과 동일한 손상이 난다.

해소는 결정성을 깨지 않아야 하므로 재배정이 아니라 **풀 자체를 조합으로 키운다** — 성 200 ×
이름 3,000 = 60만 조합이면 5만 명 코퍼스에서도 충돌이 무시할 수준이다. 인덱스 +1 방식의 open
addressing은 스코프 밖에서 결정성이 깨지므로 쓰지 않는다.

### 7.3 한국어 조사 — 여기서 실제 버그가 난다

치환은 문자열 교체가 아니다. 받침이 바뀌면 뒤따르는 조사가 틀린다.

```
"홍길동은 …"   →  가명 박정호    →  "박정호은 …"  ✗   →  "박정호는 …"  ✓
"2304118이 …"  →  "[정규직]이 …"  ✗               →  "[정규직]은 …" ✓
"김민수와 …"   →  "[부장]와 …"    ✗               →  "[부장]과 …"  ✓
```

교정 대상: `은/는` `이/가` `을/를` `과/와` `아/야` `(으)로` `(이)라` `(이)나` `(이)며`.
치환문 끝 음절의 종성으로 결정되며, `[사번]` 같은 대괄호 자리표시는 **닫는 괄호가 아니라 그 앞
음절**을 본다.

사소해 보이지만 영향이 크다 — 외부 LLM 경로에서는 입력 문장이 비문이 되어 응답 품질이 떨어지고,
RAG 경로에서는 색인 문장이 망가진다. 규칙이 닫혀 있어 테이블 + 단위 테스트로 완결된다.

### 7.4 Vault와 복원 — 정책 정정

```
seal:    handle = AES-GCM(vault_key, {entity_key → [원본 표면형], replacement})
                  TTL 후 자동 폐기, reversible=false 프로파일은 아예 생성하지 않음
restore: LLM 응답에서 replacement를 찾아 원본으로 역치환
```

문제는 **LLM이 가명을 그대로 돌려주지 않는다**는 것이다.

```
보낸 것:  박정호 부장이 …
받는 것:  "박정호님께서", "박 부장", "정호 씨", "Mr. Park", "박정호(부장)"
                └─ 정확 일치 실패 → 복원 누락 → 원문 복구 불가
```

`[이름_3]` 같은 **색인 자리표시는 LLM이 변형하지 않는다** — 토큰이 낯설어 그대로 흘려보낸다.
반대로 자연스러운 가명은 LLM이 한국어 문법에 맞춰 활용해버린다.

따라서 `external_llm` 프로파일이 `reversible: true`이면서 복원 신뢰도가 가장 낮은 L4(가명)를
고르는 것은 자기모순이다. **`NAME`의 기본값을 L5(색인 자리표시)로 정정한다.**

자연스러움이 필요한 태스크(문체 교정, 요약문 가독성)에서는 가명이 유리하므로 프로파일 옵션으로
남기되 기본값은 자리표시로 둔다. `on_unrestored: report`는 조용한 복원 실패를 막는 장치다 —
100개를 봉인했는데 92개만 복원됐다면 그 사실이 반드시 보여야 한다.

### 7.5 `pseudonym_scope: global`의 실제 노출면

`rag_index` 프로파일의 규칙을 보면 `NAME: L2`, `EMPLOYEE_ID: L4`, `ADDRESS: L2`, `RRN: L3` —
**가명을 쓰는 타입이 없다.** 전부 범주 자리표시로 떨어진다. 즉 `global` 스코프가 실제로 적용되는
것은 기본값이 L1(가명)인 `NICKNAME` 하나뿐이다.

닉네임은 사내에서 사람을 지목하는 검색 키라 일관성이 검색 품질에 직결되고 노출면이 한 타입뿐이므로,
**전역 일관을 유지한다.** 이 결정의 타당성은 §9의 평가 모듈에서 측정 가능한 형태로 검증한다.

---

## 8. §4 — 평가 모듈

레벨 선택은 취향이 아니라 측정 결과여야 한다. 이 절은 그 측정을 정의한다.

### 8.1 평가가 답해야 하는 질문

| # | 질문 | 축 |
|---|---|---|
| Q1 | 안 잡힌 PII가 남아 있나? | 프라이버시 — 탐지 |
| Q2 | 잡아서 범주화한 것이 여전히 재식별되나? | 프라이버시 — 범주화 |
| Q3 | 의미가 얼마나 남았나? | 유틸리티 |

Q1과 Q2는 다른 실패다. Q1은 탐지기가 놓친 것(원본이 그대로 노출), Q2는 범주화가 약한 것
(`[110번대 정규직]`이 3명뿐이라 좁혀짐). 지표도 대응 방식도 다르므로 분리해서 잰다.

### 8.2 축 1 — 프라이버시 위험

**(a) Leak rate — 탐지 실패 (Q1)**

합성 코퍼스는 정답 span을 알고 있으므로 entity-level로 직접 잰다.

```
leak_rate      = 미탐 PII span 수 / 전체 PII span 수        (타입별 breakdown 필수)
false_positive = 오탐 span 수 / 탐지 span 수
```

**recall을 precision보다 크게 가중한다.** 오탐은 문장이 조금 뭉개지는 손해지만, 미탐은 개인정보
유출이다. PolyBed의 PII 학습 설정이 **entity-level micro F5(beta=5, recall 25배 가중)** 를
쓰고 있으므로 같은 기준을 채택해 두 레포의 수치를 비교 가능하게 둔다.

**(b) k-익명성 — 범주화 강도 (Q2)**

익명화 결과에서 같은 치환값을 받은 서로 다른 EntityKey의 수가 그 그룹의 k다.

```
k(replacement) = |{ entity_key : render(entity_key) == replacement }|

보고: k의 분포(min / p5 / median), 그리고 k < min_k 인 그룹의 목록
```

`k = 1`인 그룹은 곧 재식별이다 — `[152번대 정규직]`이 코퍼스에 한 명뿐이면 익명화가 아니다.
이 지표가 §5 장치 ①의 k 실측과 같은 정의이므로, 추론기가 고른 레벨이 실제로 목표 k를
달성했는지 사후 검증하는 역할도 한다.

**(c) 프로필 유일성 — 링크 가능성 (Q2)**

k-익명성은 한 속성만 본다. 여러 속성을 결합하면 다시 좁혀진다.

```
각 EntityKey에 대해 익명화 코퍼스 전체에서 수집 가능한 속성 튜플을 만든다
  (소속, 직급, 연령대, 지역, 등장 문서 수, …)
profile_uniqueness = 같은 튜플을 갖는 EntityKey가 1명뿐인 비율
```

이 지표가 §7.5의 `pseudonym_scope: global` 결정을 **측정 가능한 형태로** 검증한다. 전역 일관
가명은 문서 간 속성 결합을 가능하게 하므로, `global`과 `document` 스코프로 각각 돌려
`profile_uniqueness` 차이를 보면 링크 위험의 실제 크기가 나온다. 차이가 무시할 수준이면
전역 일관을 유지하고, 크면 스코프를 좁힌다.

**(d) 잔여 상관**

일반화 후에도 원본과 단조 관계가 남으면 순서 정보가 새어나간다 — 순차 채번 사번을 채번 블록으로
일반화했을 때 블록 순서가 곧 입사 순서인 경우다.

```
residual_corr = spearman(원본값 순위, 치환값 순위)   # 타입별, |ρ|가 낮을수록 안전
```

§4.3에서 L3(채번 블록)을 기본 체인에서 뺀 판단을 이 지표로 사후 검증한다.

### 8.3 축 2 — 유틸리티

원문과 익명화문을 **같은 인코더로 임베딩해서 비교**한다. 지표 자체는 표준적이라 numpy와
scikit-learn만으로 구현한다 (§1.3-a).

**(a) 의미 보존 — alignment & uniformity (Wang & Isola, 2020)**

positive 쌍을 `(원문, 익명화문)`으로 두면 이 두 지표가 그대로 목적에 맞는다.

```python
embedding_quality(
    embeddings_a=encode(원문들),        # positive 쌍의 한쪽
    embeddings_b=encode(익명화문들),     # 다른 한쪽
)
# → {"alignment": ..., "uniformity": ...}
```

- **alignment** (낮을수록 좋음) — 익명화가 문장 의미를 얼마나 밀어냈는지. 이것이 곧 semantic drift.
- **uniformity** (낮을수록 좋음) — **붕괴 감지기로 쓴다.** 모든 이름이 `[이름]` 하나로 뭉개지면
  서로 다른 문장들이 임베딩 공간에서 한 점으로 모인다. 익명화문의 uniformity가 원문 대비 크게
  나빠졌다면 범주화가 문서를 구별 불가능하게 만든 것이다. **alignment만 보면 이 실패를 놓친다** —
  모든 문장을 똑같이 조금씩 밀면 alignment는 좋게 나온다.

**(b) 검색 품질 delta — RAG 경로의 실질 지표**

동일한 IR 평가를 인덱스만 바꿔 두 번 돌린다.

```
쿼리:   원문 (사용자는 원문 표현으로 질문한다)
인덱스: ① 원문 코퍼스   ② 익명화 코퍼스
지표:   ndcg@10, mrr, recall@k   →   Δ = anon - orig
```

한국어 사내 IR 벤치마크가 없다는 문제는 **PII 주입**으로 푼다. 기존 공개 IR 데이터셋 문서에
합성 PII를 심고 relevance 라벨은 그대로 둔다. 라벨이 불변이므로 성능 차이가 순수하게 익명화
효과가 된다. 합성 코퍼스 자체의 QA 쌍(§9)이 준비되면 그쪽으로 옮긴다.

**(c) 다운스트림 delta — 클러스터링**

카테고리 라벨이 있는 문서 집합에서 익명화 전후 V-measure/NMI/ARI를 비교한다
(`sklearn.metrics` 직접 사용). 문서 주제 판별력이
익명화로 손상됐는지 본다.

**(d) 외부 LLM 경로 전용 — 응답 품질과 복원**

```
restore_rate   = 복원된 handle 수 / 봉인된 handle 수      (§7.4 on_unrestored 로그 기반)
answer_drift   = cos( encode(원문으로 받은 답), encode(익명화문으로 받은 답 → 복원) )
```

`restore_rate`는 §7.4에서 `NAME` 기본값을 가명 → 색인 자리표시로 바꾼 판단의 검증 지표다.
두 레벨로 각각 돌려 격차를 확인한다.

### 8.4 레벨 스윕 — 이 모듈의 산출물

**조합 폭발을 피한다.** 6개 타입 × 5레벨을 전조합하면 15,625회다. 대신 **타입별 독립 스윕**
(one-at-a-time)을 쓴다 — 다른 타입은 프로파일 기본값에 고정하고 한 타입만 L0..L5를 훑는다.
6 × 5 = 30회로 끝난다.

타입 간 상호작용(이름을 억제하면 사번의 재식별력이 달라지는 효과)은 무시한다. 대부분의 타입이
문장 안에서 독립적으로 등장하므로 1차 근사로 충분하고, 상호작용이 실제로 관측되면 그때
해당 쌍만 2차원으로 훑는다.

**레벨 선택 규칙 — 제약 최적화.**

```
argmax  utility(level)
 level
subject to   k(level) ≥ min_k
             leak_rate ≤ 목표치
```

프라이버시를 **제약**으로, 유틸리티를 **목적함수**로 둔다. 반대로 두면(위험 최소화) 항상 완전
억제가 이긴다. 이 규칙이 `policy.yaml`의 기본 레벨에 근거를 부여한다.

산출물:

```
output/anonymize/sweep/
├── curve_<TYPE>.json      # 레벨별 (privacy, utility) 좌표
├── pareto.md              # 파레토 프론티어 + 제약 만족 레벨 추천
└── figures/*.svg          # 위험–유틸리티 곡선
```

### 8.5 코드 접합

```
kopii/evaluation/
├── privacy_metrics.py   # leak_rate, k_anonymity, profile_uniqueness, residual_corr
├── utility_metrics.py   # alignment/uniformity, IR 지표, 클러스터링 delta
├── sweep.py             # 레벨 스윕 러너 + 파레토 선택
└── evaluator.py         # KoPIIEvaluator 파사드
```

**의존성을 얇게 유지한다.** `utility_metrics.py`가 쓰는 것은 numpy, scikit-learn,
sentence-transformers뿐이다. 알고리즘은 PolyBed의 대응 구현과 수치가 일치하도록 맞추고,
그 일치를 골든 테스트로 고정한다 — 두 레포의 실험 결과를 나란히 놓고 비교할 수 있어야 한다.

설정은 `KoPIIConfig` 아래에 붙인다.

```yaml
kopii:
  hierarchy: configs/hierarchy.yaml
  knowledge: configs/knowledge.synthetic.yaml
  policy:    configs/policy.yaml
  profile:   rag_index

  evaluation:
    corpus:    data/synthetic_ko.jsonl
    encoder:   BAAI/bge-m3            # 한국어 인코더, model.name과 별개로 고정
    profiles:  [external_llm, rag_index]
    sweep:
      types:  [NAME, EMPLOYEE_ID, ADDRESS, NICKNAME]
      levels: all
    privacy:
      min_k: 5
      target_leak_rate: 0.01
    utility:
      ir_benchmark: data/ir_pairs.jsonl
      k_values: [1, 5, 10]
```

### 8.6 1차 성공 기준 (제안)

| 지표 | 목표 | 비고 |
|---|---|---|
| `leak_rate` (구조화 PII: 주민·전화·이메일·카드) | ≤ 1% | 체크섬으로 검증되므로 달성 가능 |
| `leak_rate` (이름·닉네임) | ≤ 10% | 규칙 기반 한계. 2차 NER 모델의 개선 여지로 남긴다 |
| `k` (모든 출력 그룹) | ≥ 5 | 미달 시 `policy.yaml`의 해당 타입 기본 레벨을 올린다 — 런타임 자동 상향이 아니라 설정 조정 |
| `ndcg@10` 상대 하락 | ≤ 5% | `rag_index` 프로파일 |
| `restore_rate` | ≥ 98% | `external_llm` 프로파일 |

### 8.7 이 평가의 한계

**합성 코퍼스로 잰 `leak_rate`는 낙관적이다.** 생성기가 만든 PII는 생성기가 아는 형태이고,
탐지기도 같은 형태를 안다. 실제 문서의 표기 흔들림(오타, 줄바꿈 끼임, 표 안의 값, OCR 잡음)은
재현되지 않는다.

완화책은 **실문서 소량 수동 라벨링**이다. 100~200 문서를 손으로 라벨링해 합성 코퍼스 점수와
실문서 점수의 격차를 재고, 그 격차를 보정 계수로 기록한다. 1차 스코프 밖이지만 실서비스 투입
전에는 반드시 필요하다 — 이 문서에 명시적 선행 조건으로 남긴다.

---

## 9. §5 — 합성 데이터 생성기

§8의 모든 지표가 이 코퍼스 위에서 계산된다. 코퍼스가 부실하면 측정이 전부 무의미해지므로,
지표에서 요구사항을 역산해 설계한다.

### 9.1 지표가 코퍼스에 요구하는 것

| §8 지표 | 코퍼스에 필요한 것 |
|---|---|
| `leak_rate` | span 단위 정답 라벨 (offset + 타입) |
| `k`-익명성 | **같은 사람이 여러 문서에 반복 등장**, 현실적인 인구 분포 |
| `profile_uniqueness` | 사람마다 속성 튜플 (소속·직급·연령대·지역) |
| `residual_corr` | 사번이 **실제 채번 규칙**을 따를 것 (순서 정보가 존재해야 잴 수 있다) |
| 검색 품질 delta | relevance 라벨이 붙은 쿼리–문서 쌍 |
| alignment / uniformity | 문장 다양성 (템플릿이 단조로우면 붕괴가 안 보인다) |

**핵심:** 이건 "PII가 뿌려진 문장 목록"이 아니다. 위 절반이 사람 단위 일관성을 요구하므로
**가상 조직 하나를 통째로 만들어야 한다.** 문서를 먼저 만들고 PII를 뿌리는 순서로는
`k`도 `profile_uniqueness`도 정의되지 않는다.

### 9.2 2단계 생성 — 인구 먼저, 문서 나중

```
Stage 1  가상 조직 생성  →  population.jsonl   사람 N명 + 조직 트리 + 채번된 사번
Stage 2  문서 생성       →  corpus.jsonl       템플릿 × 인구 샘플링
```

Stage 1을 분리하면 세 가지가 따라온다.

1. 같은 사람이 여러 문서에 **일관되게** 등장한다 → `k`·`profile_uniqueness` 측정 가능
2. `hr_directory` 정답을 갖고 있다 → 지식 프로바이더가 **있는 경우와 없는 경우**를 같은 코퍼스로 비교 실험
3. **생성기가 곧 `IdSchemaInducer`의 정답지가 된다** — 채번 블록 경계를 아는 상태로 만들었으므로,
   추론기가 그 경계를 맞히는지 직접 채점할 수 있다 (§9.8)

인구 생성 파라미터:

```yaml
population:
  size: 2000
  seed: 42
  org:
    divisions: 5
    teams_per_division: [3, 8]        # 범위에서 샘플링
    titles: [사원, 선임, 책임, 수석, 팀장, 부장]
  employee_id:
    scheme: sequential_block          # 순차 채번 (블록 = 입사 연도군)
    variants:
      - { id: FULLTIME, weight: 0.9, format: "{block}{serial:05d}" }
      - { id: PROJECT,  weight: 0.1, format: "K{serial:06d}" }
  locale: ko_KR
```

`scheme`을 바꿔 **다른 조직 포맷**(조직 코드 내장형 `25A3-0417` vs 순차형)을 만들 수 있어야 한다.
§5 장치 ①의 일반화 주장은 그렇게만 검증된다 — 한 포맷에서만 동작하면 오버피팅을 코퍼스로
옮겨놓은 것에 불과하다.

### 9.3 문서 생성 — 장르와 표기 흔들림

장르마다 PII 밀도와 표기 관습이 다르므로 장르를 나눈다.

| 장르 | PII 밀도 | 특징 |
|---|---|---|
| 사내 메일 | 중 | 서명 블록에 이름·연락처·소속 집중 |
| 회의록 | 높음 | 참석자 명단에 `이름(닉네임) · 사번` 나열 |
| 인사 공지 | 높음 | 소속·직급 변경, 사번 다수 |
| 결재 문서 | 낮음 | 표 안에 사번·금액 혼재 → **오탐 시험대** |
| 채팅 로그 | 중 | 호칭 생략, 이름만 단독 등장 |
| 이슈 티켓 | 낮음 | URL·계정명 위주 |

**표기 흔들림 주입(`perturb.py`)** 이 §8.7에서 지적한 "합성은 낙관적"이라는 한계를 부분적으로
좁힌다. 각 변형은 확률 파라미터를 갖는다.

```
호칭 변형      님 / 씨 / 선임 / 책임 / 직급 생략
이름 부분 표기  성만 · 이름만 · 성+직급
구분자 변형    ( ) · / - | 탭 쉼표 공백
줄바꿈 끼임    표 셀 경계에서 사번이 잘림
자모 오타      1글자 치환
공백 삽입      010 - 0000 - 0000
```

**정답 span offset은 변형 후 텍스트 기준으로 재계산해야 한다.** 변형이 span 내부를 건드리면
경계가 밀리고, 여기서 틀리면 `leak_rate`가 통째로 틀린다. 구현상 가장 회귀가 잘 나는 지점이며
§10의 라운드트립 테스트가 이걸 막는다.

### 9.4 라벨 스키마 — 세밀하게 달고 거칠게 내린다

익명화 엔진이 쓰는 타입 집합과 기존 NER 학습이 쓰는 Kaggle 7-type이 다르다. 계층이 타입마다
다르므로 익명화는 세밀한 타입이 필요하고, Kaggle 7-type에는 `RRN`·`EMPLOYEE_ID`·`NICKNAME`이
없다 — 전부 `ID_NUM` 하나로 뭉개져 있다.

```
생성기 라벨(세밀)   RRN, EMPLOYEE_ID, NAME, NICKNAME, PHONE, EMAIL,
                    ADDRESS, ACCOUNT, CARD, DOB, URL, USERNAME
                          │
                          ↓  ENTITY_MERGE_MAP  (세밀 → 거침, 손실 매핑)
                          │
Kaggle 7-type       NAME_STUDENT, EMAIL, USERNAME, ID_NUM,
                    PHONE_NUM, URL_PERSONAL, STREET_ADDRESS
```

**생성기는 항상 세밀한 쪽으로 단다.** 세밀 → 거침은 손실 없이 내려가지만 반대는 복구가 안 된다.
`ENTITY_MERGE_MAP`은 KoPII가 `kopii/labels.py`에 자체 보유한다 (§1.3-a). PolyBed의 매핑을
출발점으로 삼되 한국 타입(`RRN`·`EMPLOYEE_ID`·`NICKNAME`)을 추가하고, Kaggle 7-type으로
내리는 경로를 유지해 **외부 PII 데이터셋(Nemotron, AI4Privacy 등)이 그대로 물리게** 한다.
매핑이 공개 자산이 되므로 새 소스 데이터셋의 엔티티명을 기여받기도 쉬워진다.

### 9.5 출력 포맷

표준 JSONL로 낸다. `datasets.load_dataset("json", …)`과 PolyBed의 JSONL 로더가 모두
그대로 읽는 형태이며, 별도 로더를 요구하지 않는다.

```json
{
  "id": "doc_00417",
  "genre": "meeting_note",
  "text": "…",
  "spans": [
    {"start": 12, "end": 19, "type": "EMPLOYEE_ID",
     "surface": "2304118", "entity_key": "p_0042"}
  ],
  "meta": {"person_ids": ["p_0042", "p_0117"], "template": "mtg_attendees_v2"}
}
```

`entity_key`가 **정답 EntityKey**다. 이것이 붙어 있으면 §6 linker의 성능도 직접 잴 수 있다 —
예측 클러스터와 정답 클러스터를 조정 랜드 지수(ARI)로 비교하면 된다. §8에 linker 지표가
빠져 있었는데, 여기서 채운다.

```
linker_ari = adjusted_rand_score(정답 entity_key 클러스터, 예측 EntityKey 클러스터)
```

과소 병합이 과잉 병합보다 심각하다는 §6의 비대칭을 반영해 **클러스터 순도와 완전성을 따로**
보고한다 (ARI 하나로는 두 방향이 구분되지 않는다).

### 9.6 공개 데이터 접합

| 소스 | 용도 | 취급 |
|---|---|---|
| AI Hub 한국어 데이터 | 실제 한국어 문장 분포 확보 | **레포에 커밋 금지** — 재배포 제한. 다운로드 스크립트 + 체크섬만 버전 관리 |
| 공개 IR 데이터셋 | §8.3(b) 검색 delta 측정 | `inject.py`가 population에서 뽑아 문서에 PII를 심고, relevance 라벨은 그대로 둔다 |
| `nvidia/Nemotron-PII` 등 영어 PII 데이터셋 | §9.4 매핑으로 물림 | 2차 NER 사전학습용으로만. **한국어 평가에는 쓰지 않는다** |

생성 산출물도 레포에 커밋하지 않는다. `data/`를 gitignore에 넣고, **시드 고정으로
재현**한다 — 합성 데이터라도 실제 인물과 우연히 일치할 수 있고, 무엇보다 코퍼스 파일을 커밋하면
diff가 무의미해진다.

### 9.7 코드 위치

```
kopii/synth/
├── population.py     # 가상 조직·인구 생성 (Stage 1)
├── templates/        # 장르별 문서 템플릿 (YAML)
├── document.py       # 템플릿 × 인구 → 문서 (Stage 2)
├── perturb.py        # 표기 흔들림 + span offset 재계산
├── inject.py         # 기존 IR 데이터셋에 PII 주입
└── cli.py            # python -m kopii.synth --config …
```

```yaml
# configs/synth.yaml
population: { … }                    # §9.2
corpus:
  size: 20000
  genres:
    meeting_note:  0.25
    email:         0.25
    hr_notice:     0.15
    approval_doc:  0.15
    chat_log:      0.10
    issue_ticket:  0.10
  perturb:
    honorific_variation: 0.3
    partial_name:        0.2
    separator_variation: 0.3
    line_break_split:    0.05
    typo:                0.02
output:
  dir:  data/       # gitignore
  seed: 42
```

### 9.8 생성기 자체의 검증

생성기가 틀리면 그 위의 모든 측정이 조용히 틀린다. 그래서 생성기에도 테스트를 건다.

- **span 라운드트립** — 모든 span에 대해 `text[start:end] == surface` (perturb 적용 후 기준)
- **인구 통계 검증** — 사번이 선언한 채번 규칙을 따르는지, 팀별 인원이 목표 분포를 따르는지
- **inducer 채점** — 생성기가 아는 채번 블록 경계를 `IdSchemaInducer`가 맞히는지.
  자릿수 경계 정확도로 보고한다. `scheme`을 바꿔 최소 2개 포맷에서 통과해야 한다
- **재현성** — 같은 시드면 바이트 단위로 동일한 출력

### 9.9 한계

**템플릿 다양성이 곧 코퍼스 다양성의 상한이다.** 템플릿 20종으로 문서 2만 건을 찍으면 문장이
20종처럼 보이고, §8.3(a)의 uniformity 지표가 익명화 때문이 아니라 템플릿 때문에 나빠진다.

완화책은 **LLM으로 템플릿을 오프라인 확장**하는 것이다. §2에서 LLM 기반 범주화를 온라인 경로에서
배제하면서 "오프라인 사전 구축에는 유용하므로 그 용도로만 남긴다"고 했는데, 템플릿 생성이 정확히
그 용도다. 생성 시점이 오프라인이라 비결정성이 문제되지 않고, 산출물(템플릿 YAML)은 사람이
검토한 뒤 버전 관리된다.

`perturb.py`는 실문서와의 격차를 좁히지만 없애지는 못한다. §8.7의 실문서 수동 라벨링은 여전히
실서비스 투입 전 선행 조건으로 남는다.

---

## 10. 테스트 전략

- **결정성 property test** — 같은 `(secret, scope, key)`면 100회 반복해도 동일 가명
- **조사 교정 테이블 테스트** — 종성 유무 × 9개 조사쌍 전수
- **round-trip 테스트** — 원문 → 익명화 → 변형이 섞인 가짜 LLM 응답 → 복원, 복구율 측정
- **오프셋 정합성** — Report의 span 오프셋이 결과 문자열과 정확히 대응 (치환으로 길이가 바뀌므로
  회귀가 잘 나는 지점)
- **fail-closed 테스트** — 지식 프로바이더를 비웠을 때 어떤 입력도 원본 노출로 떨어지지 않음
- **오탐 테스트** — 금액·수량·날짜·전화번호가 섞인 문서에서 앵커 없는 숫자가 사번으로 잡히지 않음
  (§9.3의 결재 문서 장르가 이 시험대다)
- **linker 정확도** — §9.5의 정답 `entity_key` 기준 ARI + 클러스터 순도·완전성 분리 보고
- **생성기 자체 검증** — §9.8 (span 라운드트립, 인구 통계, inducer 채점, 재현성)

---

## 11. 남은 작업

### 구현 순서

§9의 합성 코퍼스가 §8의 모든 측정을 떠받치고, §8이 §4 정책의 기본 레벨을 결정한다.
따라서 아래 순서를 지킨다.

```
① synth/         가상 조직 + 문서 생성 (측정 대상이 없으면 아무것도 못 잰다)
② detect/        규칙 기반 탐지 + inducer 최소 버전
③ identity/      linker + 결정적 가명
④ hierarchy/     계층 + 프리미티브
⑤ policy/ render/ josa/    치환 경로 완성
⑥ evaluation/   지표 + 레벨 스윕  →  policy.yaml 기본 레벨 확정
⑦ vault/ restore/          외부 LLM 경로 (rag_index 경로만으로 먼저 검증 가능)
```

②~⑤ 없이 ①만으로도 생성기 자체 검증(§9.8)은 돌릴 수 있으므로 ①을 독립 착수 단위로 둔다.

### 결정 대기

| 항목 | 기본값 (미결정 시 채택) |
|---|---|
| `min_k` 코퍼스 통계 기반 자동 상향을 1차에 넣을지 | **1차 제외.** §5 장치 ①의 k 실측으로 대체하고, 코퍼스 전역 k는 2차로 미룬다. |
| 채번 블록과 입사 시기의 상관 여부 | **상관 있다고 가정.** L3(채번 블록)을 기본 체인에서 제외. §8.2(d) 잔여 상관으로 사후 검증. |
| §8.6 성공 기준 수치 | **제안값 그대로 채택.** 실측 후 조정한다. |

### 다음 단계

§4·§5를 마치고 전체 승인 후 `writing-plans`로 구현 계획을 작성한다.
