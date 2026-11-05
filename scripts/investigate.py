"""Manually investigate stored evidence, or read provider model metadata without generation."""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/pipeguard/src"))
from pipeguard.investigation.core import InvestigationRejected, project_bundle
from pipeguard.investigation.groq import MODEL, PROMPT_VERSION, json_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--bundle-id", type=UUID)
    source.add_argument("--verify-connection", action="store_true",
                        help="Read authenticated Groq model metadata; never generate a response")
    parser.add_argument("--free-plan-confirmed", action="store_true",
                        help="Operator confirms this key's Groq organization remains on the Free plan")
    parser.add_argument("--dry-run", action="store_true", help="Inspect locally; make no Groq request")
    parser.add_argument("--request-key", type=UUID, help="Reuse an existing request key without another generation")
    args = parser.parse_args()
    if args.verify_connection and args.request_key:
        parser.error("--request-key requires --bundle-id")
    if not args.dry_run and not args.free_plan_confirmed:
        raise InvestigationRejected("free_plan_confirmation_required")
    if args.verify_connection:
        if not args.dry_run:
            key = os.environ.get("GROQ_API_KEY", "")
            if not key.strip():
                raise InvestigationRejected("groq_key_missing")
            models = json_request("https://api.groq.com/openai/v1/models", key=key)
            if (not isinstance(models, dict) or not isinstance(models.get("data"), list)
                    or any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
                           or not row["id"] or ("active" in row and type(row["active"]) is not bool)
                           for row in models["data"])):
                raise InvestigationRejected("invalid_model_metadata")
            if not any(row["id"] == MODEL and row.get("active", True) for row in models["data"]):
                raise InvestigationRejected("configured_model_unavailable")
        print(json.dumps({"mode": "provider_metadata_only", "groq_request_sent": not args.dry_run,
                          "generation_requested": False, "model": MODEL, "prompt_version": PROMPT_VERSION,
                          "model_available": None if args.dry_run else True, "billing_plan_verified": False}))
        return
    bundle_id = str(args.bundle_id)
    bundle = json_request("http://127.0.0.1:8000/v1/evidence-bundles/" + bundle_id,
                          key=os.environ["PIPEGUARD_ADMIN_TOKEN"])
    if args.dry_run:
        packet, _ = project_bundle(bundle)
        print(json.dumps({"mode": "local_projection_only", "groq_request_sent": False,
                          "evidence_count": len(packet["items"]), "bytes": len(json.dumps(packet).encode())}))
        return
    request_key = str(args.request_key or uuid4())
    print(json.dumps({"request_key": request_key}), flush=True)
    record = json_request("http://127.0.0.1:8000/v1/incidents/" + str(UUID(bundle["incident_id"])) + "/investigations",
        key=os.environ["PIPEGUARD_ADMIN_TOKEN"], body={"request_key": request_key,
        "bundle_id": bundle_id, "free_plan_confirmed": True})
    print(json.dumps({"id": record["id"], "state": record["state"], "request_key": request_key}))


if __name__ == "__main__":
    try:
        main()
    except InvestigationRejected as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit("investigation_failed_private_details_withheld") from None
