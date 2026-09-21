"""Publication checks keep scanning unknown values around verified source hashes."""

import hashlib
import json
import runpy
from pathlib import Path


def test_scanner_only_excludes_verified_local_source_digest(tmp_path, monkeypatch) -> None:
    root = Path(__file__).parents[3]
    scanner = runpy.run_path(str(root / "scripts/pii_scan.py"))
    # This fixed content hashes to a digest with a checksum-valid numeric run.
    source = b"publication fixture 211"
    (tmp_path / "source.py").write_bytes(source)
    digest = hashlib.sha256(source).hexdigest()
    line = f'"source.py": "{digest}",'
    monkeypatch.chdir(tmp_path)
    assert scanner["redact_verified_source_digest"](line) != line
    assert scanner["scan_text"](line) == []
    # Editing the file invalidates the exemption, even for a well-formed digest.
    (tmp_path / "source.py").write_text("changed")
    assert scanner["redact_verified_source_digest"](line) == line
    assert scanner["scan_text"](line)
    assert scanner["redact_verified_source_digest"](
        line.replace("source.py", "../source.py")
    ) == line.replace("source.py", "../source.py")
    phone = "010" + "2468" + "1357"
    assert any(hit[1] == "PHONE" for hit in scanner["scan_text"](json.dumps({"note": phone})))
