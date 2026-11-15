"""E7: validation on samples of the real Google 2011 cluster trace.

The first run downloads one ~4 MB part of task_events into data/raw/ and stores a
pool of usable finished tasks in data/trace/google2011_pool.csv (shipped with the
code, so later runs and fresh machines need no network access).
"""

import pandas as pd

from experiments.common import DATA, RESULTS, parser, run_methods, save, summary, write_table
from src import trace

POOL = DATA / "trace" / "google2011_pool.csv"
POOL_SIZE = 3000


def load_pool() -> pd.DataFrame:
    if not POOL.exists():
        part = trace.download(DATA / "raw" / "task_events-part-00000-of-00500.csv.gz")
        tasks = trace.finished_tasks(part)
        POOL.parent.mkdir(parents=True, exist_ok=True)
        trace.sample(tasks, min(POOL_SIZE, len(tasks)), seed=0).to_csv(POOL, index=False)
        print(f"  {len(tasks)} usable finished tasks in the part; pool of {POOL_SIZE} saved to {POOL}")
    return pd.read_csv(POOL)


def main():
    a = parser(__doc__).parse_args()
    tl = a.time_limit or (3 if a.quick else 10)
    pool = load_pool()
    rows = []
    for seed in range(2 if a.quick else 5):
        sample = trace.sample(pool, 60, seed=seed)
        inst = trace.to_instance(sample, n_machines=6, seed=seed, rho=1.0, tau=2.0, name=f"google2011_s{seed}")
        inst.save(DATA / "trace" / f"{inst.name}.json")
        r, _, _ = run_methods(inst, tl, a.workers, save_dir=RESULTS / "schedules" / "e7")
        rows += r
        print(f"  sample {seed}: " + ", ".join(f"{x['method']}={x['objective']:.3f}" for x in r))
    df = pd.DataFrame(rows)
    save(df, "e7_trace.csv")
    write_table(summary(df, ["method"], ["objective", "makespan_over_lb", "cost", "weighted_tardiness", "n_late", "leased_util_cpu"]), "e7_trace.md")


if __name__ == "__main__":
    main()
