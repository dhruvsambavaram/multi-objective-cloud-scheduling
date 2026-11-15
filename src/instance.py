"""Data model, JSON I/O and the seeded synthetic instance generator.

Units
-----
* Time is measured in integer slots (1 slot = 1 minute by convention).
* CPU and memory are integer "units". The three VM types below define the scale:
  a small VM has 4 CPU / 8 MEM units, a large VM has 16 CPU / 32 MEM units.
* Prices are integer cost units per leased slot (``price``) plus a one-off
  activation fee (``fixed``) paid if the machine runs at least one task.
  Integers keep the CP-SAT model exact (CP-SAT only accepts integer data).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Task:
    id: int
    cpu: int  # CPU units required while running
    mem: int  # memory units required while running
    p: int  # processing time in slots (>= 1)
    r: int  # release time (earliest start)
    d: int  # due date (soft deadline)
    w: int = 1  # priority weight used in weighted tardiness


@dataclass(frozen=True)
class Machine:
    id: int
    cpu: int  # CPU capacity
    mem: int  # memory capacity
    price: int  # cost per slot while leased (k_m)
    fixed: int = 0  # activation cost if used at all (F_m)
    kind: str = ""


@dataclass
class Instance:
    name: str
    tasks: list[Task]
    machines: list[Machine]
    meta: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ helpers
    @property
    def n(self) -> int:
        return len(self.tasks)

    @property
    def m(self) -> int:
        return len(self.machines)

    def fits(self, task: Task, machine: Machine) -> bool:
        return task.cpu <= machine.cpu and task.mem <= machine.mem

    def eligible(self, task: Task) -> list[Machine]:
        return [mc for mc in self.machines if self.fits(task, mc)]

    def safe_horizon(self) -> int:
        """H = max r_i + sum p_i: running everything back to back always fits."""
        return max(t.r for t in self.tasks) + sum(t.p for t in self.tasks)

    def check_well_formed(self) -> None:
        ids = [t.id for t in self.tasks]
        if ids != list(range(len(ids))):
            raise ValueError("task ids must be 0..n-1 in order")
        mids = [mc.id for mc in self.machines]
        if mids != list(range(len(mids))):
            raise ValueError("machine ids must be 0..m-1 in order")
        for t in self.tasks:
            if t.p < 1 or t.r < 0 or t.cpu < 1 or t.mem < 1 or t.w < 0:
                raise ValueError(f"bad task data: {t}")
            if not self.eligible(t):
                raise ValueError(f"task {t.id} fits on no machine (infeasible instance)")

    # ---------------------------------------------------------------------- I/O
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "meta": self.meta,
            "machines": [asdict(mc) for mc in self.machines],
            "tasks": [asdict(t) for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Instance":
        inst = cls(
            name=d["name"],
            tasks=[Task(**t) for t in d["tasks"]],
            machines=[Machine(**mc) for mc in d["machines"]],
            meta=d.get("meta", {}),
        )
        inst.check_well_formed()
        return inst

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), indent=1))

    @classmethod
    def load(cls, path: str | Path) -> "Instance":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def with_durations(self, p: dict[int, int], name_suffix: str = "") -> "Instance":
        """Copy of the instance with some processing times replaced (for robustness tests)."""
        tasks = [Task(t.id, t.cpu, t.mem, p.get(t.id, t.p), t.r, t.d, t.w) for t in self.tasks]
        return Instance(self.name + name_suffix, tasks, list(self.machines), dict(self.meta))


# --------------------------------------------------------------------- generator
# (cpu, mem, price per slot, fixed activation cost). Larger VMs cost more per slot
# but less per CPU unit (economies of scale), which creates a genuine trade-off.
MACHINE_TYPES: dict[str, tuple[int, int, int, int]] = {
    "small": (4, 8, 2, 10),
    "medium": (8, 16, 3, 15),
    "large": (16, 32, 5, 20),
}


def make_machines(n_machines: int, rng: np.random.Generator) -> list[Machine]:
    """A mixed pool; machine 0 is always large so every task fits somewhere."""
    kinds = ["large"] + [str(k) for k in rng.choice(["small", "medium", "large"], size=n_machines - 1, p=[0.4, 0.4, 0.2])]
    # Sort so machine ids are grouped by type (makes plots easier to read).
    order = {"large": 0, "medium": 1, "small": 2}
    kinds.sort(key=lambda k: order[k])
    machines = []
    for mid, kind in enumerate(kinds):
        cpu, mem, price, fixed = MACHINE_TYPES[kind]
        machines.append(Machine(mid, cpu, mem, price, fixed, kind))
    return machines


def offered_load_window(tasks_cpu_p: float, tasks_mem_p: float, machines: list[Machine], rho: float) -> int:
    """Release-window length L such that (work / capacity) / L == rho.

    Work is measured in the bottleneck resource:
        W = max( sum cpu_i p_i / sum CPU_m , sum mem_i p_i / sum MEM_m )   [slots]
    """
    W = max(tasks_cpu_p / sum(mc.cpu for mc in machines), tasks_mem_p / sum(mc.mem for mc in machines))
    return max(1, int(round(W / rho)))


def generate(
    n_tasks: int = 30,
    n_machines: int = 5,
    seed: int = 0,
    rho: float = 1.0,
    tau: float = 2.0,
    name: str | None = None,
) -> Instance:
    """Seeded synthetic instance.

    rho : offered load. Releases are spread over a window L so that the bottleneck
          work per slot divided by pool capacity is ~rho. rho > 1 means the pool is
          over-subscribed during the arrival window and queueing is unavoidable.
    tau : deadline tightness, d_i = r_i + ceil(tau * p_i). Smaller is tighter.
    """
    rng = np.random.default_rng(seed)
    machines = make_machines(n_machines, rng)
    max_cpu = max(mc.cpu for mc in machines)
    max_mem = max(mc.mem for mc in machines)

    # Resource demands: skewed (lognormal), most tasks small, a few big ones.
    cpu = np.clip(np.rint(rng.lognormal(math.log(2.0), 0.7, n_tasks)), 1, max_cpu).astype(int)
    mem = np.clip(np.rint(cpu * rng.lognormal(math.log(2.0), 0.5, n_tasks)), 1, max_mem).astype(int)

    # Durations: bimodal, ~75% short tasks and ~25% long batch jobs.
    is_long = rng.random(n_tasks) < 0.25
    short = np.clip(np.rint(rng.lognormal(math.log(4.0), 0.5, n_tasks)), 1, 15)
    long_ = np.clip(np.rint(rng.lognormal(math.log(15.0), 0.4, n_tasks)), 8, 40)
    p = np.where(is_long, long_, short).astype(int)

    L = offered_load_window(float((cpu * p).sum()), float((mem * p).sum()), machines, rho)
    r = rng.integers(0, L, size=n_tasks)
    w = rng.choice([1, 2, 3], size=n_tasks, p=[0.6, 0.3, 0.1])

    tasks = [
        Task(i, int(cpu[i]), int(mem[i]), int(p[i]), int(r[i]), int(r[i] + math.ceil(tau * p[i])), int(w[i]))
        for i in range(n_tasks)
    ]
    inst = Instance(
        name or f"syn_n{n_tasks}_m{n_machines}_rho{rho}_tau{tau}_s{seed}",
        tasks,
        machines,
        {"generator": "synthetic", "n_tasks": n_tasks, "n_machines": n_machines,
         "seed": seed, "rho": rho, "tau": tau, "release_window": L},
    )
    inst.check_well_formed()
    return inst


# --------------------------------------------------------------------- schedules
@dataclass(frozen=True)
class Assignment:
    task: int
    machine: int
    start: int
    end: int


@dataclass
class Schedule:
    method: str
    assignments: list[Assignment]
    info: dict = field(default_factory=dict)  # solver status, time, bound, reported values ...

    def by_task(self) -> dict[int, Assignment]:
        return {a.task: a for a in self.assignments}

    def to_rows(self) -> list[dict]:
        return [asdict(a) for a in sorted(self.assignments, key=lambda a: (a.machine, a.start, a.task))]

    def save_csv(self, path: str | Path) -> None:
        import pandas as pd

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(self.to_rows(), columns=["task", "machine", "start", "end"]).to_csv(path, index=False)
