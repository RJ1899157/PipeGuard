"""Minimal outbound evidence and locally checked advisory responses."""
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pipeguard.detection.service import digest
from pipeguard.ingestion.contracts import ExecutionEvent
from pipeguard.detection.contracts import QualityReport
from pipeguard.lineage.evidence import SAFE_SOURCE_ERRORS


class InvestigationRejected(ValueError):
    """Errors contain fixed public codes, never provider bodies or evidence text."""
    def __init__(self, code, *, diagnostic=None):
        super().__init__(code)
        self.diagnostic = diagnostic


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Hypothesis(StrictModel):
    category: Literal["reported_source_failure", "reported_execution_failure", "reported_validation_failure",
                      "reported_quality_failure", "source_evidence_gap", "lineage_evidence_gap",
                      "conflicting_execution_reports"]
    explanation: Annotated[str, Field(min_length=1, max_length=1200)]
    confidence: Literal["low", "medium"]
    supporting_evidence: Annotated[list[str], Field(min_length=1, max_length=1)]
    contradicting_evidence: Annotated[str, Field(min_length=1, max_length=5)]


class Investigation(StrictModel):
    abstained: bool = Field(strict=True)
    abstention_reason: Annotated[str, Field(max_length=600)]
    hypotheses: Annotated[list[Hypothesis], Field(max_length=3)]
    next_checks: Annotated[list[Literal["inspect_source_availability", "compare_retry_history",
        "compare_quality_reports", "inspect_source_coverage", "inspect_lineage_completeness",
        "request_missing_evidence"]], Field(max_length=5)]

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.abstained:
            if self.hypotheses or not self.abstention_reason.strip():
                raise ValueError("abstention_requires_reason_without_hypotheses")
        elif not self.hypotheses or self.abstention_reason:
            raise ValueError("hypotheses_required_without_abstention_reason")
        for hypothesis in self.hypotheses:
            support = hypothesis.supporting_evidence
            contradiction = [] if hypothesis.contradicting_evidence == "none" else [hypothesis.contradicting_evidence]
            if (len(set(support)) != len(support) or len(set(contradiction)) != len(contradiction)
                    or set(support) & set(contradiction)):
                raise ValueError("ambiguous_evidence_citations")
        return self


STATES = {"unknown", "queued", "running", "waiting", "succeeded", "failed", "cancelled", "blocked", "skipped"}
CONDITIONS = {"execution_failure", "unknown_execution_state", "quality_failure", "quality_conflict",
              "quality_missing", "source_coverage", "lineage_conflict", "lineage_partial", "lineage_missing"}
ERRORS = SAFE_SOURCE_ERRORS | {"connection_timeout", "source_unavailable", "validation_failed", "execution_error", "unknown"}


def project_bundle(bundle):
    """No raw names, external identifiers, logs, SQL or arbitrary strings leave here.

    Fail on size/integrity limits instead of silently dropping older failed attempts.
    Local citation mapping is retained separately and never sent to the provider.
    """
    payload = bundle["payload"]
    if digest(payload) != bundle["payload_hash"]:
        raise InvestigationRejected("bundle_integrity_mismatch")
    if payload.get("schema_version") != 1 or payload.get("truncated") is not False:
        raise InvestigationRejected("bundle_incomplete_or_unsupported")
    if "source_hash_mismatch" in payload.get("missing_evidence", []):
        raise InvestigationRejected("source_integrity_mismatch")
    source_items = payload.get("items", [])
    if not isinstance(source_items, list) or len(source_items) > 100:
        raise InvestigationRejected("evidence_limit")
    aliases, run_ids, mapping, items = {}, {}, {}, []

    def run_alias(value):
        if value not in aliases:
            aliases[value] = f"run_{len(aliases) + 1}"
        return aliases[value]

    for item in source_items:
        if item["table"] == "runs":
            external = item["summary"].get("external_run_id")
            if isinstance(external, str):
                run_ids[item["id"]] = run_alias(external)
    for item in source_items:
        table, value, fields = item["table"], item["summary"], {}
        # UUIDs and original hashes remain in the local citation map only.
        UUID(item["id"])
        if table == "ingested_events":
            event = ExecutionEvent.model_validate(value)
            fields = {"run": run_alias(event.external_run_id), "attempt": event.attempt_number,
                      "state": event.state, "error_code": event.error_code,
                      "occurred_at": event.occurred_at.isoformat()}
        elif table == "attempts":
            if value.get("run_id") not in run_ids:
                raise InvestigationRejected("attempt_run_missing")
            number = value.get("attempt_number")
            if type(number) is not int or not 1 <= number <= 2147483647:
                raise InvestigationRejected("invalid_attempt")
            fields = {"run": run_ids[value["run_id"]], "attempt": number}
        elif table == "runs":
            fields = {"run": run_ids.get(item["id"])}
        elif table == "observations" and "report" in value:
            report = QualityReport.model_validate(value["report"])
            fields = {"run": run_alias(report.external_run_id), "attempt": report.attempt_number,
                      "inventory_complete": report.inventory_complete,
                      "quality_counts": {status: sum(c.status == status for c in report.checks)
                                         for status in ("pass", "fail", "error", "skipped", "unknown")},
                      "occurred_at": report.occurred_at.isoformat()}
        elif table == "observations":
            if value.get("status") in {"complete", "incomplete"}:
                fields["scan_status"] = value["status"]
        elif table == "lineage_events":
            if value.get("coverage") in {"complete", "partial"}:
                fields["lineage_coverage"] = value["coverage"]
        else:
            continue
        if value.get("state") in STATES:
            fields["state"] = value["state"]
        if value.get("error_code") in ERRORS:
            fields["error_code"] = value["error_code"]
        if type(value.get("reconciliation_required")) is bool:
            fields["reconciliation_required"] = value["reconciliation_required"]
        if not fields:
            continue
        citation = f"e{len(items) + 1}"
        items.append({"citation": citation, "kind": table, "facts": fields})
        mapping[citation] = {key: item[key] for key in ("table", "id", "content_hash", "hash_basis")}
    condition = payload.get("incident", {}).get("condition")
    packet = {"schema_version": 1, "condition": condition if condition in CONDITIONS else "unknown",
              "missing_evidence_present": bool(payload.get("missing_evidence")), "items": items}
    if not items:
        raise InvestigationRejected("no_usable_evidence")
    if len(json.dumps(packet).encode()) > 6000:
        raise InvestigationRejected("provider_evidence_limit")
    return packet, mapping


