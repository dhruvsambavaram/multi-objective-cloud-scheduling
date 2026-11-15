"""Google cluster trace (2011, v2) -> scheduling instance (PLAN.md §3.6).

Source: https://github.com/google/cluster-data/blob/master/ClusterData2011_2.md
We only need one ~4 MB part of the ``task_events`` table.

task_events columns (no header):
  0 timestamp [us]  1 missing info  2 job ID  3 task index  4 machine ID
  5 event type      6 user          7 scheduling class      8 priority
  9 CPU request     10 memory request   11 disk request     12 different-machine
Event types: 0 SUBMIT, 1 SCHEDULE, 2 EVICT, 3 FAIL, 4 FINISH, 5 KILL, 6 LOST, 7/8 UPDATE

Conversion assumptions (all listed in the README / report):
  A1  A task is usable if it has a SUBMIT, a SCHEDULE and a later FINISH event in
      the part, was submitted after the trace start (timestamp > 0) and has a
      non-zero CPU and memory request.
  A2  Runtime = FINISH - last SCHEDULE time; 1 slot = 60 s; p = ceil(runtime / 60).
  A3  CPU / memory requests are normalised by the trace to the largest machine
      in the Google cluster (= 1.0). Our "large" VM is assumed to be 20% of that
      machine, so 1 CPU unit = 0.2/16 and 1 MEM unit = 0.2/32 of the largest
      machine. Requests are rounded up and clipped to [1, large capacity].
  A4  Real submit times are kept in their observed *order and relative spacing*
      but rescaled linearly into a window whose length gives offered load rho
      (same definition as the synthetic generator), because a 100-task sample
      from a 12,000-machine cluster would otherwise be almost load-free.
  A5  The trace has no deadlines: d_i = r_i + ceil(tau * p_i), as for synthetic data.
  A6  Priority weight w_i = 1 + (trace priority >= 9) + (trace priority >= 11)
      (the trace's free / batch / production tiers).
"""

from __future__ import annotations

import math
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from .instance import Instance, Task, make_machines, offered_load_window

PART_URL = "https://commondatastorage.googleapis.com/clusterdata-2011-2/task_events/part-00000-of-00500.csv.gz"
COLS = ["ts", "missing", "job", "idx", "machine", "event", "user", "sclass", "prio", "cpu", "mem", "disk", "diffm"]
SLOT_SECONDS = 60
VM_FRACTION = 0.2  # large VM = 20% of the largest trace machine (A3)


def download(dest: str | Path, url: str = PART_URL) -> Path:
    dest = Path(dest)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, dest)
    return dest


def finished_tasks(part_csv_gz: str | Path) -> pd.DataFrame:
    """One row per usable finished task (assumption A1, A2)."""
    df = pd.read_csv(part_csv_gz, header=None, names=COLS)
    key = ["job", "idx"]
    sub = df[df.event == 0].groupby(key).agg(t_submit=("ts", "min"), cpu=("cpu", "last"), mem=("mem", "last"), prio=("prio", "last"))
    sch = df[df.event == 1].groupby(key).ts.max().rename("t_schedule")
    fin = df[df.event == 4].groupby(key).ts.max().rename("t_finish")
    j = pd.concat([sub, sch, fin], axis=1).dropna().reset_index()
    j = j[(j.t_finish > j.t_schedule) & (j.t_submit > 0) & (j.cpu > 0) & (j.mem > 0)]
    j["runtime_s"] = (j.t_finish - j.t_schedule) / 1e6
    return j.sort_values("t_submit").reset_index(drop=True)


def sample(tasks: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    return tasks.sample(n=n, random_state=seed).sort_values("t_submit").reset_index(drop=True)


def to_instance(rows: pd.DataFrame, n_machines: int = 6, seed: int = 0, rho: float = 1.0, tau: float = 2.0,
                name: str = "google2011_sample") -> Instance:
    rng = np.random.default_rng(seed)
    machines = make_machines(n_machines, rng)
    big = max(machines, key=lambda m: m.cpu)
    cpu_unit, mem_unit = VM_FRACTION / big.cpu, VM_FRACTION / big.mem
    cpu = np.clip(np.ceil(rows.cpu.to_numpy() / cpu_unit - 1e-9), 1, big.cpu).astype(int)
    mem = np.clip(np.ceil(rows.mem.to_numpy() / mem_unit - 1e-9), 1, big.mem).astype(int)
    p = np.maximum(1, np.ceil(rows.runtime_s.to_numpy() / SLOT_SECONDS)).astype(int)

    L = offered_load_window(float((cpu * p).sum()), float((mem * p).sum()), machines, rho)
    sub = rows.t_submit.to_numpy(dtype=float)
    span = sub.max() - sub.min()
    r = np.zeros(len(rows), dtype=int) if span == 0 else np.floor((sub - sub.min()) / span * (L - 1)).astype(int)
    w = 1 + (rows.prio.to_numpy() >= 9).astype(int) + (rows.prio.to_numpy() >= 11).astype(int)

    tasks = [Task(i, int(cpu[i]), int(mem[i]), int(p[i]), int(r[i]), int(r[i] + math.ceil(tau * p[i])), int(w[i]))
             for i in range(len(rows))]
    inst = Instance(name, tasks, machines, {
        "generator": "google-2011-trace", "source": PART_URL, "n_tasks": len(rows), "n_machines": n_machines,
        "seed": seed, "rho": rho, "tau": tau, "slot_seconds": SLOT_SECONDS, "vm_fraction": VM_FRACTION,
        "release_window": L,
    })
    inst.check_well_formed()
    return inst
