"""E3: load sensitivity - vary offered load rho, report late tasks, utilisation, gap to CP-SAT."""

import pandas as pd

from experiments.common import parser, run_methods, save, summary, write_table
from src.instance import generate


def main():
    a = parser(__doc__).parse_args()
    rhos = [0.5, 1.0, 1.5] if a.quick else [0.5, 0.75, 1.0, 1.25, 1.5]
    seeds = range(2) if a.quick else range(5)
    tl = a.time_limit or (3 if a.quick else 10)
    rows = []
    for rho in rhos:
        for seed in seeds:
            inst = generate(40, 5, seed=200 + seed, rho=rho, tau=2.0)
            r, _, _ = run_methods(inst, tl, a.workers)
            ref = next(x for x in r if x["method"] == "CP-SAT")
            for x in r:
                x["makespan_vs_cpsat"] = x["makespan"] / ref["makespan"]
                x["objective_vs_cpsat"] = x["objective"] / ref["objective"]
            rows += r
            print(f"  rho={rho} seed={seed}: " + ", ".join(f"{x['method']}={x['objective_vs_cpsat']:.3f}" for x in r))
    df = pd.DataFrame(rows)
    save(df, "e3_load.csv")
    write_table(summary(df, ["rho", "method"], ["objective_vs_cpsat", "makespan_vs_cpsat", "n_late", "util_cpu", "leased_util_cpu"]), "e3_load.md")


if __name__ == "__main__":
    main()
