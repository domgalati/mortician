from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from mortician import bundle, serve, utils


def _mk_bundle(tmp_path: Path, issue_id: str = "abc123", title: str = "Test Incident") -> Path:
    incidents = tmp_path / "incidents"
    incidents.mkdir(parents=True, exist_ok=True)
    bundle.INCIDENTS_DIR = incidents
    serve.INCIDENTS_DIR = incidents
    return bundle.create_bundle(issue_id, title)


def test_resolution_parse_fallback_when_no_subheadings() -> None:
    raw = "## Resolution\n\nLegacy one-block resolution text."
    parsed = bundle.parse_index_md(
        "## Summary\n\nx\n\n## Impact & Severity\n\nx\n\n## Root Cause\n\nx\n\n" + raw + "\n"
    )
    assert parsed["resolution_temporary"] == "Legacy one-block resolution text."
    assert parsed["resolution_permanent"] == ""


def test_impact_roundtrip_keeps_all_subsections() -> None:
    fields = {
        "affected_services": "api, web",
        "duration_of_outage": "22m",
        "business_impact": "checkout degraded",
    }
    md = bundle._build_impact_markdown(fields)
    parsed = bundle._parse_impact_subsections(md)
    assert parsed == fields


def test_action_done_semantics_and_cli_unset_completed(tmp_path: Path) -> None:
    _mk_bundle(tmp_path, issue_id="act001")
    data = bundle.load_postmortem("act001")
    assert data is not None
    data["actions_and_follow_up"] = [{"task": "x", "done": False, "completed": True}]
    bundle.save_postmortem("act001", data)

    assert utils._action_item_is_done({"done": False, "completed": True}) is True
    code = utils.set_action_item_done("act001", 1, done=False)
    assert code == 0

    saved = bundle.load_postmortem("act001")
    assert saved is not None
    first = saved["actions_and_follow_up"][0]
    assert first.get("done") is False
    assert "completed" not in first


def test_bulk_set_action_done_preserves_completed_field(tmp_path: Path) -> None:
    b = _mk_bundle(tmp_path, issue_id="act002")
    bundle._write_actions(
        b,
        [
            {"task": "a", "done": False, "completed": False},
            {"task": "b", "done": False},
        ],
    )
    updated = bundle.bulk_set_action_done(b, True)
    assert updated == 2
    rows = bundle._read_actions(b)
    assert rows[0]["done"] is True and rows[0]["completed"] is True
    assert rows[1]["done"] is True and "completed" not in rows[1]


def test_api_error_responses_parity(tmp_path: Path) -> None:
    _mk_bundle(tmp_path, issue_id="api001")
    client = TestClient(serve.app)

    res = client.patch("/api/postmortems/api001/actions/not-an-int", content=b"{}")
    assert res.status_code == 400
    assert res.json()["error"] == "invalid index"

    res = client.post("/api/postmortems/api001/actions", content=b'"oops"')
    assert res.status_code == 400
    assert res.json()["error"] == "body must be a JSON object"

    res = client.patch(
        "/api/postmortems/api001/actions/reorder",
        json={"from_index": "a", "to_index": 1},
    )
    assert res.status_code == 400
    assert "required integers" in res.json()["error"]
