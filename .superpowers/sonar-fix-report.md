# SonarCloud Quality Gate 수정 보고서

**대상**: KoPII-Pipeline PR #1 (`feat/synth-corpus` → `main`)
**게이트 실패 사유**: Security Rating on New Code = C (요구: A) — 4건의
"검증되지 않은 사용자 입력 경로로 파일시스템 접근" 취약점

---

## FIX 1 — 사용자 입력 경로 검증 (`resolve_user_path`)

`kopii/config/schema.py`에 `resolve_user_path(path: str | Path, *,
must_be_file: bool = False) -> Path` 헬퍼를 추가했다.

- 빈 문자열, NUL 바이트 포함 문자열을 각각 한국어 `ValueError`로 거부한다.
- `~` 확장 후 `expanduser().resolve()`로 절대·심볼릭 링크 해소 경로로
  정규화한다 (파일시스템 접근 전에 `..` 등을 모두 접는다).
- `must_be_file=True`이면 정규화된 경로가 존재하는 "일반 파일"이어야 하며,
  없으면 `FileNotFoundError`, 있지만 파일이 아니면 `ValueError`를 낸다.

호출부 3곳:
- `kopii/config/schema.py :: load_synth_config` — 설정 경로를
  `must_be_file=True`로 검증 후 `read_text`.
- `kopii/synth/cli.py :: run()` — `output_dir`를 함수 맨 위에서
  `resolve_user_path`로 정규화. 정규화된 경로가 존재하는데 디렉터리가
  아니면 한국어 `ValueError`로 먼저 실패시키고, 그 뒤에만 `mkdir` 및
  3개 파일(`population.jsonl`, `corpus.jsonl`, `manifest.json`) 쓰기.
- `kopii/synth/cli.py :: main()` — `--config`, `--out`(또는 설정의
  `output_dir`) 모두 `run()`/`load_synth_config()`에 넘기기 전에
  `resolve_user_path`로 정규화.

새 플래그 추가 없음, 쓰기 가능 위치 제한 없음, 산출물 내용 변경 없음
(검증만 추가, 정책 변경 아님).

`tests/test_config_schema.py`에 4개 테스트 추가:
`test_resolve_user_path_rejects_empty_path`,
`test_resolve_user_path_rejects_null_byte`,
`test_resolve_user_path_collapses_parent_segments`,
`test_resolve_user_path_requires_regular_file`.

## FIX 2 — `scripts/pii_scan.py` 정규식 문자 클래스

`(?<![0-9])` → `(?<!\d)`, `(?![0-9])` → `(?!\d)` 로 4곳(RRN_RE, PHONE_RE,
CARD_RE, BIZNO_RE) 모두 기계적으로 치환. 동작 변화 없음 (검증은 아래
3번 참고).

## FIX 3 — `pytest.raises` 블록 안의 `Edit(...)` 생성 제거

`tests/synth/test_perturb.py`의 `test_partial_overlap_is_rejected`,
`test_overlapping_edits_are_rejected` 모두 `Edit(...)` 및 리스트 생성을
`with pytest.raises(...)` 블록 위 지역 변수로 끌어올렸다. 블록 안에는
`apply_edits(...)` 호출만 남는다. `match=` 패턴과 단언 내용은 그대로.

---

## 검증 결과

### 1. 테스트 전체
```
$ .venv/bin/python -m pytest tests/ -v
...
============================== 67 passed in 0.18s ==============================
```
(기존 63개 + 신규 4개 = 67개, 전부 통과)

### 2. Lint
```
$ .venv/bin/python -m ruff check kopii tests scripts
All checks passed!

$ .venv/bin/python -m ruff format --check kopii tests scripts
26 files already formatted
```
(`ruff format`이 `CARD_RE` 정규식을 한 줄로 재포맷 — `[0-9]`→`\d` 치환으로
줄이 짧아져 88자 제한 안에 들어간 결과. 내용 변경 아님.)

### 3. FIX 2 동작 불변 검증

리포 전체 스캔 — 발견 없음:
```
$ .venv/bin/python scripts/pii_scan.py $(git ls-files)
실 개인정보로 보이는 값이 발견되지 않았습니다.
```

리포 밖 스크래치 파일에 체크섬 유효 RRN(900101-1234568), Luhn 유효
카드번호(4532-7587-8974-1321), 자리표시가 아닌 전화번호(010-9999-8888)를
넣고 스캔 — 3건 모두 탐지:
```
$ .venv/bin/python scripts/pii_scan.py <scratch>/pii_scan_probe.txt
실 개인정보로 보이는 값 3건이 감지되었습니다. 체크섬까지 통과한 값이므로 실제 데이터일 가능성이 높습니다.
값을 제거하거나, 정당한 픽스처라면 .piiscanignore 에 경로를 추가하세요.
<scratch>/pii_scan_probe.txt:1: RRN 로 보이는 값 — 900101-*******
<scratch>/pii_scan_probe.txt:2: CARD 로 보이는 값 — 4532-****-****-****
<scratch>/pii_scan_probe.txt:3: PHONE 로 보이는 값 — 010-****-88**
```

