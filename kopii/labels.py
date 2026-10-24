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
