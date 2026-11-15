"""Run every experiment (E1-E8) in order, then draw all figures.

    python -m experiments.run_all          # full configuration (~30 min on 8 cores)
    python -m experiments.run_all --quick  # smoke configuration (~3 min)
"""

import subprocess
import sys
import time

from experiments.common import ROOT

SCRIPTS = ["run_e1_methods", "run_e2_scalability", "run_e3_load", "run_e4_pareto", "run_e5_anytime",
           "run_e6_robustness", "run_e7_trace", "run_e8_milp", "plots"]


def run_all(quick: bool = False) -> None:
    for s in SCRIPTS:
        t0 = time.perf_counter()
        print(f"=== {s}", flush=True)
        args = [sys.executable, "-m", f"experiments.{s}"] + (["--quick"] if quick and s != "plots" else [])
        subprocess.run(args, cwd=ROOT, check=True)  # separate process each: keeps HiGHS and OR-Tools apart
        print(f"=== {s} finished in {time.perf_counter() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    run_all("--quick" in sys.argv)
