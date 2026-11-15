"""E4: cost vs makespan Pareto front by the epsilon-constraint method (plus a weighted-sum sweep for contrast).

For each eps in [Cmax_min, Cmax at min cost]:  minimise Cost  s.t.  Cmax <= eps
(lexicographic tie-break on Cmax so returned points are not weakly dominated).
Tardiness is not part of this bi-objective study.
"""

import numpy as np
import pandas as pd

from experiments.common import parser, save, write_table
from src import cpsat_model as cp
from src.baselines import BASELINES
from src.metrics import Weights, cost, make_refs, makespan
from src.instance import generate
from src.validate import assert_valid


def main():
    a = parser(__doc__).parse_args()
    tl = a.time_limit or (5 if a.quick else 30)
    n_eps = 6 if a.quick else 14
    inst = generate(24, 5, seed=0, rho=2.0)  # capacity-bound, so the trade-off is visible
    bs = {k: f(inst) for k, f in BASELINES.items()}
    refs = make_refs(inst, bs["Greedy"])
    hint = min(bs.values(), key=makespan)
    rows = []

    def record(s, kind, eps=None, alpha=None):
        assert_valid(inst, s, s.info.get("reported"))
        rows.append({"kind": kind, "eps": eps, "alpha": alpha, "makespan": makespan(s), "cost": cost(inst, s),
                     "status": s.info.get("status"), "gap": s.info.get("gap")})

    def solve(**kw):
        return cp.solve(inst, Weights(), refs, cp.CpSatOptions(time_limit=tl, workers=a.workers, **kw))

    lo = solve(objective="makespan", hint=hint)
    hi = solve(objective="cost")
    record(lo, "endpoint")
    record(hi, "endpoint")
    c_lo, c_hi = makespan(lo), makespan(hi)
    print(f"  Cmax range [{c_lo}, {c_hi}], cost range [{cost(inst, hi)}, {cost(inst, lo)}]")
    # Makespan is integer, so sweeping every integer eps gives the complete front.
    grid = range(c_lo, c_hi + 1) if c_hi - c_lo <= 40 else sorted(set(np.linspace(c_lo, c_hi, n_eps).round().astype(int)))
    for eps in grid:
        s = solve(objective="cost", makespan_cap=int(eps), hint=lo)
        record(s, "eps", eps=int(eps))
        print(f"  eps={eps}: Cmax={makespan(s)} cost={cost(inst, s)} {s.info['status']}")

    for alpha in np.linspace(0, 1, 6 if a.quick else 11):
        # Weighted sum of the two normalised terms: alpha * Cmax/LB + (1 - alpha) * Cost/Cost_ref
        s = cp.solve(inst, Weights(float(alpha), float(1 - alpha), 0.0), refs,
                     cp.CpSatOptions(time_limit=tl, workers=a.workers, hint=hint))
        record(s, "weighted_sum", alpha=round(float(alpha), 2))

    for name, s in bs.items():
        record(s, name)

    df = pd.DataFrame(rows)
    # Non-dominated filter over the eps points (the front itself).
    eps = df[df.kind.isin(["eps", "endpoint"])].sort_values(["makespan", "cost"])
    front, best = [], np.inf
    for i, r in eps.iterrows():
        if r.cost < best:
            front.append(i)
            best = r.cost
    df["on_front"] = df.index.isin(front)
    df["instance"] = inst.name
    save(df, "e4_pareto.csv")
    write_table(df[df.on_front][["makespan", "cost", "status"]].drop_duplicates().sort_values("makespan"), "e4_pareto_front.md")


if __name__ == "__main__":
    main()
