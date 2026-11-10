"""Reproducible Phase 1 baseline: direct JuliaCall versus Jupy.

Report times; do not assert speedups or compare cold-start samples across jobs.
Run in a project with JuliaCall and matching PythonCall already installed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from statistics import median
from time import perf_counter_ns


def measure(call, n=200):
    for _ in range(20):
        call()
    results = []
    for _ in range(n):
        start = perf_counter_ns()
        call()
        results.append(perf_counter_ns() - start)
    results.sort()
    return {"median_ns": median(results), "p90_ns": results[int(.9 * (len(results) - 1))]}


def cold_start(command: str, env: dict[str, str], cwd: Path, repeats=2):
    results = []
    for _ in range(repeats):
        start = perf_counter_ns()
        subprocess.run([sys.executable, "-c", command], env=env, cwd=cwd, check=True,
                       stdout=subprocess.DEVNULL)
        results.append((perf_counter_ns() - start) / 1_000_000)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    args.output = args.output.resolve()
    executable = shutil.which("julia")
    if not executable or not (project / "Project.toml").is_file():
        raise RuntimeError("Julia executable and initialized Julia project are required")
    env = os.environ.copy()
    env.update({
        "PYTHON_JULIACALL_EXE": str(Path(executable).resolve()),
        "PYTHON_JULIACALL_PROJECT": str(project),
    })
    direct_cold = cold_start(
        "from juliacall import Main; Main.seval('import LinearAlgebra')", env, project
    )
    jupy_cold = cold_start(
        "import jupy; jupy.load('LinearAlgebra')", env, project
    )

    # Both imports use exactly the same Julia project and interpreter.
    os.environ.update({
        "PYTHON_JULIACALL_EXE": env["PYTHON_JULIACALL_EXE"],
        "PYTHON_JULIACALL_PROJECT": env["PYTHON_JULIACALL_PROJECT"],
    })
    import jupy
    os.chdir(project)
    jl = jupy.julia.start()
    jl.seval("import LinearAlgebra")
    direct_module = jl.LinearAlgebra
    jupy_module = jupy.load("LinearAlgebra")
    values = [3.0, 4.0]
    results = {
        "methodology": "same process, same imported module, 20 warmups, 200 timed iterations per operation; wall-clock nanoseconds",
        "python": sys.version.split()[0],
        "julia_project": str(project),
        "cold_start_ms": {"direct": direct_cold, "jupy": jupy_cold},
        "cached_module_lookup": {
            "direct": measure(lambda: jl.LinearAlgebra),
            "jupy": measure(lambda: jupy.load("LinearAlgebra")),
        },
        "native_bridge_call": {
            "direct": measure(lambda: direct_module.norm(values)),
            "jupy": measure(lambda: jupy_module.norm(values)),
        },
        "module_handles_identical": direct_module is jupy_module,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
