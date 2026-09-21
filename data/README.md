# 평가 데이터 준비

이 디렉터리에는 데이터 파일을 커밋하지 않습니다. 이 README만 버전 관리합니다.

현재 벤치마크는 공개 데이터셋 [seongyeon1/ko-pii-ner-100k](https://huggingface.co/datasets/seongyeon1/ko-pii-ner-100k)의 고정 버전을 사용합니다.

| 파일 | 사용 범위 |
|---|---|
| `ko_pii/test_kdpii.jsonl` | 한국어 대화 기반 홀드아웃 2,006건 전량 |
| `ko_pii/test.jsonl` | 개인정보가 없는 L4 문서 580건만 선택 |

저장소 루트에서 [벤치마크 실행 환경](../benchmarks/pii_compare/README.md)을 설치한 후 준비합니다.

```bash
benchmarks/pii_compare/.venv/bin/python benchmarks/pii_compare/prepare.py --skip-models
```

준비 스크립트는 공개 파일을 `data/ko_pii/`에 내려받고 기존 평가에 사용한 파일과 SHA-256이 같은지 확인합니다. 학습용·검증용 파일은 내려받지 않습니다.

실제 업무 문서, 인사정보, 조직도와 인증 정보는 공개 저장소에 포함하지 않습니다. 데이터 이용·재배포 조건은 공개 데이터셋과 원천 자료의 라이선스를 확인해야 합니다. 합성 생성기의 초기 설계는 [구현 계획](../docs/plans/2026-08-28-synth-corpus.md)에 있으며 이 저장소에는 해당 생성기 실행 모듈이 아직 포함돼 있지 않습니다.

## 새 연구용 fixture

`kopii synthesize --output output/fixture-data`로 작은 예제 자료를 만들 수 있습니다. 이는 위 공개 100k 데이터셋의 재생성 명령이 아닙니다. 새 JSONL 계약과 원천 그룹 분할은 [연구 실행 안내](../research/README.md)를 참고하세요.
