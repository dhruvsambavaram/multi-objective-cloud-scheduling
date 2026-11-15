"""Baselines: one list-scheduling engine with pluggable ordering / machine rules.

    for task in order(tasks):
        m = choose_machine(task, profiles)
        t = earliest t >= r_i such that task fits on m during [t, t + p_i)
        commit

* FCFS   : order by release time;   machine = the one with the earliest start.
* SJF    : order by processing time; machine = the one with the earliest start.
* Greedy : order by release time;   machine = least committed normalised work
           sum_i p_i (cpu_i / CPU_m + mem_i / MEM_m), ties -> earliest start.
* Greedy-J (cost-aware): order by release time; machine = the one whose earliest
           placement adds least to the normalised objective J
               dJ = alpha dCmax/LB + beta dCost/Cost_ref + gamma w_i T_i / sum p
           i.e. a myopic version of what CP-SAT optimises. FCFS/SJF/Greedy ignore
           cost; this baseline shows how much of CP-SAT's gain a cost-aware
           heuristic recovers.

Ties are broken deterministically (start, price, id) so runs are reproducible.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from .instance import Assignment, Instance, Machine, Schedule, Task


class Profile:
    """CPU and memory usage per slot on one machine."""

    def __init__(self, machine: Machine, horizon: int):
        self.machine = machine
        self.cpu = np.zeros(horizon, dtype=np.int64)
        self.mem = np.zeros(horizon, dtype=np.int64)

    def _grow(self, need: int) -> None:
        if need > len(self.cpu):
            extra = max(need - len(self.cpu), len(self.cpu))
            self.cpu = np.concatenate([self.cpu, np.zeros(extra, dtype=np.int64)])
            self.mem = np.concatenate([self.mem, np.zeros(extra, dtype=np.int64)])

    def earliest_fit(self, cpu: int, mem: int, p: int, earliest: int) -> int:
        """Smallest t >= earliest such that [t, t+p) has room for (cpu, mem).

        Uses a prefix sum over the boolean "slot has room" mask: a window of
        length p is feasible iff it contains p free slots.
        """
        if cpu > self.machine.cpu or mem > self.machine.mem:
            raise ValueError("task does not fit this machine")
        # Beyond the last used slot the machine is empty, so a fit always exists
        # within [earliest, last_used + 1]; make sure the arrays cover that window.
        self._grow(earliest + p + 1)
        ok = (self.cpu + cpu <= self.machine.cpu) & (self.mem + mem <= self.machine.mem)
        ok = np.concatenate([ok, np.ones(earliest + p, dtype=bool)])  # empty future
        cs = np.concatenate([[0], np.cumsum(ok)])
        win = cs[p:] - cs[:-p]  # win[t] = free slots in [t, t+p)
        cand = np.flatnonzero(win[earliest:] == p)
        return int(earliest + cand[0])

    def commit(self, start: int, cpu: int, mem: int, p: int) -> None:
        self._grow(start + p)
        self.cpu[start:start + p] += cpu
        self.mem[start:start + p] += mem
        assert self.cpu[start:start + p].max() <= self.machine.cpu
        assert self.mem[start:start + p].max() <= self.machine.mem


OrderRule = Callable[[Instance], list[Task]]
MachineRule = Callable[[Task, list[Machine], dict[int, Profile], dict[int, float]], tuple[Machine, int]]


def order_fcfs(inst: Instance) -> list[Task]:
    return sorted(inst.tasks, key=lambda t: (t.r, t.id))


def order_sjf(inst: Instance) -> list[Task]:
    return sorted(inst.tasks, key=lambda t: (t.p, t.r, t.id))


def pick_earliest_start(task, eligible, profiles, load):
    best = None
    for mc in eligible:
        s = profiles[mc.id].earliest_fit(task.cpu, task.mem, task.p, task.r)
        key = (s, mc.price, mc.id)
        if best is None or key < best[0]:
            best = (key, mc, s)
    return best[1], best[2]


def pick_least_loaded(task, eligible, profiles, load):
    best = None
    for mc in eligible:
        s = profiles[mc.id].earliest_fit(task.cpu, task.mem, task.p, task.r)
        key = (round(load[mc.id], 9), s, mc.price, mc.id)
        if best is None or key < best[0]:
            best = (key, mc, s)
    return best[1], best[2]


def list_schedule(inst: Instance, order: OrderRule, choose: MachineRule, name: str) -> Schedule:
    H = inst.safe_horizon() + 1
    profiles = {mc.id: Profile(mc, H) for mc in inst.machines}
    load = {mc.id: 0.0 for mc in inst.machines}
    out: list[Assignment] = []
    for task in order(inst):
        mc, s = choose(task, inst.eligible(task), profiles, load)
        profiles[mc.id].commit(s, task.cpu, task.mem, task.p)
        load[mc.id] += task.p * (task.cpu / mc.cpu + task.mem / mc.mem)
        out.append(Assignment(task.id, mc.id, s, s + task.p))
    return Schedule(name, sorted(out, key=lambda a: a.task))


def fcfs(inst: Instance) -> Schedule:
    return list_schedule(inst, order_fcfs, pick_earliest_start, "FCFS")


def sjf(inst: Instance) -> Schedule:
    return list_schedule(inst, order_sjf, pick_earliest_start, "SJF")


def greedy(inst: Instance) -> Schedule:
    return list_schedule(inst, order_fcfs, pick_least_loaded, "Greedy")


def greedy_objective(inst: Instance, w=None, refs=None) -> Schedule:
    """Greedy-J: place each task (release order) where it increases J the least."""
    from .metrics import Weights, make_refs

    w = w or Weights()
    refs = refs or make_refs(inst, greedy(inst))
    H = inst.safe_horizon() + 1
    profiles = {mc.id: Profile(mc, H) for mc in inst.machines}
    E = {mc.id: 0 for mc in inst.machines}  # current lease end per machine
    used: set[int] = set()
    cmax = 0
    out: list[Assignment] = []
    for task in order_fcfs(inst):
        best = None
        for mc in inst.eligible(task):
            s = profiles[mc.id].earliest_fit(task.cpu, task.mem, task.p, task.r)
            e = s + task.p
            d_cost = (0 if mc.id in used else mc.fixed) + mc.price * max(0, e - E[mc.id])
            d_J = (w.alpha * max(0, e - cmax) / refs.lb + w.beta * d_cost / refs.cost_ref
                   + w.gamma * task.w * max(0, e - task.d) / refs.work)
            key = (round(d_J, 12), s, mc.price, mc.id)
            if best is None or key < best[0]:
                best = (key, mc, s)
        _, mc, s = best
        profiles[mc.id].commit(s, task.cpu, task.mem, task.p)
        E[mc.id] = max(E[mc.id], s + task.p)
        used.add(mc.id)
        cmax = max(cmax, s + task.p)
        out.append(Assignment(task.id, mc.id, s, s + task.p))
    return Schedule("Greedy-J", sorted(out, key=lambda a: a.task))


BASELINES: dict[str, Callable[[Instance], Schedule]] = {"FCFS": fcfs, "SJF": sjf, "Greedy": greedy, "Greedy-J": greedy_objective}
