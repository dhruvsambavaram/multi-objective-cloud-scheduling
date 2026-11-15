"""Correctness checks (PLAN.md §7). Run with:  python -m pytest -q"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from src import cpsat_model as cp
from src import milp_model as mi
from src.baselines import BASELINES, Profile, greedy
from src.instance import Assignment, Instance, Machine, Schedule, Task, generate
from src.metrics import Refs, Weights, evaluate, make_refs, makespan, makespan_lb, objective
from src.simulate import perturb, replay
from src.validate import check

MAKESPAN_ONLY = Weights(1.0, 0.0, 0.0)


def tiny_hand_instance() -> Instance:
    """3 tasks, 1 machine (CPU 4). Solved by hand:

    A(cpu 2, p 3, r 0) and B(cpu 2, p 2, r 0) can run together on [0,3) / [0,2).
    C(cpu 4, p 1, r 1) needs the whole machine, so it cannot overlap A or B.
    Best: A,B at 0, C at 3  ->  Cmax = 4.   (C first at 1 gives A,B at 2 -> Cmax = 5.)
    """
    tasks = [Task(0, 2, 1, 3, 0, 10), Task(1, 2, 1, 2, 0, 10), Task(2, 4, 1, 1, 1, 10)]
    return Instance("hand", tasks, [Machine(0, 4, 8, 1, 0, "m")])


def refs_for(inst: Instance) -> Refs:
    return make_refs(inst, greedy(inst))


# --------------------------------------------------------------------- helpers
def test_earliest_fit_respects_both_resources():
    pr = Profile(Machine(0, 4, 4, 1), 10)
    pr.commit(0, 3, 1, 5)  # [0,5): cpu 3, mem 1
    pr.commit(6, 1, 4, 2)  # [6,8): cpu 1, mem 4 (memory full)
    assert pr.earliest_fit(1, 1, 3, 0) == 0  # fits next to the first task
    assert pr.earliest_fit(2, 1, 1, 0) == 5  # cpu blocked until 5
    assert pr.earliest_fit(2, 1, 2, 0) == 8  # [5,7) hits the memory-full slot 6
    assert pr.earliest_fit(1, 1, 1, 20) == 20  # beyond the profile: grows


# --------------------------------------------------------------------- 7.1 hand
def test_hand_instance_cpsat_matches_hand_solution():
    inst = tiny_hand_instance()
    s = cp.solve(inst, MAKESPAN_ONLY, refs_for(inst), cp.CpSatOptions(time_limit=5))
    assert s.info["status"] == "OPTIMAL"
    assert makespan(s) == 4
    assert not check(inst, s, s.info["reported"])


# --------------------------------------------------------------------- 7.2 single machine
def test_single_machine_serial_equals_total_work():
    # Every task needs the whole CPU, so tasks run one at a time.
    tasks = [Task(i, 4, 1, p, 0, 100) for i, p in enumerate([3, 1, 4, 1, 5])]
    inst = Instance("serial", tasks, [Machine(0, 4, 8, 1)])
    s = cp.solve(inst, MAKESPAN_ONLY, refs_for(inst))
    assert makespan(s) == sum(t.p for t in tasks)


def test_single_machine_unlimited_capacity_equals_release_bound():
    tasks = [Task(i, 1, 1, p, r, 100) for i, (p, r) in enumerate([(3, 0), (2, 4), (6, 1), (1, 7)])]
    inst = Instance("wide", tasks, [Machine(0, 100, 100, 1)])
    s = cp.solve(inst, MAKESPAN_ONLY, refs_for(inst))
    assert makespan(s) == max(t.r + t.p for t in tasks) == makespan_lb(inst)
    for b in BASELINES.values():  # every baseline is optimal here too
        assert makespan(b(inst)) == makespan_lb(inst)


# --------------------------------------------------------------------- brute force
def brute_force(inst: Instance, w: Weights, refs: Refs, H: int) -> float:
    """Enumerate every (machine, start) choice, depth-first with capacity pruning."""
    best = [float("inf")]
    use = {mc.id: (np.zeros(H, int), np.zeros(H, int)) for mc in inst.machines}
    chosen: list[Assignment] = []

    def rec(k: int):
        if k == inst.n:
            best[0] = min(best[0], objective(inst, Schedule("bf", list(chosen)), w, refs))
            return
        t = inst.tasks[k]
        for mc in inst.eligible(t):
            c, m = use[mc.id]
            for s in range(t.r, H - t.p + 1):
                if (c[s:s + t.p] + t.cpu).max() <= mc.cpu and (m[s:s + t.p] + t.mem).max() <= mc.mem:
                    c[s:s + t.p] += t.cpu
                    m[s:s + t.p] += t.mem
                    chosen.append(Assignment(t.id, mc.id, s, s + t.p))
                    rec(k + 1)
                    chosen.pop()
                    c[s:s + t.p] -= t.cpu
                    m[s:s + t.p] -= t.mem

    rec(0)
    return best[0]


def small_random(seed: int) -> Instance:
    rng = np.random.default_rng(seed)
    machines = [Machine(0, 4, 4, 3, 5, "big"), Machine(1, 2, 2, 1, 2, "small")]
    tasks = []
    for i in range(4):
        p = int(rng.integers(1, 4))
        r = int(rng.integers(0, 3))
        tasks.append(Task(i, int(rng.integers(1, 4)), int(rng.integers(1, 3)), p, r, r + p + int(rng.integers(0, 2)),
                          int(rng.integers(1, 3))))
    return Instance(f"bf{seed}", tasks, machines)


@pytest.mark.parametrize("seed", range(6))
def test_cpsat_matches_brute_force(seed):
    inst = small_random(seed)
    w = Weights()
    refs = refs_for(inst)
    H = inst.safe_horizon()
    s = cp.solve(inst, w, refs, cp.CpSatOptions(time_limit=10, horizon=H))
    assert s.info["status"] == "OPTIMAL"
    assert not check(inst, s, s.info["reported"])
    # CP-SAT optimises integer-rounded coefficients, hence the small tolerance.
    assert objective(inst, s, w, refs) == pytest.approx(brute_force(inst, w, refs, H), abs=1e-4)


# --------------------------------------------------------------------- validator
def test_validator_catches_violations():
    inst = tiny_hand_instance()
    ok = Schedule("ok", [Assignment(0, 0, 0, 3), Assignment(1, 0, 0, 2), Assignment(2, 0, 3, 4)])
    assert check(inst, ok) == []
    overlap = Schedule("x", [Assignment(0, 0, 0, 3), Assignment(1, 0, 0, 2), Assignment(2, 0, 2, 3)])
    assert any("CPU" in e for e in check(inst, overlap))
    early = Schedule("x", [Assignment(0, 0, 0, 3), Assignment(1, 0, 0, 2), Assignment(2, 0, 0, 1)])
    assert any("before release" in e for e in check(inst, early))
    missing = Schedule("x", [Assignment(0, 0, 0, 3), Assignment(1, 0, 3, 5)])
    assert any("0 times" in e for e in check(inst, missing))
    wrong_len = Schedule("x", [Assignment(0, 0, 0, 2), Assignment(1, 0, 0, 2), Assignment(2, 0, 3, 4)])
    assert any("p =" in e for e in check(inst, wrong_len))
    assert any("reported" in e for e in check(inst, ok, {"makespan": 3}))


# --------------------------------------------------------------------- 7.3 / 7.4
@pytest.mark.parametrize("seed", range(3))
def test_all_methods_valid_and_cpsat_not_worse_than_best_baseline(seed):
    inst = generate(25, 4, seed=seed, rho=1.2)
    w = Weights()
    bs = {k: f(inst) for k, f in BASELINES.items()}
    refs = make_refs(inst, bs["Greedy"])
    for s in bs.values():
        assert not check(inst, s)
    best = min(bs.values(), key=lambda s: objective(inst, s, w, refs))
    s = cp.solve(inst, w, refs, cp.CpSatOptions(time_limit=5, hint=best))
    assert not check(inst, s, s.info["reported"])
    assert objective(inst, s, w, refs) <= objective(inst, best, w, refs) + 1e-9


def test_milp_and_cpsat_agree_on_small_instance():
    inst = generate(7, 3, seed=4)
    w = Weights()
    g = greedy(inst)
    refs = make_refs(inst, g)
    H = makespan(g)  # same (tight) horizon for both models
    m = mi.solve(inst, w, refs, H, time_limit=60)
    c = cp.solve(inst, w, refs, cp.CpSatOptions(horizon=H, time_limit=30))
    assert m.info["status"] == "OPTIMAL" and c.info["status"] == "OPTIMAL"
    assert not check(inst, m) and not check(inst, c)
    assert objective(inst, m, w, refs) == pytest.approx(objective(inst, c, w, refs), abs=1e-4)


# --------------------------------------------------------------------- 7.5 determinism
def test_same_seed_same_results():
    a, b = generate(40, 5, seed=11), generate(40, 5, seed=11)
    assert a.to_dict() == b.to_dict()
    for f in BASELINES.values():
        assert f(a).assignments == f(b).assignments
    w = Weights()
    ra, rb = make_refs(a, greedy(a)), make_refs(b, greedy(b))
    sa = cp.solve(a, w, ra, cp.CpSatOptions(workers=1, time_limit=30, seed=0))
    sb = cp.solve(b, w, rb, cp.CpSatOptions(workers=1, time_limit=30, seed=0))
    if sa.info["status"] == sb.info["status"] == "OPTIMAL":
        assert objective(a, sa, w, ra) == pytest.approx(objective(b, sb, w, rb))


def test_json_roundtrip(tmp_path):
    inst = generate(10, 3, seed=1)
    inst.save(tmp_path / "i.json")
    assert Instance.load(tmp_path / "i.json").to_dict() == inst.to_dict()


# --------------------------------------------------------------------- simulator
def test_replay_is_valid_and_keeps_assignment():
    inst = generate(30, 4, seed=3)
    plan = greedy(inst)
    rng = np.random.default_rng(0)
    for delta in (0.0, 0.3):
        actual = perturb(inst, delta, rng)
        rep = replay(plan, actual)
        assert not check(actual, rep)
        assert {a.task: a.machine for a in rep.assignments} == {a.task: a.machine for a in plan.assignments}
    # delta = 0 leaves durations unchanged
    assert [t.p for t in perturb(inst, 0.0, rng).tasks] == [t.p for t in inst.tasks]


def test_evaluate_row_has_core_metrics():
    inst = generate(10, 3, seed=0)
    row = evaluate(inst, greedy(inst), Weights(), refs_for(inst))
    for k in ("makespan", "cost", "weighted_tardiness", "n_late", "util_cpu", "objective", "makespan_over_lb"):
        assert k in row
    assert row["makespan_over_lb"] >= 1.0
    assert row["objective"] > 0
