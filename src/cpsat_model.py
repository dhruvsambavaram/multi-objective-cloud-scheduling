"""CP-SAT formulation (PLAN.md §2.3), the primary optimiser.

Variables
---------
  S_i  in [r_i, H - p_i]        start of task i (shared by all its optional intervals)
  a_im in {0,1}                 task i runs on machine m   (only for pairs where i fits m)
  I_im = optional interval [S_i, S_i + p_i) present iff a_im
  y_m  in {0,1}                 machine m used             (y_m = max_i a_im)
  E_m  in [0, H]                lease end of machine m     (E_m = max_i a_im * end_i)
  T_i  >= 0                     tardiness                  (T_i = max(0, end_i - d_i))
  Cmax                          makespan                   (Cmax = max_i end_i)

Constraints
-----------
  ExactlyOne_m a_im                                  every task runs once
  Cumulative(I_im, cpu_i, CPU_m), Cumulative(I_im, mem_i, MEM_m)   per machine
  release times are encoded in the domain of S_i

The max-equalities make the reported E_m / T_i / Cmax exact (not just bounds), so
the validator can check the solver's numbers against values recomputed from the
schedule. CP-SAT accepts integer coefficients only, so the normalised objective
weights are multiplied by SCALE and rounded.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .instance import Assignment, Instance, Schedule
from .metrics import Refs, Weights

SCALE = 1_000_000


@dataclass
class CpSatOptions:
    time_limit: float = 10.0
    workers: int = 8
    seed: int = 0
    objective: str = "weighted"  # "weighted" | "cost" | "makespan"
    makespan_cap: int | None = None  # epsilon-constraint: Cmax <= cap
    cost_cap: int | None = None  # epsilon-constraint the other way round
    horizon: int | None = None  # default: safe horizon (or makespan_cap)
    hint: Schedule | None = None  # warm start (e.g. best baseline)
    log: bool = False


def objective_coefficients(w: Weights, refs: Refs) -> tuple[int, int, int]:
    """Integer coefficients for (Cmax, Cost, weighted tardiness)."""
    return (
        int(round(SCALE * w.alpha / refs.lb)),
        int(round(SCALE * w.beta / refs.cost_ref)),
        int(round(SCALE * w.gamma / refs.work)),
    )


def build(inst: Instance, w: Weights, refs: Refs, opt: CpSatOptions):
    H = opt.horizon or inst.safe_horizon()
    if opt.makespan_cap is not None:
        H = min(H, opt.makespan_cap)
    md = cp_model.CpModel()

    S, end, T = {}, {}, {}
    a: dict[tuple[int, int], cp_model.IntVar] = {}
    per_machine: dict[int, list[tuple[int, cp_model.IntervalVar]]] = {mc.id: [] for mc in inst.machines}

    for t in inst.tasks:
        if t.r + t.p > H:
            raise ValueError(f"horizon {H} too short for task {t.id}")
        S[t.id] = md.NewIntVar(t.r, H - t.p, f"S{t.id}")
        end[t.id] = S[t.id] + t.p
        lits = []
        for mc in inst.eligible(t):
            lit = md.NewBoolVar(f"a{t.id}_{mc.id}")
            a[t.id, mc.id] = lit
            lits.append(lit)
            iv = md.NewOptionalFixedSizeIntervalVar(S[t.id], t.p, lit, f"I{t.id}_{mc.id}")
            per_machine[mc.id].append((t.id, iv))
        md.AddExactlyOne(lits)
        T[t.id] = md.NewIntVar(0, max(0, H - t.d), f"T{t.id}")
        md.AddMaxEquality(T[t.id], [end[t.id] - t.d, 0])

    y, E = {}, {}
    for mc in inst.machines:
        items = per_machine[mc.id]
        y[mc.id] = md.NewBoolVar(f"y{mc.id}")
        E[mc.id] = md.NewIntVar(0, H, f"E{mc.id}")
        if not items:
            md.Add(y[mc.id] == 0)
            md.Add(E[mc.id] == 0)
            continue
        ivs = [iv for _, iv in items]
        md.AddCumulative(ivs, [inst.tasks[i].cpu for i, _ in items], mc.cpu)
        md.AddCumulative(ivs, [inst.tasks[i].mem for i, _ in items], mc.mem)
        md.AddMaxEquality(y[mc.id], [a[i, mc.id] for i, _ in items])
        # e_im = end_i if a_im else 0;  E_m = max_i e_im
        e_terms = []
        for i, _ in items:
            e = md.NewIntVar(0, H, f"e{i}_{mc.id}")
            md.Add(e == end[i]).OnlyEnforceIf(a[i, mc.id])
            md.Add(e == 0).OnlyEnforceIf(a[i, mc.id].Not())
            e_terms.append(e)
        md.AddMaxEquality(E[mc.id], e_terms)

    Cmax = md.NewIntVar(0, H, "Cmax")
    md.AddMaxEquality(Cmax, [end[t.id] for t in inst.tasks])
    cost = sum(mc.fixed * y[mc.id] + mc.price * E[mc.id] for mc in inst.machines)
    wT = sum(t.w * T[t.id] for t in inst.tasks)

    if opt.makespan_cap is not None:
        md.Add(Cmax <= opt.makespan_cap)
    if opt.cost_cap is not None:
        md.Add(cost <= opt.cost_cap)

    cost_ub = sum(mc.fixed + mc.price * H for mc in inst.machines)
    if opt.objective == "weighted":
        cc, ck, ct = objective_coefficients(w, refs)
        md.Minimize(cc * Cmax + ck * cost + ct * wT)
    elif opt.objective == "cost":  # lexicographic: cost, then makespan
        md.Minimize(cost * (H + 1) + Cmax)
    elif opt.objective == "makespan":  # lexicographic: makespan, then cost
        md.Minimize(Cmax * (cost_ub + 1) + cost)
    else:
        raise ValueError(opt.objective)

    if opt.hint is not None:
        _add_hint(md, inst, opt.hint, S, a, y, E, T, Cmax, H)

    return md, {"S": S, "a": a, "y": y, "E": E, "T": T, "Cmax": Cmax, "cost": cost, "wT": wT, "H": H}


def _add_hint(md, inst, hint: Schedule, S, a, y, E, T, Cmax, H) -> None:
    by = hint.by_task()
    if max(x.end for x in hint.assignments) > H:
        return  # hint violates the horizon/epsilon cap: useless
    used = {x.machine for x in hint.assignments}
    for t in inst.tasks:
        h = by[t.id]
        md.AddHint(S[t.id], h.start)
        for (i, m), lit in a.items():
            if i == t.id:
                md.AddHint(lit, int(m == h.machine))
        md.AddHint(T[t.id], max(0, h.end - t.d))
    for mc in inst.machines:
        md.AddHint(y[mc.id], int(mc.id in used))
        md.AddHint(E[mc.id], max([x.end for x in hint.assignments if x.machine == mc.id], default=0))
    md.AddHint(Cmax, max(x.end for x in hint.assignments))


STATUS = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE", cp_model.INFEASIBLE: "INFEASIBLE",
          cp_model.MODEL_INVALID: "MODEL_INVALID", cp_model.UNKNOWN: "UNKNOWN"}


def solve(inst: Instance, w: Weights, refs: Refs, opt: CpSatOptions | None = None, name: str = "CP-SAT") -> Schedule | None:
    """Solve and return a Schedule (None if no feasible solution was found)."""
    opt = opt or CpSatOptions()
    t0 = time.perf_counter()
    md, v = build(inst, w, refs, opt)
    build_time = time.perf_counter() - t0

    solver = cp_model.CpSolver()
    p = solver.parameters
    p.max_time_in_seconds = opt.time_limit
    p.num_workers = opt.workers
    p.random_seed = opt.seed
    p.log_search_progress = opt.log
    status = solver.Solve(md)
    st = STATUS.get(status, str(status))
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    out = []
    for t in inst.tasks:
        s = solver.Value(v["S"][t.id])
        m = next(m for (i, m), lit in v["a"].items() if i == t.id and solver.Value(lit))
        out.append(Assignment(t.id, m, s, s + t.p))

    obj, bound = solver.ObjectiveValue(), solver.BestObjectiveBound()
    info = {
        "status": st,
        "solve_time": solver.WallTime(),
        "build_time": build_time,
        "objective_raw": obj,
        "bound_raw": bound,
        "gap": (obj - bound) / obj if obj > 0 else 0.0,
        "horizon": v["H"],
        "n_bool_assign": len(v["a"]),
        "reported": {
            "makespan": solver.Value(v["Cmax"]),
            "cost": solver.Value(v["cost"]),
            "weighted_tardiness": solver.Value(v["wT"]),
        },
    }
    if opt.objective == "makespan":
        cost_ub = sum(mc.fixed + mc.price * v["H"] for mc in inst.machines)
        info["bound_makespan"] = int(bound // (cost_ub + 1))
    return Schedule(name, out, info)
