"""Extract bounded check outcomes and rule fingerprints; never transmit SQL or rows."""
from hashlib import sha256
import json


def extract(artifacts):
    try:
        if any((artifacts / name).stat().st_size > 20_000_000 for name in ("manifest.json", "run_results.json")):
            return {"checks": [], "inventory_complete": False}
        manifest = json.loads((artifacts / "manifest.json").read_text())
        results = json.loads((artifacts / "run_results.json").read_text())
        nodes = manifest["nodes"]
        expected = {key: node for key, node in nodes.items() if node["resource_type"] == "test"}
        actual = {r["unique_id"]: r for r in results["results"]}
        duplicates = len(actual) != len(results["results"])
        matching = (manifest["metadata"].get("invocation_id") is not None and
                    manifest["metadata"].get("invocation_id") == results.get("metadata", {}).get("invocation_id"))
        checks = []
        macros = {key: value.get("macro_sql") for key, value in manifest.get("macros", {}).items()}
        # Reports admit at most 100 checks. Do not hash discarded rules from an
        # unexpectedly large manifest; keep the sampled inventory incomplete.
        for key, node in sorted(expected.items())[:100]:
            code = {"test": node.get("raw_code"), "config": node.get("config"),
                    "dbt_version": manifest["metadata"]["dbt_version"],
                    "macros": macros,
                    "parents": {k: nodes.get(k, {}).get("checksum") for k in node.get("depends_on", {}).get("nodes", [])}}
            version = sha256(json.dumps(code, sort_keys=True).encode()).hexdigest()
            result = actual.get(key, {})
            status = {"pass": "pass", "fail": "fail", "warn": "fail", "error": "error", "skipped": "skipped"}.get(result.get("status"), "unknown")
            if duplicates or not matching:
                status = "unknown"
            failures = result.get("failures")
            checks.append({"rule_id": key if len(key) <= 255 else "dbt." + sha256(key.encode()).hexdigest(),
                           "rule_version": version, "status": status,
                           "failures": failures if type(failures) is int and 0 <= failures <= 2147483647 else None})
        complete = bool(expected) and len(expected) <= 100 and expected.keys() <= actual.keys() and not duplicates and matching and actual.keys() <= nodes.keys()
        return {"checks": checks, "inventory_complete": complete}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return {"checks": [], "inventory_complete": False}