### 4. FIX 1이 파이프라인을 깨지 않았는지

```
$ .venv/bin/python -m kopii.synth --config configs/synth.yaml --out data/
생성 완료 — 구성원 2000명, 문서 20000건 → .../KoPII-Pipeline/data

$ .venv/bin/python -m kopii.synth.validate --dir data/
PASS  employee_id_unique
PASS  entity_key_resolvable
PASS  manifest_counts_match
PASS  rrn_checksum
PASS  span_roundtrip
PASS  surface_matches_origin

모든 검사를 통과했습니다.
```
6개 검사 모두 통과.

### 5. 바이트 재현성

리포 밖 두 디렉터리(`<scratch>/repro1`, `<scratch>/repro2`)에 같은
설정으로 두 번 생성 후 비교:
```
$ diff -rq <scratch>/repro1 <scratch>/repro2
(차이 없음)

population.jsonl: c8e0264a223552b75c4567d8c24c44b5da9146bf (동일)
corpus.jsonl:      b60ec5c139f3b0c15c00a8446a1d155b22162c2c (동일)
manifest.json:     0ad018e2ed328205d64b20f4f920b2f8926a3239 (동일)
```
바이트 단위로 동일함을 SHA1로 확인.

### 6. `git status` — `data/` 관련 항목 없음
```
$ git status --short
 M kopii/config/schema.py
 M kopii/synth/cli.py
 M scripts/pii_scan.py
 M tests/synth/test_perturb.py
 M tests/test_config_schema.py
```
`data/` 아래 항목 없음, `data/README.md` 삭제로 표시되지 않음 (`data/`가
gitignore 대상이라 신규 산출물이 추적되지 않음).

---

## 자체 리뷰(diff self-review)

- **범위 준수**: `kopii/synth/document.py`, `perturb.py`, `population.py`,
  `validate.py`는 건드리지 않았다 (perturb.py는 테스트 파일만 수정, 소스는
  무변경).
- **타입 힌트**: `resolve_user_path`의 매개변수/반환값 모두 명시.
  `Optional[X]` 대신 `str | Path`, `X | None` 스타일만 사용.
- **독스트링**: 한 줄 모듈 독스트링은 기존 그대로 유지, `resolve_user_path`에
  Google 스타일 한국어 독스트링(Args/Returns/Raises) 추가.
- **`resolve_user_path` 시그니처를 `Path` 대신 `str | Path`로 잡은 이유**:
  `Path("")`는 파이썬에서 즉시 `Path('.')`로 정규화되어 "빈 경로"를 표현할
  방법이 없다. 원시 문자열을 받아 `Path`로 감싸기 전에 빈 문자열/NUL 바이트를
  검사해야 스펙이 요구하는 "빈 경로 거부"가 실제로 테스트 가능해진다.
  `cli.py`에서는 여전히 `argparse(type=Path)`로 받은 `Path` 객체를 그대로
  넘기므로 실사용 경로에는 영향이 없다.
- **이중 정규화**: `main()`에서 `resolve_user_path(args.config)`를 호출한
  뒤 `load_synth_config()` 내부에서 `must_be_file=True`로 다시
  `resolve_user_path`를 호출한다. 이미 정규화된 절대 경로를 다시 정규화하는
  것은 멱등이라 부작용이 없고, 태스크 지시("main()에서 --config 경로와
  유효 출력 경로를 모두 정규화한 뒤 넘긴다")를 문자 그대로 만족시키기 위해
  의도적으로 남겼다.
- **`run()`의 방어적 `ValueError`**: 산출물 경로가 이미 존재하지만
  디렉터리가 아닌 경우 `mkdir(parents=True, exist_ok=True)`가 애매한
  `FileExistsError`를 내기 전에 명확한 한국어 메시지로 먼저 실패시킨다.
- **FIX 2 리스크**: 순수 기계적 치환이며, RRN_RE/PHONE_RE/BIZNO_RE는 원래
  한 줄이라 그대로 유지되고 CARD_RE만 `ruff format`이 3줄→1줄로 재포맷했다
  (라인 길이가 줄어든 결과일 뿐 정규식 문자열 자체는 동일).
- **FIX 3**: `match=` 패턴("부분적으로", "겹칩니다")과 단언 대상 모두
  변경하지 않았다. `Edit` 생성이 실패할 경우 이제 `pytest.raises` 밖에서
  즉시 원래 예외로 터지므로, 어떤 호출이 실패를 유발했는지 모호함이
  사라졌다.
- **미해결/관찰 사항**: 없음. 6개 검증 항목 모두 통과, 게이트를 끌어내린
  4건의 취약점 지점(schema.py의 `load_synth_config`, cli.py의 `run()`과
  `main()` 2곳)을 전부 `resolve_user_path` 경로로 라우팅했다.

---

## 커밋

한 번에 커밋 예정 (모든 검증 통과 후):
- `kopii/config/schema.py`
- `kopii/synth/cli.py`
- `scripts/pii_scan.py`
- `tests/synth/test_perturb.py`
- `tests/test_config_schema.py`
