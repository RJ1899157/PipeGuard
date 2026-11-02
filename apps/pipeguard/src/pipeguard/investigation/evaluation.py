"""Deterministic acceptance scoring; never calls a provider or executes recovery.

Labels describe observable source claims, not independently verified root causes.
Schema/grounding safety and useful coverage are deliberately separate measurements.
"""
from pipeguard.investigation.core import validate_answer


def score(answer, packet, expected_categories, *, must_abstain=False):
    try:
        result = validate_answer(answer, packet)
    except ValueError:
        return {"safe": False, "useful": False, "reason": "rejected_answer"}
    categories = {hypothesis.category for hypothesis in result.hypotheses}
    expected = set(expected_categories)
    safe = (not categories if must_abstain else categories <= expected)
    useful = result.abstained if must_abstain else bool(categories) and categories == expected
    return {"safe": safe, "useful": safe and useful,
            "reason": "abstained" if result.abstained else "supported_findings"}