def eligible_categories(condition):
    return ({"reported_source_failure", "reported_execution_failure", "reported_validation_failure", "conflicting_execution_reports"}
            if condition in {"execution_failure", "unknown_execution_state"} else
            {"reported_quality_failure"} if condition in {"quality_failure", "quality_conflict", "quality_missing"} else
            {"source_evidence_gap"} if condition == "source_coverage" else
            {"lineage_evidence_gap"} if condition in {"lineage_partial", "lineage_missing", "lineage_conflict"} else set())


def supports(category, fact):
    if category == "reported_source_failure":
        return fact.get("error_code") in {"source_unavailable", "connection_timeout"}
    if category == "reported_execution_failure":
        return fact.get("error_code") == "execution_error"
    if category == "reported_validation_failure":
        return fact.get("error_code") == "validation_failed"
    if category == "reported_quality_failure":
        return any(fact.get("quality_counts", {}).get(s, 0) > 0 for s in ("fail", "error"))
    if category == "source_evidence_gap":
        return fact.get("scan_status") == "incomplete" or fact.get("error_code") in SAFE_SOURCE_ERRORS
    if category == "lineage_evidence_gap":
        return fact.get("lineage_coverage") == "partial"
    return category == "conflicting_execution_reports" and fact.get("reconciliation_required") is True


def supported_categories(packet):
    return sorted(c for c in eligible_categories(packet.get("condition"))
                  if any(supports(c, item.get("facts", {})) for item in packet["items"]))


def incompatible(one, two):
    return (one.get("run") is not None and one.get("run") == two.get("run")
            and one.get("attempt") is not None and one.get("attempt") == two.get("attempt")
            and one.get("state") in {"succeeded", "failed", "cancelled"}
            and two.get("state") in {"succeeded", "failed", "cancelled"} and one["state"] != two["state"])


def validate_answer(answer, packet):
    result = Investigation.model_validate(answer)
    if len(json.dumps(result.model_dump(), ensure_ascii=False).encode()) > 12000:
        raise InvestigationRejected("investigation_output_limit")
    allowed = {item["citation"] for item in packet["items"]}
    categories = set()
    facts = {item["citation"]: item.get("facts", {}) for item in packet["items"]}
    condition = packet.get("condition")
    eligible = eligible_categories(condition)
    for hypothesis in result.hypotheses:
        contradiction = [] if hypothesis.contradicting_evidence == "none" else [hypothesis.contradicting_evidence]
        if not set(hypothesis.supporting_evidence + contradiction) <= allowed:
            raise InvestigationRejected("unknown_evidence_citation")
        category = hypothesis.category
        if category not in eligible or category in categories:
            raise InvestigationRejected("unsupported_hypothesis_category")
        categories.add(category)
        supporting = [facts[ref] for ref in hypothesis.supporting_evidence]
        if not all(supports(category, fact) for fact in supporting):
            raise InvestigationRejected("hypothesis_support_missing")
        # A successful later retry is not a contradiction of an earlier failed attempt.
        for ref in contradiction:
            counter = facts[ref]
            if not any(incompatible(counter, support) for support in supporting):
                raise InvestigationRejected("unsupported_contradiction")
    return result
