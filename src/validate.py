"""Independent feasibility checker (PLAN.md §3.3).

Deliberately does not share code with the solvers or the baselines: it uses a
plain per-slot loop over a dictionary so a bug in a model (e.g. a wrong
cumulative constraint) cannot be hidden by the same bug in the checker.
"""

from __future__ import annotations

from collections import defaultdict

from .instance import Instance, Schedule


class InvalidSchedule(AssertionError):
    pass


def check(inst: Instance, sched: Schedule, reported: dict | None = None) -> list[str]:
    """Return a list of human-readable violations (empty list == valid).

    ``reported`` may contain any of ``makespan``, ``cost``, ``weighted_tardiness``
    as claimed by a solver; they are compared with values recomputed from scratch.
    """
    errors: list[str] = []
    seen: dict[int, int] = defaultdict(int)
    usage: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])  # (machine, slot) -> [cpu, mem]
    task_by_id = {t.id: t for t in inst.tasks}
    mach_by_id = {m.id: m for m in inst.machines}

    for a in sched.assignments:
        seen[a.task] += 1
        t = task_by_id.get(a.task)
        mc = mach_by_id.get(a.machine)
        if t is None:
            errors.append(f"unknown task {a.task}")
            continue
        if mc is None:
            errors.append(f"task {a.task}: unknown machine {a.machine}")
            continue
        if t.cpu > mc.cpu or t.mem > mc.mem:
            errors.append(f"task {t.id} does not fit machine {mc.id}")
        if a.start < t.r:
            errors.append(f"task {t.id} starts at {a.start} before release {t.r}")
        if a.end - a.start != t.p:
            errors.append(f"task {t.id}: end-start = {a.end - a.start} but p = {t.p}")
        for s in range(a.start, a.end):
            u = usage[(mc.id, s)]
            u[0] += t.cpu
            u[1] += t.mem

    for t in inst.tasks:
        if seen[t.id] != 1:
            errors.append(f"task {t.id} scheduled {seen[t.id]} times (expected exactly 1)")

    for (mid, s), (c, m) in sorted(usage.items()):
        mc = mach_by_id[mid]
        if c > mc.cpu:
            errors.append(f"machine {mid} slot {s}: CPU {c} > capacity {mc.cpu}")
        if m > mc.mem:
            errors.append(f"machine {mid} slot {s}: MEM {m} > capacity {mc.mem}")

    if reported and not errors:
        # Recompute from scratch, without importing metrics.py.
        C = max(a.end for a in sched.assignments)
        E: dict[int, int] = defaultdict(int)
        for a in sched.assignments:
            E[a.machine] = max(E[a.machine], a.end)
        cost = sum(mach_by_id[mid].fixed + mach_by_id[mid].price * e for mid, e in E.items())
        wT = sum(task_by_id[a.task].w * max(0, a.end - task_by_id[a.task].d) for a in sched.assignments)
        actual = {"makespan": C, "cost": cost, "weighted_tardiness": wT}
        for k, v in reported.items():
            if k in actual and abs(actual[k] - v) > 1e-6:
                errors.append(f"reported {k} = {v} but recomputed {actual[k]}")
    return errors


def assert_valid(inst: Instance, sched: Schedule, reported: dict | None = None) -> None:
    errs = check(inst, sched, reported)
    if errs:
        head = "\n  ".join(errs[:10])
        raise InvalidSchedule(f"{sched.method} on {inst.name}: {len(errs)} violation(s)\n  {head}")
