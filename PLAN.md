# Implementation Plan — Multi-Objective Cloud Task Scheduling

This is a build guide for the team. It specifies *what* to build and *why*, with
math and pseudocode. The code itself is for the team to write.

---

## 0. Scope (freeze this early)

- **Offline, deterministic, batch** scheduling. All tasks are known up front.
- 10–100 tasks, 3–10 machines, integer time slots (e.g., 1 slot = 1 minute).
- No preemption, and no task is split across machines.
- Extensions, only if time permits: online arrivals, rescheduling, machine-dependent speeds.

Write these assumptions down in the report. Examiners reward explicit scope.

---

## 1. Data model

**Task** `i`: `cpu_i`, `mem_i`, `p_i` (duration in slots), `r_i` (release), `d_i` (deadline), optional `w_i` (priority weight).

**Machine** `m`: `CPU_m`, `MEM_m`, `k_m` (cost per slot while leased), optional `F_m` (fixed activation cost).

Store an instance as one JSON/CSV file so every method reads the *identical* input.
Store a schedule as a table: `task_id, machine_id, start, end`.

Sanity rule: every task must fit on at least one machine (`cpu_i ≤ CPU_m` and `mem_i ≤ MEM_m` for some `m`). Otherwise the instance is infeasible by construction.

---

## 2. Mathematical formulation

### 2.1 Decide what "cost" means (important modelling choice)

If cost = Σ (busy time × price) and durations don't depend on the machine, then cost only depends on *which* machine each task uses. It has almost no interaction with makespan, so the "trade-off" is weak.

**Recommended:** a machine is *leased* from time 0 until the last task on it finishes (or use a fixed cost `F_m` if used at all):

\[
\text{Cost} = \sum_m \left( F_m\, y_m + k_m\, E_m \right)
\]

where `y_m ∈ {0,1}` means "machine used" and `E_m` is the time the last task on `m` ends. This creates a real conflict: you can use fewer or cheaper machines (lower cost) but finish later (higher makespan). That conflict gives you the Pareto experiment.

### 2.2 Time-indexed MILP (matches the proposal; use with Pyomo + HiGHS)

Variables: `x_{imt} ∈ {0,1}` (task i starts on m at t), `y_m ∈ {0,1}`, `C_i ≥ 0`, `T_i ≥ 0` (tardiness), `C_max ≥ 0`, `E_m ≥ 0`.

Let `T_i^{feas} = { t : r_i ≤ t ≤ H − p_i }` with horizon `H`.

1. **Assign once:** \( \sum_m \sum_{t \in T_i^{feas}} x_{imt} = 1 \quad \forall i \)
2. **CPU capacity:** \( \sum_i \sum_{s=t-p_i+1}^{t} cpu_i\, x_{ims} \le CPU_m\, y_m \quad \forall m, t \)
3. **Memory capacity:** same with `mem_i`, `MEM_m`.
4. **Completion:** \( C_i = \sum_m \sum_t (t + p_i)\, x_{imt} \)
5. **Tardiness:** \( T_i \ge C_i - d_i,\; T_i \ge 0 \) (soft deadlines). For hard deadlines, add \( C_i \le d_i \) instead.
6. **Makespan:** \( C_{max} \ge C_i \quad \forall i \)
7. **Machine end time:** \( E_m \ge \sum_t (t+p_i)\, x_{imt} \quad \forall i, m \)
   (this is valid because the right-hand side is 0 if i is not on m)
8. Release times are enforced by the index set \(T_i^{feas}\).

Size ≈ |tasks| × |machines| × H binaries. With 100 tasks, 10 machines and H = 300, that is about 300k binaries, which is heavy. **Discuss this in the report.** It is the reason CP-SAT is the primary solver.

### 2.3 CP-SAT formulation (primary; OR-Tools)

The same model, written with scheduling primitives:

- For each pair (i, m) where task i fits on machine m: a Boolean `a_im` (assigned) and an **optional interval** `[S_im, S_im + p_i)` that exists only when `a_im` is true.
- `ExactlyOne(a_im over m)` for each task.
- For each machine: one **cumulative** constraint on CPU (demands `cpu_i`, capacity `CPU_m`) and another on memory.
- `S_im ≥ r_i` (domain lower bound).
- A global start/end per task, linked to the chosen machine with `OnlyEnforceIf(a_im)`.
- `C_max` = max over task ends. Use the max-equality constraint.
- `T_i ≥ end_i − d_i`, `T_i ≥ 0`.
- `E_m ≥ end_im` enforced if `a_im`; `y_m ≥ a_im`.

Things to look up in the OR-Tools docs yourselves: `NewOptionalIntervalVar`, `AddCumulative`, `AddExactlyOne`, `AddMaxEquality`, `OnlyEnforceIf`, solver parameters `max_time_in_seconds` and `num_workers`, and reading `ObjectiveValue()` / `BestObjectiveBound()` for the gap.

CP-SAT only takes **integer** coefficients. Scale the normalised weights (e.g. × 1000) and round. Mention this in the report.

