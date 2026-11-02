"""Run ONE predeclared evaluation trial through the normal durable API.

The private plan freezes bundle hashes, packets, expected labels and request keys
before any trials. Repeating a trial replays its key. No automatic retries, fallback,
budget bypass or direct Groq calls are available here.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import UUID, uuid4

from local_files import read_private, write_private

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/pipeguard/src"))
from pipeguard.detection.service import digest
from pipeguard.investigation.core import InvestigationRejected, project_bundle
from pipeguard.investigation.evaluation import score
from pipeguard.investigation.groq import MODEL, PROMPT_VERSION, json_request


def run(plan, case_index, trial):
    if plan["model"] != MODEL or plan["prompt_version"] != PROMPT_VERSION:
        raise ValueError("evaluation_policy_changed")
    case = plan["cases"][case_index]
    bundle_id = str(UUID(case["bundle_id"]))
    incident_id = str(UUID(case["incident_id"]))
    key = str(UUID(case["request_keys"][trial - 1]))
    token = os.environ["PIPEGUARD_ADMIN_TOKEN"]
    bundle = json_request("http://127.0.0.1:8000/v1/evidence-bundles/" + bundle_id, key=token)
    packet, _ = project_bundle(bundle)
    if bundle["incident_id"] != incident_id or bundle["payload_hash"] != case["bundle_hash"] or digest(packet) != case["packet_hash"]:
        raise ValueError("evaluation_evidence_changed")
    try:
        row = json_request("http://127.0.0.1:8000/v1/incidents/" + incident_id + "/investigations",
            key=token, body={"bundle_id": bundle_id, "request_key": key, "free_plan_confirmed": True})
    except InvestigationRejected as error:
        return {"case": case["name"], "trial": trial, "request_key": key,
                "state": "submission_unresolved", "safe": False, "useful": False, "reason": str(error)}
    if (row["model"] != MODEL or row["prompt_version"] != PROMPT_VERSION or not row["input_integrity_valid"]
            or row["bundle_id"] != bundle_id or digest(row["input_payload"]["packet"]) != case["packet_hash"]):
        raise ValueError("evaluation_record_mismatch")
    outcome = row.get("outcome") or {}
    answer = outcome.get("result")
    measurement = (score(answer, packet, case["expected_categories"], must_abstain=case["must_abstain"])
                   if row["state"] == "completed" and answer else
                   {"safe": False, "useful": False, "reason": row["state"]})
    return {"case": case["name"], "trial": trial, "request_key": key, "request_id": row["id"],
            "model": row["model"], "prompt_version": row["prompt_version"], "state": row["state"],
            "provider_call_attempted": outcome.get("provider_call_attempted", False), **measurement}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--case", required=True, type=int, help="Zero-based case index")
    parser.add_argument("--trial", required=True, type=int, choices=(1, 2))
    parser.add_argument("--free-plan-confirmed", required=True, action="store_true")
    args = parser.parse_args()
    if args.case < 0:
        parser.error("case must be nonnegative")
    plan = json.loads(read_private(args.plan, 131072))
    result = run(plan, args.case, args.trial)
    # Atomic separate result files survive a stopped evaluator. The request key is
    # already in the plan, so an interrupted write is resolved by replaying it.
    result["plan_hash"] = digest(plan)
    path = args.plan.with_name(f"{args.plan.stem}-case{args.case}-trial{args.trial}-{uuid4()}.json")
    write_private(path, json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("evaluation_failed_check_private_plan_and_service_availability") from None
