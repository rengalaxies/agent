"""Independent synthetic-test oracle, never included in graph read grants."""

from collections import Counter
import hashlib
import json

DATASET = [{"id": i} for i in range(1, 251)]
DATASET_BYTES = (json.dumps(DATASET, separators=(",", ":")) + "\n").encode()
DATASET_SHA256 = hashlib.sha256(DATASET_BYTES).hexdigest()


def check_ids(actual):
    if not isinstance(actual, list) or any(type(x) is not int for x in actual):
        raise ValueError("invalid_consumer_output")
    counts = Counter(actual)
    missing = sorted(set(range(1, 251)) - counts.keys())
    unexpected = sorted(counts.keys() - set(range(1, 251)))
    duplicate = sorted(k for k, v in counts.items() if v > 1)
    passed = not (missing or unexpected or duplicate) and len(actual) == 250
    return dict(
        expected_count=250,
        actual_count=len(actual),
        missing_ids=missing,
        duplicate_ids=duplicate,
        unexpected_ids=unexpected,
        passed=passed,
        status="PASS" if passed else "FAIL",
    )