### 2.4 Horizon H (both models)

- Safe upper bound: \( H = \max_i r_i + \sum_i p_i \) (run everything back to back).
- Tighter and still valid with soft deadlines: makespan of the best baseline schedule. Tighter H means a much smaller model, so say so explicitly.

### 2.5 Lower bounds (for evaluating quality without proving optimality)

\[
LB_{C_{max}} = \max\Big( \max_i (r_i + p_i),\; \Big\lceil \tfrac{\sum_i cpu_i\, p_i}{\sum_m CPU_m} \Big\rceil,\; \Big\lceil \tfrac{\sum_i mem_i\, p_i}{\sum_m MEM_m} \Big\rceil \Big)
\]

Report every method's makespan as a ratio to this LB. CP-SAT also gives its own proven bound.

### 2.6 Normalising the objective (the proposal flags this; do it properly)

Turn every term into a dimensionless quantity with a natural meaning:

\[
\min\; \alpha \frac{C_{max}}{LB_{C_{max}}} + \beta \frac{\text{Cost}}{\text{Cost}_{ref}} + \gamma \frac{\sum_i w_i T_i}{\sum_i p_i}
\]

- `Cost_ref` = cost of the baseline schedule (e.g. greedy), so "1.0" means "same as greedy".
- Tardiness divided by total work = "fraction of work-time late".
- Then α, β, γ (summing to 1) really are relative importances. Justify the defaults, e.g. (0.4, 0.3, 0.3).

**For the Pareto front, don't sweep weights.** Use the **ε-constraint method**: minimise cost subject to \(C_{max} \le \varepsilon\), for ε from LB up to the baseline makespan. Weighted sums miss non-convex parts of the front; this is a good viva point.

---

## 3. Components to build

Suggested layout:

```
team_name/
  README.md
  requirements.txt
  data/            # generated instances + sampled trace
  src/
    instance.py    # dataclasses, load/save, generator
    baselines.py   # FCFS, SJF, Greedy
    cpsat_model.py # CP-SAT formulation
    milp_model.py  # Pyomo + HiGHS (optional / small instances)
    validate.py    # independent feasibility checker
    metrics.py     # makespan, cost, tardiness, utilisation, LB
    simulate.py    # replay under perturbed durations
    trace.py       # Google trace sampling → instance
  experiments/
    run_*.py       # one script per experiment, writes CSV
    plots.py       # reads CSVs, writes figures
  results/
```

### 3.1 Instance generator

Parameters: `n_tasks, n_machines, seed, load_factor ρ, deadline_tightness τ`.

- Machines: a few types (small/medium/large) with CPU, memory and price; larger machines cost more per slot.
- Tasks: `cpu_i`, `mem_i` from a skewed distribution (lognormal clipped to the largest machine). `p_i` from lognormal or bimodal (many short tasks, a few long ones, which is realistic).
- Releases: spread over a window so that offered load ≈ ρ × capacity. **ρ is your main "workload" knob.**
- Deadlines: \( d_i = r_i + \lceil \tau \cdot p_i \rceil \) with τ ∈ [1.2, 3]. Smaller τ means tighter deadlines.
- **Always seed.** Every experiment must be reproducible.

### 3.2 Baselines: one list-scheduling engine with pluggable rules

All three baselines are "list scheduling": **order** the tasks, then **place** each one.

```
schedule = empty profile per machine (CPU and memory usage over time)
for task in order(tasks):                 # FCFS: by r_i; SJF: by p_i
    m = choose_machine(task, profiles)    # rule-dependent
    t = earliest t ≥ r_i such that task fits on m during [t, t+p_i)
    commit task to m at t
```

- **FCFS**: order by release time (tie-break by id). Machine = the one giving the earliest start.
- **SJF**: order by duration (ties by release). Same placement.
- **Greedy least-loaded**: order by release time. Machine = the one with the smallest committed work, measured as normalised CPU·time plus normalised memory·time. Start at the earliest feasible time on it.

Note: "earliest feasible t" requires checking both resources over the whole interval. Write this helper once and test it well, because all baselines depend on it.

### 3.3 Validator (do not skip; examiners like it)

Independent from the models. Given an instance and a schedule:

- every task is scheduled exactly once, on a machine it fits on;
- `start ≥ r_i`, `end = start + p_i`;
- for every machine and every slot: Σ CPU ≤ cap and Σ memory ≤ cap;
- recompute makespan, cost and tardiness from scratch and compare with what the solver reported.

Run it on **every** schedule produced in every experiment. It catches modelling bugs (e.g. a wrong cumulative constraint) that would otherwise silently corrupt results.

### 3.4 Metrics

Makespan, cost, total/weighted tardiness, number of late tasks, average CPU and memory utilisation (used resource·time ÷ capacity·time over [0, C_max]), solve time, and the ratio to LB. For CP-SAT, also the optimality gap: `(obj − bound) / obj`.

### 3.5 Robustness simulator (proposal's "Question 3")

Planned start times become meaningless if durations change. So replay the **policy**, not the timestamps:

