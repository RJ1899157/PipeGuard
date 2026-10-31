"""Extract bounded check outcomes and rule fingerprints; never transmit SQL or rows."""
from hashlib import sha256
import json


def extract(artifacts):
    try:
        manifest = json.loads((artifacts / "manifest.json").read_text())
        results = json.loads((artifacts / "run_results.json").read_text())
        nodes = manifest["nodes"]
        expected = {key: node for key, node in nodes.items() if node["resource_type"] == "test"}
        actual = {r["unique_id"]: r for r in results["results"]}
        checks = []
        for key, node in sorted(expected.items()):
            code = {"test": node.get("raw_code"), "config": node.get("config"),
                    "dbt_version": manifest["metadata"]["dbt_version"],
                    "macros": {k: v.get("macro_sql") for k, v in manifest.get("macros", {}).items()},
                    "parents": {k: nodes.get(k, {}).get("checksum") for k in node.get("depends_on", {}).get("nodes", [])}}
            version = sha256(json.dumps(code, sort_keys=True).encode()).hexdigest()
            result = actual.get(key, {})
            status = {"pass": "pass", "fail": "fail", "warn": "fail", "error": "error", "skipped": "skipped"}.get(result.get("status"), "unknown")
            failures = result.get("failures")
            checks.append({"rule_id": key if len(key) <= 255 else "dbt." + sha256(key.encode()).hexdigest(),
                           "rule_version": version, "status": status,
                           "failures": failures if type(failures) is int and 0 <= failures <= 2147483647 else None})
        complete = bool(expected) and expected.keys() <= actual.keys() and len(checks) <= 100
        return {"checks": checks[:100], "inventory_complete": complete}
    except (OSError, ValueError, TypeError, KeyError):
        return {"checks": [], "inventory_complete": False}
