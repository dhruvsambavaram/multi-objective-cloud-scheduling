"""Entry point.

    python main.py demo [--n 30 --m 5 --seed 0 --rho 1.0 --tau 2.0 --time-limit 10]
        generate one instance, run FCFS / SJF / Greedy / CP-SAT, validate, print a table
    python main.py solve data/synthetic/<instance>.json [--time-limit 10] [--out schedule.csv]
        solve a saved instance with CP-SAT and write the schedule
    python main.py experiments [--quick]
        run E1-E8 and draw every figure (same as python -m experiments.run_all)
"""

from __future__ import annotations

import argparse

import pandas as pd

from experiments.common import run_methods
from src.instance import Instance, generate


def demo(a):
    inst = generate(a.n, a.m, seed=a.seed, rho=a.rho, tau=a.tau)
    print(f"Instance {inst.name}: {inst.n} tasks, machines = {[mc.kind for mc in inst.machines]}")
    rows, scheds, refs = run_methods(inst, a.time_limit, a.workers)
    print(f"LB(Cmax) = {refs.lb:.0f}, Cost_ref (greedy) = {refs.cost_ref:.0f}, sum p = {refs.work:.0f}")
    cols = ["method", "objective", "makespan", "makespan_over_lb", "cost", "weighted_tardiness", "n_late",
            "machines_used", "leased_util_cpu", "solve_time"]
    print(pd.DataFrame(rows)[cols].to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    info = scheds["CP-SAT"].info
    print(f"CP-SAT status {info['status']}, gap {info['gap']:.2%}, warm start from {info['hint_from']}; "
          f"all schedules passed the independent validator.")


def solve(a):
    inst = Instance.load(a.instance)
    rows, scheds, _ = run_methods(inst, a.time_limit, a.workers)
    print(pd.DataFrame(rows)[["method", "objective", "makespan", "cost", "weighted_tardiness"]].to_string(index=False))
    if a.out:
        scheds["CP-SAT"].save_csv(a.out)
        print(f"wrote {a.out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--n", type=int, default=30)
    d.add_argument("--m", type=int, default=5)
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--rho", type=float, default=1.0)
    d.add_argument("--tau", type=float, default=2.0)
    s = sub.add_parser("solve")
    s.add_argument("instance")
    s.add_argument("--out")
    for p in (d, s):
        p.add_argument("--time-limit", type=float, default=10)
        p.add_argument("--workers", type=int, default=8)
    e = sub.add_parser("experiments")
    e.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    if a.cmd == "demo":
        demo(a)
    elif a.cmd == "solve":
        solve(a)
    else:
        from experiments.run_all import run_all

        run_all(a.quick)


if __name__ == "__main__":
    main()
