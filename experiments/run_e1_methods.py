"""E1: method comparison on identical synthetic instances (~10 seeds per size)."""

import pandas as pd

from experiments.common import DATA, RESULTS, parser, run_methods, save, summary, write_table
from src.instance import Instance, generate


def main():
    a = parser(__doc__).parse_args()
    sizes = [(20, 4), (50, 6)] if a.quick else [(20, 4), (50, 6), (100, 8)]
    seeds = range(3) if a.quick else range(10)
    tl = a.time_limit or (3 if a.quick else 10)
    rows = []
    for n, m in sizes:
        for seed in seeds:
            inst = generate(n, m, seed=seed, rho=1.0, tau=2.0)
            path = DATA / "synthetic" / f"{inst.name}.json"
            inst.save(path)
            inst = Instance.load(path)  # every method reads the identical file
            r, _, _ = run_methods(inst, tl, a.workers, save_dir=RESULTS / "schedules" / "e1")
            rows += r
            print(f"  n={n} seed={seed}: " + ", ".join(f"{x['method']}={x['objective']:.3f}" for x in r))
    df = pd.DataFrame(rows)
    save(df, "e1_methods.csv")
    cols = ["objective", "makespan_over_lb", "cost", "weighted_tardiness", "n_late", "leased_util_cpu", "solve_time"]
    t = summary(df, ["n_tasks", "method"], cols)
    write_table(t, "e1_methods.md")
    print(t.to_string(index=False))


if __name__ == "__main__":
    main()
