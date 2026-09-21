"""Check built distributions for accidental local/internal artifact inclusion."""

import tarfile
import zipfile
from pathlib import Path


def main() -> None:
    """Inspect archive names without extracting or executing their contents."""
    artifacts = list(Path("dist").glob("*.whl")) + list(Path("dist").glob("*.tar.gz"))
    if not artifacts:
        raise SystemExit("Build distributions before running this check")
    forbidden = (
        "docs/customer/", "docs/confluence/", "docs/benchmarks/", "output/", ".venv/",
        "data/ko_pii/", "benchmarks/pii_compare/report.py", ".env", "organizations.private",
    )
    for artifact in artifacts:
        if artifact.suffix == ".whl":
            with zipfile.ZipFile(artifact) as wheel:
                names = wheel.namelist()
        else:
            with tarfile.open(artifact) as source:
                names = source.getnames()
        for name in names:
            if any(token in name for token in forbidden):
                raise SystemExit(f"Unexpected local artifact in distribution: {name}")
        print(f"{artifact.name}: {len(names)} entries; local artifact check passed")


if __name__ == "__main__":
    main()
