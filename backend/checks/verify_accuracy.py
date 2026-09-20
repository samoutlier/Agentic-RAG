"""Check the agents' output against facts read by hand from the documents.

    python checks/verify_accuracy.py            every analysed sample document
    python checks/verify_accuracy.py esds-rhp   only documents whose id matches

Each check in expected.json names a value ("offer.structure.fresh_issue_shares"),
what it should be, and the page it was read from. This script reads the saved
agent outputs in ipo_data/<document>/results/ and compares them, so a change
to a prompt, a model or the parser that breaks an extraction shows up here
instead of in a report. It uses no Groq tokens: everything is already saved.

Exit code 1 if any check fails, so it can run in a pipeline.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.drhp.parser import document_folder, load_result  # noqa: E402

EXPECTED = Path(__file__).resolve().parent / "expected.json"
# Numbers are rounded at several steps, so allow a small relative difference
TOLERANCE = 0.005
STEP = re.compile(r"([^.\[\]]+)(?:\[(\d+)\])?")


def resolve(path: str, results: dict):
    """Follow a path like "offer.structure.objects[0].amount" through the
    saved results. Returns MISSING if any step isn't there."""
    value = results
    for name, index in STEP.findall(path):
        if not isinstance(value, dict) or name not in value:
            return "MISSING"
        value = value[name]
        if index:
            if not isinstance(value, list) or int(index) >= len(value):
                return "MISSING"
            value = value[int(index)]
    return value


def matches(expected, actual) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(actual - expected) <= max(abs(expected) * TOLERANCE, 0.01)
    return expected == actual


def check_document(doc_id: str, spec: dict) -> tuple[int, int]:
    results = {name: load_result(doc_id, name) or {} for name in
               ("risk", "financial", "legal", "business", "offer", "score", "report")}
    if not any(results.values()):
        print(f"\n{spec['filename']}: not analysed yet, skipping ({doc_id})")
        return 0, 0

    print(f"\n{spec['filename']}")
    passed = 0
    for check in spec["checks"]:
        actual = resolve(check["path"], results)
        ok = matches(check["expect"], actual)
        passed += ok
        print(f"  {'PASS' if ok else 'FAIL'}  {check['what']:<48} expected {check['expect']!r:>14}"
              f"   got {actual!r}")
        if not ok:
            print(f"        read from the document at {check['source']}")
    return passed, len(spec["checks"])


def main(patterns: list[str]) -> int:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    total_passed = total = 0
    for doc_id, spec in expected.items():
        if doc_id.startswith("_"):
            continue
        if patterns and not any(pattern in doc_id for pattern in patterns):
            continue
        if not document_folder(doc_id).exists():
            print(f"\n{spec['filename']}: no saved data, skipping ({doc_id})")
            continue
        passed, count = check_document(doc_id, spec)
        total_passed += passed
        total += count

    if not total:
        print("\nNothing to check. Analyse a sample document first.")
        return 0
    print(f"\n{total_passed} of {total} checks passed.")
    return 0 if total_passed == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
