"""Schedule metrics, the makespan lower bound and the normalised objective.

Everything here is recomputed from the (instance, schedule) pair only, so the
numbers are identical no matter which method produced the schedule.

Cost model (PLAN.md §2.1): machine m is leased from time 0 until the last task on
it finishes (E_m) and pays a fixed activation fee F_m if it is used at all:

    Cost = sum_m ( F_m * y_m + k_m * E_m )

Normalised objective (PLAN.md §2.6), every term dimensionless:

    J = alpha * Cmax / LB  +  beta * Cost / Cost_ref  +  gamma * sum_i w_i T_i / sum_i p_i
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .instance import Instance, Schedule


@dataclass(frozen=True)
class Weights:
    """Relative importance of makespan, cost and tardiness (should sum to 1).

    Defaults (0.4, 0.3, 0.3): completion time is the headline metric of the
    project; cost and lateness matter equally and slightly less.
    """

    alpha: float = 0.4
    beta: float = 0.3
    gamma: float = 0.3


@dataclass(frozen=True)
class Refs:
    """Normalisation constants. All must be > 0."""

    lb: float  # makespan lower bound
    cost_ref: float  # cost of the reference (greedy) schedule
    work: float  # sum of processing times


def makespan_lb(inst: Instance) -> int:
    """LB = max( max_i(r_i+p_i), ceil(sum cpu_i p_i / sum CPU_m), ceil(sum mem_i p_i / sum MEM_m) )."""
    t = inst.tasks
    lb_release = max(x.r + x.p for x in t)
    lb_cpu = math.ceil(sum(x.cpu * x.p for x in t) / sum(m.cpu for m in inst.machines))
    lb_mem = math.ceil(sum(x.mem * x.p for x in t) / sum(m.mem for m in inst.machines))
    return max(lb_release, lb_cpu, lb_mem)


def make_refs(inst: Instance, reference: Schedule) -> Refs:
    return Refs(lb=float(makespan_lb(inst)), cost_ref=float(cost(inst, reference)), work=float(sum(t.p for t in inst.tasks)))


def machine_end_times(inst: Instance, sched: Schedule) -> dict[int, int]:
    E = {mc.id: 0 for mc in inst.machines}
    for a in sched.assignments:
        E[a.machine] = max(E[a.machine], a.end)
    return E


def cost(inst: Instance, sched: Schedule) -> int:
    E = machine_end_times(inst, sched)
    used = {a.machine for a in sched.assignments}
    return sum((mc.fixed if mc.id in used else 0) + mc.price * E[mc.id] for mc in inst.machines)


def makespan(sched: Schedule) -> int:
    return max((a.end for a in sched.assignments), default=0)


def tardiness(inst: Instance, sched: Schedule) -> tuple[int, int, int]:
    """(total tardiness, weighted tardiness, number of late tasks)."""
    tot = wtot = late = 0
    for a in sched.assignments:
        t = inst.tasks[a.task]
        T = max(0, a.end - t.d)
        tot += T
        wtot += t.w * T
        late += T > 0
    return tot, wtot, late


def objective(inst: Instance, sched: Schedule, w: Weights, refs: Refs) -> float:
    _, wT, _ = tardiness(inst, sched)
    return w.alpha * makespan(sched) / refs.lb + w.beta * cost(inst, sched) / refs.cost_ref + w.gamma * wT / refs.work


def utilisation(inst: Instance, sched: Schedule) -> dict[str, float]:
    """Used resource-time / capacity-time.

    * ``util_*``  : over the whole pool and the window [0, Cmax]
    * ``leased_util_*`` : over what was actually paid for, i.e. sum_m cap_m * E_m
    """
    C = makespan(sched)
    E = machine_end_times(inst, sched)
    used_cpu = sum(inst.tasks[a.task].cpu * (a.end - a.start) for a in sched.assignments)
    used_mem = sum(inst.tasks[a.task].mem * (a.end - a.start) for a in sched.assignments)
    pool_cpu = sum(m.cpu for m in inst.machines) * C
    pool_mem = sum(m.mem for m in inst.machines) * C
    leased_cpu = sum(m.cpu * E[m.id] for m in inst.machines)
    leased_mem = sum(m.mem * E[m.id] for m in inst.machines)
    return {
        "util_cpu": used_cpu / pool_cpu if pool_cpu else 0.0,
        "util_mem": used_mem / pool_mem if pool_mem else 0.0,
        "leased_util_cpu": used_cpu / leased_cpu if leased_cpu else 0.0,
        "leased_util_mem": used_mem / leased_mem if leased_mem else 0.0,
    }


def evaluate(inst: Instance, sched: Schedule, w: Weights | None = None, refs: Refs | None = None) -> dict:
    """One flat row of metrics, suitable for a pandas DataFrame."""
    C = makespan(sched)
    lb = makespan_lb(inst)
    T, wT, late = tardiness(inst, sched)
    row = {
        "instance": inst.name,
        "method": sched.method,
        "n_tasks": inst.n,
        "n_machines": inst.m,
        "makespan": C,
        "lb": lb,
        "makespan_over_lb": C / lb,
        "cost": cost(inst, sched),
        "tardiness": T,
        "weighted_tardiness": wT,
        "n_late": late,
        "machines_used": len({a.machine for a in sched.assignments}),
        **utilisation(inst, sched),
    }
    if w is not None and refs is not None:
        row["objective"] = objective(inst, sched, w, refs)
    for k in ("status", "solve_time", "gap", "bound_makespan"):
        if k in sched.info:
            row[k] = sched.info[k]
    return row


def usage_profile(inst: Instance, sched: Schedule, horizon: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Per-machine CPU and memory usage per slot, shape (m, H)."""
    H = horizon or makespan(sched)
    cpu = np.zeros((inst.m, H), dtype=np.int64)
    mem = np.zeros((inst.m, H), dtype=np.int64)
    for a in sched.assignments:
        t = inst.tasks[a.task]
        cpu[a.machine, a.start:a.end] += t.cpu
        mem[a.machine, a.start:a.end] += t.mem
    return cpu, mem
