"""Directory behavior for ambiguity, missing values, and hierarchy selection."""

from pathlib import Path

import pytest

from kopii import Pipeline, Policy
from kopii.detectors.rules import DictionaryDetector
from kopii.resolvers.csv import CsvResolver


def test_resolver_keeps_different_teams_ambiguous_even_with_same_parent(tmp_path: Path) -> None:
    path = tmp_path / "org.csv"
    path.write_text("name,team,division\n김하늘,A팀,A본부\n김하늘,B팀,A본부\n이바다,A팀,A본부\n")
    result = CsvResolver(path, "division").resolve(["김하늘", "이바다", "미등록"])
    assert result["김하늘"].status == "ambiguous"
    assert result["이바다"].value == "A본부"
    assert result["미등록"].status == "missing"


def test_same_name_same_team_can_resolve_but_not_identify_person(tmp_path: Path) -> None:
    path = tmp_path / "org.csv"
    path.write_text("name,team\n김하늘,A팀\n김하늘,A팀\n")
    assert CsvResolver(path).resolve(["김하늘"])["김하늘"].value == "A팀"


def test_unsafe_directory_category_falls_back_to_mask(tmp_path: Path) -> None:
    path = tmp_path / "org.csv"
    path.write_text("name,team\n김하늘,[injected]\n")
    pipeline = Pipeline(
        DictionaryDetector(["김하늘"]), Policy({"PERSON_NAME": "organization"}), CsvResolver(path)
    )
    assert pipeline.process("김하늘").text == "[PERSON_NAME]"


def test_resolver_rejects_truncated_csv_rows(tmp_path: Path) -> None:
    path = tmp_path / "org.csv"
    path.write_text("name,team\n김하늘\n")
    with pytest.raises(ValueError, match="Malformed"):
        CsvResolver(path)
