"""E8: time-indexed MILP (Pyomo + HiGHS) vs CP-SAT on small instances, same horizon H for both.

Part A: same optimum? solve time? model size?   (n = 6..12 tasks, 3 machines, H = greedy makespan)
Part B: model size vs horizon - the MILP grows with H, CP-SAT does not.
"""

import pandas as pd

from experiments.common import WEIGHTS, parser, save, summary, write_table
from src import cpsat_model as cp
from src import milp_model as mi
from src.baselines import greedy
from src.instance import generate
from src.metrics import make_refs, makespan, objective
from src.validate import assert_valid


def compare(inst, H, milp_tl, workers, part):
    refs = make_refs(inst, greedy(inst))
    m = mi.solve(inst, WEIGHTS, refs, H, time_limit=milp_tl)
    c = cp.solve(inst, WEIGHTS, refs, cp.CpSatOptions(horizon=H, time_limit=milp_tl, workers=workers))
    out = []
    for s, solver in ((m, "MILP (HiGHS)"), (c, "CP-SAT")):
        if s is None:
            out.append({"part": part, "instance": inst.name, "n_tasks": inst.n, "H": H, "solver": solver, "status": "NO_SOLUTION"})
            continue
        assert_valid(inst, s, s.info.get("reported"))
        out.append({"part": part, "instance": inst.name, "n_tasks": inst.n, "H": H, "solver": solver,
                    "status": s.info["status"], "objective": objective(inst, s, WEIGHTS, refs),
                    "solve_time": s.info["solve_time"], "build_time": s.info["build_time"], "gap": s.info["gap"],
                    "n_binaries": s.info.get("n_binaries", s.info.get("n_bool_assign", 0) + inst.m),
                    "n_constraints": s.info.get("n_constraints")})
    return out


def main():
    a = parser(__doc__).parse_args()
    milp_tl = a.time_limit or (20 if a.quick else 120)
    rows = []
    for n in ([6, 8] if a.quick else [6, 8, 10, 12]):
        for seed in range(2 if a.quick else 3):
            inst = generate(n, 3, seed=500 + seed, rho=1.0)
            H = makespan(greedy(inst))
            rows += compare(inst, H, milp_tl, a.workers, "A")
            print(f"  n={n} seed={seed} H={H}: " + ", ".join(f"{r['solver']} {r['status']} {r.get('solve_time', 0):.2f}s" for r in rows[-2:]))
    inst = generate(8, 3, seed=500)
    H0 = makespan(greedy(inst))
    for f in ([1.0, 2.0] if a.quick else [1.0, 1.5, 2.0, 3.0, 4.0]):
        rows += compare(inst, int(round(H0 * f)), milp_tl, a.workers, "B")
        print(f"  H={int(round(H0 * f))}: MILP binaries={rows[-2]['n_binaries']} t={rows[-2]['solve_time']:.2f}s")
    df = pd.DataFrame(rows)
    save(df, "e8_milp.csv")
    A = df[df.part == "A"].copy()
    A["optimal"] = (A.status == "OPTIMAL").astype(float)
    write_table(summary(A, ["n_tasks", "solver"], ["objective", "solve_time", "n_binaries", "optimal"]), "e8_milp.md")


if __name__ == "__main__":
    main()
