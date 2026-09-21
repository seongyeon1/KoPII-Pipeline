#!/usr/bin/env python3
"""공개 레포에 실 개인정보가 커밋되는 것을 막는 최소 스캐너.

체크섬이 있는 식별자만 검사하여 오탐을 억제한다. 형태만 맞고 체크섬이 틀린
값(문서의 예시 등)은 통과시킨다. 본격적인 탐지는 kopii.detect가 맡고,
이 스크립트는 그 전까지의 안전망이자 이후에는 회귀 테스트의 출발점이다.

사용:
    python scripts/pii_scan.py <파일 또는 디렉터리> ...
    python scripts/pii_scan.py $(git diff --name-only origin/main...HEAD)
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import sys
from pathlib import Path

IGNORE_FILE = Path(".piiscanignore")
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".whl",
    ".ico", ".woff", ".woff2", ".so", ".dylib", ".pyc",
}

RRN_RE = re.compile(r"(?<![0-9])(\d{6})[-\s]?([1-4]\d{6})(?![0-9])")
PHONE_RE = re.compile(r"(?<![0-9])(01[016789])[-\s.]?(\d{3,4})[-\s.]?(\d{4})(?![0-9])")
CARD_RE = re.compile(r"(?<![0-9])(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})(?![0-9])")
BIZNO_RE = re.compile(r"(?<![0-9])(\d{3})-?(\d{2})-?(\d{5})(?![0-9])")


def _is_placeholder(digits: str) -> bool:
    """0000·1111 처럼 한 숫자만 반복되는 자리표시 값인지."""
    return len(set(digits)) == 1


def valid_rrn(digits: str) -> bool:
    """주민등록번호 검증 (13자리, 가중치 2~9 순환)."""
    if len(digits) != 13 or _is_placeholder(digits):
        return False
    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    total = sum(int(d) * w for d, w in zip(digits[:12], weights))
    return (11 - total % 11) % 10 == int(digits[12])


def valid_luhn(digits: str) -> bool:
    """카드번호 Luhn 검증."""
    if _is_placeholder(digits):
        return False
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def valid_bizno(digits: str) -> bool:
    """사업자등록번호 검증 (10자리)."""
    if len(digits) != 10 or _is_placeholder(digits):
        return False
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    total = sum(int(d) * w for d, w in zip(digits[:9], weights))
    total += (int(digits[8]) * 5) // 10
    return (10 - total % 10) % 10 == int(digits[9])


def redact_verified_source_digest(line: str) -> str:
    """Exclude only a digest verified against a local Python source file.

    A random digit run inside a SHA-256 is not a published identifier. Keep
    filenames and every unverified value in the scan; never whitelist an entire
    result file or trust a value merely because it looks like a hash.
    """
    try:
        entry = json.loads("{" + line.strip().rstrip(",") + "}")
        if len(entry) != 1:
            return line
        name, digest = next(iter(entry.items()))
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return line
        path = Path(name)
        if path.is_absolute() or path.suffix != ".py":
            return line
        path.resolve().relative_to(Path.cwd().resolve())
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return line
        return line.replace('"' + digest + '"', '"verified-source-digest"')
    except (ValueError, OSError):
        return line


def scan_text(text: str) -> list[tuple[int, str, str]]:
    """(줄번호, 타입, 마스킹된 값) 목록을 돌려준다."""
    hits: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = redact_verified_source_digest(line)
        for m in RRN_RE.finditer(line):
            digits = m.group(1) + m.group(2)
            if valid_rrn(digits):
                hits.append((lineno, "RRN", digits[:6] + "-*******"))
        for m in PHONE_RE.finditer(line):
            body = m.group(2) + m.group(3)
            if not _is_placeholder(body):
                hits.append((lineno, "PHONE", f"{m.group(1)}-****-{m.group(3)[-2:]}**"))
        for m in CARD_RE.finditer(line):
            digits = "".join(m.groups())
            if valid_luhn(digits):
                hits.append((lineno, "CARD", digits[:4] + "-****-****-****"))
        for m in BIZNO_RE.finditer(line):
            digits = "".join(m.groups())
            if valid_bizno(digits):
                hits.append((lineno, "BIZNO", digits[:3] + "-**-*****"))
    return hits


def load_ignore_patterns() -> list[str]:
    if not IGNORE_FILE.exists():
        return []
    return [
        ln.strip()
        for ln in IGNORE_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]


def iter_files(targets: list[str], ignore: list[str]):
    for target in targets:
        path = Path(target)
        if not path.exists():
            continue
        candidates = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        for p in candidates:
            posix = p.as_posix()
            if ".git/" in posix or p.suffix.lower() in BINARY_SUFFIXES:
                continue
            if any(fnmatch.fnmatch(posix, pat) for pat in ignore):
                continue
            yield p


def main(argv: list[str]) -> int:
    targets = argv[1:] or ["."]
    ignore = load_ignore_patterns()
    findings = 0

    for path in iter_files(targets, ignore):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, kind, masked in scan_text(text):
            print(f"{path}:{lineno}: {kind} 로 보이는 값 — {masked}")
            findings += 1

    if findings:
        print(
            f"\n실 개인정보로 보이는 값 {findings}건이 감지되었습니다. "
            "체크섬까지 통과한 값이므로 실제 데이터일 가능성이 높습니다.\n"
            "값을 제거하거나, 정당한 픽스처라면 .piiscanignore 에 경로를 추가하세요.",
            file=sys.stderr,
        )
        return 1

    print("실 개인정보로 보이는 값이 발견되지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
