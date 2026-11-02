"""Manually investigate one stored evidence bundle, or verify synthetic connectivity."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from uuid import UUID, uuid4

from local_files import ensure_private_directory, write_private

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/pipeguard/src"))
from pipeguard.detection.service import digest
from pipeguard.investigation.core import InvestigationRejected, project_bundle
from pipeguard.investigation.groq import MODEL, PROMPT_VERSION, investigate, json_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--bundle-id", type=UUID)
    source.add_argument("--verify-connection", action="store_true")
    parser.add_argument("--free-plan-confirmed", action="store_true",
                        help="Operator confirms this key's Groq organization remains on the Free plan")
    parser.add_argument("--dry-run", action="store_true", help="Project locally; make no Groq request")
    parser.add_argument("--request-key", type=UUID, help="Reuse an existing request key to inspect/replay without another generation")
    args = parser.parse_args()
    os.umask(0o077)
    if not args.dry_run and not args.free_plan_confirmed:
        raise InvestigationRejected("free_plan_confirmation_required")
    bundle_id, bundle_hash, mapping = None, None, {}
    if args.verify_connection:
        packet = {"schema_version": 1, "condition": "execution_failure", "missing_evidence_present": True,
                  "items": [{"citation": "e1", "kind": "ingested_events", "facts": {
                      "run": "run_1", "attempt": 1, "state": "failed", "error_code": "source_unavailable"}},
                            {"citation": "e2", "kind": "ingested_events", "facts": {
                                "run": "run_1", "attempt": 2, "state": "succeeded"}}]}
    else:
        bundle_id = str(args.bundle_id)
        bundle = json_request("http://127.0.0.1:8000/v1/evidence-bundles/" + bundle_id,
                              key=os.environ["PIPEGUARD_ADMIN_TOKEN"])
        if args.dry_run:
            packet, mapping = project_bundle(bundle)
        bundle_hash = bundle["payload_hash"]
    if args.dry_run:
        print(json.dumps({"mode": "local_projection_only", "groq_request_sent": False,
                          "evidence_count": len(packet["items"]), "bytes": len(json.dumps(packet).encode())}))
        return
    if not args.verify_connection:
        request_key = str(args.request_key or uuid4())
        print(json.dumps({"request_key": request_key}), flush=True)
        record = json_request("http://127.0.0.1:8000/v1/incidents/" + str(UUID(bundle["incident_id"])) + "/investigations",
            key=os.environ["PIPEGUARD_ADMIN_TOKEN"], body={"request_key": request_key,
            "bundle_id": bundle_id, "free_plan_confirmed": True})
        print(json.dumps({"id": record["id"], "state": record["state"], "request_key": request_key}))
        return
    result = investigate(packet, os.environ.get("GROQ_API_KEY", ""))
    record = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "provider": "groq", "model": MODEL, "prompt_version": PROMPT_VERSION,
              "synthetic": args.verify_connection, "bundle_id": bundle_id, "bundle_hash": bundle_hash,
              "packet": packet, "packet_hash": digest(packet), "citation_map": mapping,
              "result": result.model_dump(), "operator_asserted_free_plan": True,
              "notice": "Advisory hypotheses only. Citation membership is checked; semantic correctness is not proven."}
    directory = ROOT / "data/local/investigations"
    ensure_private_directory(directory)
    path = directory / (str(uuid4()) + ".json")
    write_private(path, json.dumps(record, sort_keys=True, indent=2) + "\n", exclusive=True)
    print(json.dumps({"status": "validated_response", "synthetic": args.verify_connection,
                      "abstained": result.abstained, "record": str(path.relative_to(ROOT))}))


if __name__ == "__main__":
    try:
        main()
    except InvestigationRejected as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit("investigation_failed_private_details_withheld") from None