- Keep each task's machine and the *order* of tasks on each machine from the plan.
- Draw actual durations \( \tilde p_i = \text{round}(p_i (1+\epsilon_i)) \), with \( \epsilon_i \sim U[-\delta, \delta] \) and δ ∈ {0.1, 0.2, 0.3}.
- Start each task as early as possible, respecting release, the planned order and resource availability.
- Repeat about 30 times per δ, and report the mean and spread of makespan and tardiness.

Compare with re-running the greedy policy on the actual durations. The key question is whether the optimised plan keeps its advantage once durations become noisy.

### 3.6 Real-trace validation (small)

- Easiest option: the **2011 Google cluster trace**. Its tables are split into many small gzipped CSV parts, so you can download one or two `task_events` parts rather than the whole trace.
- From `task_events`: CPU and memory *requests* (already normalised to 0–1 of the largest machine) and runtime ≈ FINISH − SCHEDULE timestamp.
- Sample 50–100 finished tasks, rescale times into slots, and assign synthetic deadlines with τ.
- List every conversion assumption in the report. The proposal already anticipates this.

---

## 4. Experiments (each one is a script that writes a CSV, then a plot)

| # | Experiment | Vary | Report |
|---|-----------|------|--------|
| E1 | Method comparison | method, on ~10 seeds per size | makespan/LB, cost, tardiness (mean ± std) |
| E2 | Scalability | n_tasks 10→100 | solve time, gap at a fixed time limit |
| E3 | Load sensitivity | ρ from 0.5 to 1.5 | late tasks, utilisation, each method's makespan relative to CP-SAT |
| E4 | Pareto front | ε-constraint on C_max | cost vs. makespan curve, with baselines as points |
| E5 | Anytime behaviour | time limit 1, 5, 10, 30, 60 s | objective and gap vs. time |
| E6 | Robustness | δ ∈ {0, 0.1, 0.2, 0.3} | degradation of the optimised plan vs. greedy |
| E7 | Real-trace sample | — | same metrics as E1 |
| E8 (optional) | MILP vs CP-SAT | small instances only | same optimum? time? model size? |

Always use the **same instances** for all methods (same seed and same file), and validate every output.

---

## 5. Expected insights to test, not assume (for the discussion section)

- At low ρ, greedy ≈ CP-SAT. The optimiser's gain should grow with load, then flatten or become noisy when the instance gets too large to solve within the time limit.
- When deadlines are tight (small τ), some tardiness is unavoidable. Compare against the LB to show this.
- Lowering cost usually raises makespan (fewer or cheaper machines). The Pareto plot shows how much makespan one unit of cost buys.
- A tightly packed optimal plan may be *more* fragile under duration noise. Check whether your E6 data supports this.
- Time-indexed MILP grows with H, while CP-SAT grows with the number of (task, machine) pairs. This explains the solver choice.

---

## 6. Timeline and split (submission window 28 Nov – 4 Dec)

| Dates | Milestone |
|------|-----------|
| by 23 Nov | Proposal submitted; data model and generator done; formulation frozen |
| 23–25 Nov | Baselines + validator + metrics (validator tests on hand-made tiny instances) |
| 24–27 Nov | CP-SAT model; check against brute force on 5–6 task instances |
| 27–29 Nov | Experiments E1–E6, plots |
| 29 Nov–1 Dec | Trace sample (E7), optional MILP (E8), report draft |
| before demo | README, zip as `team_name.zip`, fresh-machine install test, viva rehearsal |

Suggested split for 3 members: (A) generator + trace + simulator, (B) baselines + validator + metrics, (C) CP-SAT/MILP models + experiments. Everyone should be able to explain the formulation in §2.

---

## 7. Correctness checks before trusting any result

1. Tiny instance (3 tasks, 1 machine) solved by hand: does the model match?
2. With a single machine and unlimited capacity, the makespan should equal \( \max_i r_i + \) the remaining work; check you get exactly that.
3. CP-SAT objective is never worse than the best baseline when given that baseline as a hint/horizon.
4. Validator passes for every schedule.
5. The same seed gives identical results on two runs.

---

## 8. README checklist (from guidelines)

Team name, member names, project title, short description, libraries used (e.g. `ortools`, `numpy`, `pandas`, `matplotlib`, optionally `pyomo`, `highspy`), setup instructions (`python -m venv`, `pip install -r requirements.txt`), and the exact commands to reproduce each experiment and figure.

Note: OR-Tools wheels may lag behind the newest Python release. If `pip install ortools` fails on Python 3.14, create the virtual environment with Python 3.12.

---

## 9. Likely viva questions

- Why CP-SAT over MILP for this structure? (§2.2 size argument, cumulative constraints)
- How did you choose α, β, γ, and why normalise? (§2.6)
- Why ε-constraint instead of weight sweeps for the Pareto front?
- Is your schedule optimal? (gap, bound, LB)
- What happens if durations are wrong? (E6)
- When is the optimiser *not* worth it? (E3 at low load, E2 solve time)
