"""Local ingestion command for a pre-provisioned integration and job."""
import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/pipeguard/src"))

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from pipeguard.db.config import database_url
from pipeguard.ingestion.service import IngestionRejected, process, receive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--file", type=Path, help="Version 1 execution event JSON (maximum 64 KiB)")
    inputs.add_argument("--process-event", type=UUID, help="Retry a stored observation by internal UUID")
    parser.add_argument("--receive-only", action="store_true", help="Save receipt without projecting it")
    args = parser.parse_args()
    if args.process_event and args.receive_only:
        parser.error("--receive-only requires --file")
    engine = None
    try:
        engine = create_engine(database_url(), hide_parameters=True)
        output = {}
        if args.file:
            with args.file.open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise IngestionRejected("event_too_large")
            payload = json.loads(raw)
            receipt = receive(engine, payload)
            event_id = receipt.event_id
            output["replayed"] = receipt.replayed
        else:
            event_id = args.process_event
        output["event_id"] = str(event_id)
        # Print the durable receipt first so a later failure can be retried by ID.
        print(json.dumps(output), flush=True)
        if not args.receive_only:
            result = process(engine, event_id)
            print(json.dumps({"event_id": str(event_id), "processing_state": result.processing_state,
                              "error": result.error}))
            return 0 if result.processing_state == "processed" else 1
        return 0
    except ValidationError:
        print("invalid_event: check the version 1 execution contract", file=sys.stderr)
    except IngestionRejected as exc:
        print(str(exc), file=sys.stderr)
    except (OSError, ValueError, RuntimeError, SQLAlchemyError):
        # Do not echo payloads, filenames, credentials, or database exception text.
        print("ingestion_failed: check local configuration and event format", file=sys.stderr)
    finally:
        if engine is not None:
            engine.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
