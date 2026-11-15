"""E2: scalability of CP-SAT - solve time and optimality gap vs number of tasks at a fixed time limit."""

import pandas as pd

from experiments.common import parser, run_methods, save, summary, write_table
from src.instance import generate


def main():
    a = parser(__doc__).parse_args()
    ns = [10, 20, 30, 50] if a.quick else [10, 20, 30, 50, 75, 100]
    seeds = range(2) if a.quick else range(3)
    tl = a.time_limit or (3 if a.quick else 10)
    rows = []
    for n in ns:
        m = max(3, min(10, n // 10))
        for seed in seeds:
            inst = generate(n, m, seed=100 + seed, rho=1.0)
            r, scheds, _ = run_methods(inst, tl, a.workers)
            info = scheds["CP-SAT"].info
            for x in r:
                x["time_limit"] = tl
                if x["method"] == "CP-SAT":
                    x["n_assign_vars"] = info["n_bool_assign"]
                    x["horizon"] = info["horizon"]
            rows += r
            c = next(x for x in r if x["method"] == "CP-SAT")
            print(f"  n={n} m={m} seed={seed}: {c['status']} t={c['solve_time']:.2f}s gap={c['gap']:.3%}")
    df = pd.DataFrame(rows)
    save(df, "e2_scalability.csv")
    c = df[df.method == "CP-SAT"].copy()
    c["optimal"] = (c.status == "OPTIMAL").astype(float)
    write_table(summary(c, ["n_tasks", "n_machines"], ["solve_time", "gap", "optimal", "n_assign_vars"]), "e2_scalability.md")


if __name__ == "__main__":
    main()
