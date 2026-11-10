"""Phase 2 contract overhead baseline, independent of PythonCall/JuliaCall.

Only median descriptive timings; CI never asserts a performance speedup.
"""

from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from jupy.contracts import bind, read_contract


class MetadataArray:
    dtype = "float64"
    def __init__(self, side):
        self.shape = (side, side)
    def __getitem__(self, key):
        raise AssertionError("structural contract unexpectedly examined array elements")


def measure(f, count=5000):
    for _ in range(100):
        f()
    samples = []
    for _ in range(count):
        start = perf_counter_ns()
        f()
        samples.append(perf_counter_ns() - start)
    return round(statistics.median(samples))


def run(output):
    contract = read_contract(ROOT / "tests" / "contracts" / "structural.toml")
    def function(n, arr):
        return n + 1

    trusted = bind(function, contract, mode="trusted")
    structural = bind(function, contract, mode="structural")
    assert trusted is function
    measurements = {}
    for n in (1, 100, 100000):
        a = MetadataArray(3 * n)
        assert structural(n, a) == n + 1
        measurements[str(n)] = {
            "direct_ns": measure(lambda: function(n, a)),
            "trusted_ns": measure(lambda: trusted(n, a)),
            "structural_ns": measure(lambda: structural(n, a)),
        }
    result = {
        "description": "Per-call structural overhead with fixed rank and array metadata only",
        "no_wrapper_identity": trusted is function,
        "samples_per_case": 5000,
        "results": measurements,
        "note": "CPU/runner noise may dominate. Shape sizes are metadata-only, not allocated tensors.",
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "benchmark-results/contract-python.json")
