"""Validation of Claude's output, tested with fake responses (no API calls)."""
from pathlib import Path

from claude_client.review import TOOL, build_user_message
from claude_client.validate import validate_review
from core.candidates import generate_candidates
from core.model import load_building, load_config
from core.scenarios import build_scenarios

ROOT = Path(__file__).resolve().parents[1]
cfg = load_config(ROOT / "config" / "config.toml")
b = load_building(ROOT / "fixtures" / "demo_building.json")
cands = generate_candidates(b, cfg)


def test_tool_schema_forces_required_fields():
    item = TOOL["input_schema"]["properties"]["decisions"]["items"]
    assert {"location_id", "decision", "clause", "confidence"} <= set(item["required"])


def test_user_message_is_json_payload():
    msg = build_user_message(b, cands)
    assert '"candidates"' in msg and '"building"' in msg


def test_cannot_reject_mandatory():
    review = {"decisions": [{"location_id": "A1", "decision": "reject", "reason": "x", "clause": "3-2.9.2.2",
                             "confidence": "high", "needs_engineer_review": False}], "summary": ""}
    merged, issues = validate_review(b, cands, review)
    assert any("mandatory" in i for i in issues)
    assert next(c for c in merged if c["location_id"] == "A1")["status"] != "proposed_reject"


def test_unknown_location_ignored():
    review = {"decisions": [{"location_id": "Z99", "decision": "add", "reason": "x", "clause": "3-2.9.2.2",
                             "confidence": "low", "needs_engineer_review": True}], "summary": ""}
    merged, issues = validate_review(b, cands, review)
    assert any("Z99" in i for i in issues)
    assert all(c["location_id"] != "Z99" for c in merged)


def test_added_location_gets_rule_stories():
    review = {"decisions": [{"location_id": "D3", "decision": "add", "reason": "lightly loaded neighbour",
                             "clause": "3-2.9.2.2", "confidence": "medium", "needs_engineer_review": True}],
              "summary": ""}
    merged, _ = validate_review(b, cands, review)
    d3 = next(c for c in merged if c["location_id"] == "D3")
    assert [s["story"] for s in d3["stories"]] == ["Story1", "Story2", "Story3", "Story4"]


def test_bad_region_discarded_and_good_region_filtered_by_level():
    review = {"decisions": [
        {"location_id": "A3", "decision": "accept", "reason": "ok", "clause": "3-2.11.4.1",
         "confidence": "medium", "needs_engineer_review": True,
         "affected_region": {"levels": ["L1"], "bays": ["NOT_A_BAY"], "reasoning": "x"}}], "summary": ""}
    _, issues = validate_review(b, cands, review)
    assert any("A3" in i for i in issues)

    # user-approved override applied to a Story3 removal keeps only L3/ROOF bays
    cand = next(c for c in cands if c["location_id"] == "A3")
    cand = dict(cand, region_override={"bays": ["A_L1_A2", "A_L3_A2", "A_ROOF_A2"]},
                stories=[{"story": "Story3", "reasons": []}])
    scen = build_scenarios(b, [cand], cfg)
    assert scen[0]["region"]["bays"] == ["A_L3_A2", "A_ROOF_A2"]
