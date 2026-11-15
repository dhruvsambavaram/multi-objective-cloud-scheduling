"""Robustness simulator (PLAN.md §3.5 / proposal Question 3).

Planned start times stop meaning anything once durations change, so we replay
the plan as a *policy*:

* each task keeps its planned machine and its planned position in that
  machine's start order;
* actual durations are p~_i = max(1, round(p_i (1 + eps_i))), eps_i ~ U[-delta, delta];
* a discrete-time event loop starts every task as early as possible subject to
  release time, "not before the previous task in the machine's order has
  started", and CPU/memory availability given the *actual* durations.
"""

from __future__ import annotations

import numpy as np

from .baselines import Profile
from .instance import Assignment, Instance, Schedule


def perturb(inst: Instance, delta: float, rng: np.random.Generator) -> Instance:
    eps = rng.uniform(-delta, delta, size=inst.n)
    p = {t.id: max(1, int(round(t.p * (1 + e)))) for t, e in zip(inst.tasks, eps)}
    return inst.with_durations(p, f"_d{delta}")


def replay(plan: Schedule, actual: Instance, name: str | None = None) -> Schedule:
    """Execute ``plan``'s machine assignment and per-machine order on ``actual`` durations."""
    H = actual.safe_horizon() + 1
    profiles = {mc.id: Profile(mc, H) for mc in actual.machines}
    queues: dict[int, list[Assignment]] = {mc.id: [] for mc in actual.machines}
    for a in sorted(plan.assignments, key=lambda a: (a.start, a.task)):
        queues[a.machine].append(a)

    # Machines are independent once the assignment is fixed, so each queue is
    # simulated on its own.
    out = []
    for mid, q in queues.items():
        prev_start = 0
        for a in q:
            t = actual.tasks[a.task]
            s = profiles[mid].earliest_fit(t.cpu, t.mem, t.p, max(t.r, prev_start))
            profiles[mid].commit(s, t.cpu, t.mem, t.p)
            prev_start = s
            out.append(Assignment(t.id, mid, s, s + t.p))
    return Schedule(name or f"{plan.method} (replayed)", sorted(out, key=lambda a: a.task))
