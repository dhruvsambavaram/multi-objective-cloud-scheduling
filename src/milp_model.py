"""Time-indexed MILP (PLAN.md §2.2), Pyomo + HiGHS. Small instances only.

    x[i,m,t] = 1  iff task i starts on machine m at slot t,   t in [r_i, H - p_i]

    (1) sum_{m,t} x[i,m,t] = 1                                         for all i
    (2) sum_i sum_{s=t-p_i+1..t} cpu_i x[i,m,s] <= CPU_m y_m             for all m,t
    (3) same for memory
    (4) C_i = sum_{m,t} (t + p_i) x[i,m,t]
    (5) T_i >= C_i - d_i,  T_i >= 0
    (6) Cmax >= C_i
    (7) E_m >= sum_t (t + p_i) x[i,m,t]                                for all i,m

The number of binaries is ~ sum_i |eligible(i)| * (H - r_i - p_i + 1), i.e. it
grows linearly with the horizon H, which is why CP-SAT (interval variables, size
independent of H) is the primary solver.
"""

from __future__ import annotations

import time

import pyomo.environ as pyo
from pyomo.contrib.appsi.solvers import Highs

from .instance import Assignment, Instance, Schedule
from .metrics import Refs, Weights


def build(inst: Instance, w: Weights, refs: Refs, H: int) -> pyo.ConcreteModel:
    md = pyo.ConcreteModel()
    tasks = {t.id: t for t in inst.tasks}
    machs = {m.id: m for m in inst.machines}
    idx = [(t.id, m.id, s) for t in inst.tasks for m in inst.eligible(t) for s in range(t.r, H - t.p + 1)]
    md.X = pyo.Set(initialize=idx, dimen=3)
    md.I = pyo.Set(initialize=list(tasks))
    md.M = pyo.Set(initialize=list(machs))
    md.Tm = pyo.RangeSet(0, H - 1)

    md.x = pyo.Var(md.X, domain=pyo.Binary)
    md.y = pyo.Var(md.M, domain=pyo.Binary)
    md.C = pyo.Var(md.I, domain=pyo.NonNegativeReals)
    md.T = pyo.Var(md.I, domain=pyo.NonNegativeReals)
    md.E = pyo.Var(md.M, domain=pyo.NonNegativeReals, bounds=(0, H))
    md.Cmax = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0, H))

    by_i: dict[int, list] = {i: [] for i in tasks}
    by_im: dict[tuple[int, int], list] = {}
    for k in idx:
        by_i[k[0]].append(k)
        by_im.setdefault((k[0], k[1]), []).append(k)

    md.assign = pyo.Constraint(md.I, rule=lambda md, i: sum(md.x[k] for k in by_i[i]) == 1)

    # Running set for (m, t): starts s with s <= t <= s + p_i - 1.
    def running(m, t):
        return [(i, m, s) for (i, mm), ks in by_im.items() if mm == m
                for s in range(max(tasks[i].r, t - tasks[i].p + 1), t + 1) if (i, m, s) in md.X]

    run_cache = {(m, t): running(m, t) for m in machs for t in range(H)}

    def cap_rule(attr):
        def rule(md, m, t):
            ks = run_cache[m, t]
            if not ks:
                return pyo.Constraint.Skip
            return sum(getattr(tasks[k[0]], attr) * md.x[k] for k in ks) <= getattr(machs[m], attr) * md.y[m]
        return rule

    md.cap_cpu = pyo.Constraint(md.M, md.Tm, rule=cap_rule("cpu"))
    md.cap_mem = pyo.Constraint(md.M, md.Tm, rule=cap_rule("mem"))
    md.compl = pyo.Constraint(md.I, rule=lambda md, i: md.C[i] == sum((k[2] + tasks[i].p) * md.x[k] for k in by_i[i]))
    md.tard = pyo.Constraint(md.I, rule=lambda md, i: md.T[i] >= md.C[i] - tasks[i].d)
    md.mksp = pyo.Constraint(md.I, rule=lambda md, i: md.Cmax >= md.C[i])
    md.mend = pyo.Constraint(list(by_im), rule=lambda md, i, m: md.E[m] >= sum((k[2] + tasks[i].p) * md.x[k] for k in by_im[i, m]))
    # y_m >= x is implied by the capacity rows; adding it explicitly tightens the LP.
    md.use = pyo.Constraint(md.X, rule=lambda md, i, m, s: md.x[i, m, s] <= md.y[m])

    cost = sum(machs[m].fixed * md.y[m] + machs[m].price * md.E[m] for m in machs)
    wT = sum(tasks[i].w * md.T[i] for i in tasks)
    md.cost_expr = pyo.Expression(expr=cost)
    md.obj = pyo.Objective(expr=w.alpha * md.Cmax / refs.lb + w.beta * cost / refs.cost_ref + w.gamma * wT / refs.work)
    return md


def solve(inst: Instance, w: Weights, refs: Refs, H: int, time_limit: float = 60.0, name: str = "MILP",
          isolate: bool = True) -> Schedule | None:
    """Build and solve the MILP.

    ``isolate=True`` runs the solve in a freshly spawned process. HiGHS (highspy)
    and OR-Tools ship incompatible native libraries, and calling HiGHS in a
    process that has already loaded OR-Tools segfaults on some platforms.
    """
    if isolate:
        return _solve_in_subprocess(inst, w, refs, H, time_limit, name)
    t0 = time.perf_counter()
    md = build(inst, w, refs, H)
    build_time = time.perf_counter() - t0
    opt = Highs()
    opt.config.time_limit = time_limit
    opt.config.stream_solver = False
    opt.config.load_solution = False
    t1 = time.perf_counter()
    res = opt.solve(md)
    solve_time = time.perf_counter() - t1
    tc = str(res.termination_condition)
    if res.best_feasible_objective is None:
        return None
    res.solution_loader.load_vars()

    out = []
    for (i, m, s) in md.X:
        if pyo.value(md.x[i, m, s]) > 0.5:
            out.append(Assignment(i, m, s, s + inst.tasks[i].p))
    obj, bound = res.best_feasible_objective, res.best_objective_bound
    optimal = "optimal" in tc.lower()
    info = {
        "status": "OPTIMAL" if optimal else "FEASIBLE",
        "solve_time": solve_time,
        "build_time": build_time,
        "objective_raw": obj,
        "bound_raw": bound,
        "gap": (obj - bound) / obj if obj else 0.0,
        "horizon": H,
        "n_binaries": len(md.X) + len(md.M),
        "n_constraints": sum(len(c) for c in md.component_objects(pyo.Constraint, active=True)),
    }
    if optimal:
        # At an optimum E_m and T_i are pushed down to their exact values.
        info["reported"] = {"makespan": round(pyo.value(md.Cmax))}
    return Schedule(name, sorted(out, key=lambda a: a.task), info)


def _solve_in_subprocess(inst, w, refs, H, time_limit, name):
    """Run ``solve(..., isolate=False)`` in ``python -m src.milp_model`` (no OR-Tools loaded there)."""
    import pickle
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.pkl", Path(tmp) / "out.pkl"
        src.write_bytes(pickle.dumps((inst, w, refs, H, time_limit, name)))
        subprocess.run([sys.executable, "-m", "src.milp_model", str(src), str(dst)], cwd=root, check=True)
        return pickle.loads(dst.read_bytes())


if __name__ == "__main__":
    import pickle
    import sys
    from pathlib import Path

    args = pickle.loads(Path(sys.argv[1]).read_bytes())
    Path(sys.argv[2]).write_bytes(pickle.dumps(solve(*args, isolate=False)))
