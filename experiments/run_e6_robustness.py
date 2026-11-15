"""E6: robustness - replay plans under perturbed durations p~ = round(p (1 + U[-delta, delta])).

Compared policies (same random draws for all of them, i.e. common random numbers):
  * CP-SAT plan, replayed       (machine + per-machine order kept, starts recomputed)
  * Greedy plan, replayed
  * Greedy re-run on the actual durations ("clairvoyant" greedy: an upper reference
    for what a myopic policy could do if it knew the true durations)
"""

import numpy as np
import pandas as pd

from experiments.common import WEIGHTS, parser, run_methods, save, summary, write_table
from src.baselines import greedy
from src.instance import generate
from src.metrics import evaluate
from src.simulate import perturb, replay
from src.validate import assert_valid


def main():
    a = parser(__doc__).parse_args()
    deltas = [0.0, 0.1, 0.2, 0.3]
    seeds = range(2) if a.quick else range(5)
    reps = 10 if a.quick else 30
    tl = a.time_limit or (3 if a.quick else 10)
    rows = []
    for seed in seeds:
        inst = generate(40, 5, seed=400 + seed, rho=1.0)
        _, scheds, refs = run_methods(inst, tl, a.workers)
        nominal = {m: evaluate(inst, scheds[m], WEIGHTS, refs) for m in ("CP-SAT", "Greedy")}
        rng = np.random.default_rng(seed)
        for delta in deltas:
            for rep in range(reps if delta > 0 else 1):
                actual = perturb(inst, delta, rng)
                runs = {
                    "CP-SAT plan (replayed)": replay(scheds["CP-SAT"], actual),
                    "Greedy plan (replayed)": replay(scheds["Greedy"], actual),
                    "Greedy re-run (clairvoyant)": greedy(actual),
                }
                for name, s in runs.items():
                    assert_valid(actual, s)
                    r = evaluate(actual, s, WEIGHTS, refs)  # same normalisation as the nominal plan
                    plan = "CP-SAT" if name.startswith("CP-SAT") else "Greedy"
                    r.update({"policy": name, "delta": delta, "rep": rep, "seed": seed,
                              "nominal_objective": nominal[plan]["objective"],
                              "nominal_makespan": nominal[plan]["makespan"]})
                    rows.append(r)
        print(f"  seed={seed} done")
    df = pd.DataFrame(rows)
    df["objective_degradation"] = df.objective / df.nominal_objective - 1
    save(df, "e6_robustness.csv")
    write_table(summary(df, ["delta", "policy"], ["objective", "makespan", "cost", "weighted_tardiness", "objective_degradation"]), "e6_robustness.md")


if __name__ == "__main__":
    main()
