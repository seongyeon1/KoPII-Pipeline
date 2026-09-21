"""Exercise the study runner with fictional archived predictions, without model downloads."""

import hashlib
import json
import runpy
from pathlib import Path

import pytest

from kopii.research.organization import make_world, organization_answer

ROOT = Path(__file__).parents[2]


def test_metadata_uses_service_errors_and_rejects_wrong_prediction_identity(tmp_path) -> None:
    runner = runpy.run_path(str(ROOT / "research/run_metadata_study.py"))
    protocol = json.loads((ROOT / "research/studies/metadata-retrieval.json").read_text())
    protocol["seeds"] = [42]
    _, docs, directory = make_world(42, protocol["team_sizes"])
    manifest = {"run_id": "fixture-run", "config": {"protocol": protocol}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "results.json").write_text(
        json.dumps(
            {
                "complete": True,
                "manifest": manifest,
                "worlds": [{"seed": 42}],
            }
        )
    )
    generated = runner["digest"](
        {
            "documents": [(d.did, d.text, d.person.pid) for d in docs],
            "directory": directory,
        }
    )
    prediction_path = tmp_path / "predictions-42.json"
    saved = {
        "run_id": "fixture-run",
        "generated_sha256": generated,
        "predictions": {d.did: [e.to_dict() for e in d.spans] for d in docs},
    }
    prediction_path.write_text(json.dumps(saved))
    worlds, provenance = runner["prepare"](tmp_path, protocol)
    assert (
        provenance["files"]["predictions-42.json"]
        == hashlib.sha256(prediction_path.read_bytes()).hexdigest()
    )
    world = worlds[0]
    for doc, text in zip(docs, world["conditions"]["gold"]["team"], strict=True):
        observed = organization_answer(text, "team")
        if doc.person.stress in {"missing", "cross_team_homonym", "multiple_teams"}:
            assert observed == set()
        elif doc.person.stress == "stale":
            assert len(observed) == 1 and doc.person.team not in observed
        else:
            assert observed == {doc.person.team}
    assert all(not organization_answer(t, "team") for t in world["conditions"]["gold"]["mask"])
    saved["generated_sha256"] = "wrong-world"
    prediction_path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="do not match"):
        runner["prepare"](tmp_path, protocol)
