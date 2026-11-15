"""E5: anytime behaviour - CP-SAT objective and optimality gap vs time limit (with / without warm start)."""

import pandas as pd

from experiments.common import WEIGHTS, parser, save, summary, write_table
from src import cpsat_model as cp
from src.baselines import BASELINES
from src.instance import generate
from src.metrics import make_refs, objective
from src.validate import assert_valid


def main():
    a = parser(__doc__).parse_args()
    limits = [1, 3, 5] if a.quick else [1, 5, 10, 30, 60]
    seeds = range(1) if a.quick else range(2)
    rows = []
    for seed in seeds:
        inst = generate(60 if a.quick else 100, 8, seed=300 + seed, rho=1.2)
        bs = {k: f(inst) for k, f in BASELINES.items()}
        refs = make_refs(inst, bs["Greedy"])
        best = min(bs.values(), key=lambda s: objective(inst, s, WEIGHTS, refs))
        for warm in (True, False):
            for tl in limits:
                s = cp.solve(inst, WEIGHTS, refs, cp.CpSatOptions(time_limit=tl, workers=a.workers, hint=best if warm else None))
                if s is None:
                    rows.append({"instance": inst.name, "seed": seed, "warm_start": warm, "time_limit": tl, "status": "NO_SOLUTION"})
                    continue
                assert_valid(inst, s, s.info["reported"])
                rows.append({"instance": inst.name, "seed": seed, "warm_start": warm, "time_limit": tl,
                             "status": s.info["status"], "objective": objective(inst, s, WEIGHTS, refs),
                             "best_baseline_objective": objective(inst, best, WEIGHTS, refs),
                             "gap": s.info["gap"], "solve_time": s.info["solve_time"]})
                print(f"  seed={seed} warm={warm} tl={tl}: obj={rows[-1]['objective']:.4f} gap={s.info['gap']:.2%}")
    df = pd.DataFrame(rows)
    df["objective_vs_best_found"] = df.objective / df.groupby("instance").objective.transform("min")
    save(df, "e5_anytime.csv")
    write_table(summary(df.dropna(subset=["objective"]), ["warm_start", "time_limit"], ["objective_vs_best_found", "gap"]), "e5_anytime.md")


if __name__ == "__main__":
    main()
