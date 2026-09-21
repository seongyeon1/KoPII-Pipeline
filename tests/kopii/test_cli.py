"""CLI contract tests using real configuration, files, and safe error output."""

import json
from pathlib import Path

import pytest

from kopii import Entity, Pipeline
from kopii.cli import main


def test_cli_demo_runs_without_neural_dependencies(capsys: object) -> None:
    assert (
        main(["process", "--config", "configs/demo.json", "--input", "examples/document.txt"]) == 0
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "플랫폼개발팀" in captured.out
    assert "[EMAIL]" in captured.out
    assert "박가람" not in captured.out


def test_cli_failure_does_not_echo_input_or_traceback(tmp_path: Path, capsys: object) -> None:
    config = tmp_path / "invalid.json"
    config.write_text('{"detector":{"kind":"rules","misspelled":true}}')
    text = tmp_path / "text.txt"
    text.write_text("private fixture content")
    assert main(["process", "--config", str(config), "--input", str(text)]) == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out == ""
    assert "private fixture" not in captured.err
    assert "ValueError" in captured.err


def test_cli_keeps_model_progress_off_json_stdout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoisyModel:
        def detect(self, text: str) -> list[Entity]:
            print("external model progress")
            return [Entity(0, len(text), "EMAIL")]

    def factory(*args: object) -> Pipeline:
        print("external model loaded")
        return Pipeline(NoisyModel())

    monkeypatch.setattr("kopii.cli.create_pipeline", factory)
    config, document = tmp_path / "config.json", tmp_path / "input.txt"
    config.write_text("{}")
    document.write_text("fixture@example.invalid")
    assert main(["process", "--config", str(config), "--input", str(document)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["text"] == "[EMAIL]"
    assert "external model progress" in captured.err


def test_cli_prepares_and_searches_custom_fields_without_exposing_private_metadata(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "private-index.jsonl"
    assert (
        main(
            [
                "prepare",
                "--config",
                "configs/context-demo.json",
                "--input",
                "examples/search/documents.jsonl",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["documents"] == 3
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert rows[0]["metadata"] == {"business_unit": ["product"], "region": ["west"]}
    assert "김하늘" not in output.read_text() and "alpha@example.invalid" not in output.read_text()
    assert output.stat().st_mode & 0o777 == 0o600
    command = [
        "search",
        "--index",
        str(output),
        "--query",
        "배포 일정",
        "--scope",
        "examples/search/scope.json",
        "--filters",
        "examples/search/filters.json",
    ]
    assert main(command) == 0
    hits = json.loads(capsys.readouterr().out)["hits"]
    assert [hit["id"] for hit in hits] == ["record-a"]
    assert "metadata" not in hits[0]
    assert main([*command, "--include-metadata"]) == 0
    assert json.loads(capsys.readouterr().out)["hits"][0]["metadata"]["region"] == ["west"]
    original = output.read_bytes()
    assert (
        main(
            [
                "prepare",
                "--config",
                "configs/context-demo.json",
                "--input",
                "examples/search/documents.jsonl",
                "--output",
                str(output),
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == "" and output.read_bytes() == original


def test_cli_rejects_raw_metadata_injection_and_invalid_search_scope(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw, output = tmp_path / "raw.jsonl", tmp_path / "index.jsonl"
    raw.write_text(
        json.dumps({"id": "d", "text": "sensitive fixture", "metadata": {"role": ["admin"]}})
    )
    assert (
        main(
            [
                "prepare",
                "--config",
                "configs/context-demo.json",
                "--input",
                str(raw),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert not output.exists()
    captured = capsys.readouterr()
    assert captured.out == "" and "sensitive fixture" not in captured.err
    scope = tmp_path / "scope.json"
    scope.write_text('"d"')
    assert main(["search", "--index", str(raw), "--query", "fixture", "--scope", str(scope)]) == 1
    assert capsys.readouterr().out == ""
