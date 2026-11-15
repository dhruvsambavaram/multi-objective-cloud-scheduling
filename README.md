# Multi-Objective Cloud Task Scheduling Under CPU, Memory, and Deadline Constraints

*Project topic: Cloud Computing Resource Allocation and Task Scheduling*

**Team name:** `<TEAM NAME>`
**Members:** `<Member 1>`, `<Member 2>`, `<Member 3>`

## Short description

An offline batch scheduler for a cloud platform. Given 10–100 tasks (CPU demand,
memory demand, duration, release time, soft deadline, priority) and a pool of
3–10 heterogeneous VMs (CPU/memory capacity, price per slot, activation fee),
decide **which task runs on which machine and when** so as to minimise a
normalised combination of

* **makespan** `Cmax` (completion time of the whole batch),
* **operating cost** `Σ_m F_m·y_m + k_m·E_m` (a VM is leased from 0 until its last task ends),
* **weighted tardiness** `Σ_i w_i · max(0, C_i − d_i)`,

subject to per-machine CPU and memory capacity at every time slot, release
times, and non-preemptive execution. The primary optimiser is a **CP-SAT**
model (Google OR-Tools) built on optional interval variables and cumulative
constraints. It is compared with four list-scheduling baselines (FCFS, SJF,
Greedy least-loaded, and a cost-aware Greedy-J that myopically minimises the same
objective) and with a time-indexed **MILP** (Pyomo + HiGHS) on small
instances. It is evaluated on seeded synthetic workloads and on samples of the
real **Google 2011 cluster trace**.

### Normalised objective

```
J = α · Cmax / LB  +  β · Cost / Cost_greedy  +  γ · Σ w_i T_i / Σ p_i      (α, β, γ) = (0.4, 0.3, 0.3)
```

Each term is dimensionless: makespan relative to a provable lower bound, cost
relative to the greedy schedule (1.0 = "as expensive as greedy"), and tardiness
as the fraction of total work-time that is late. CP-SAT needs integer
coefficients, so the weights are scaled by 10⁶ and rounded (`src/cpsat_model.py`).

### Scope and assumptions

* Offline and deterministic: all tasks are known up front. Time is in integer slots (1 slot = 1 min).
* No preemption, and a task never splits across machines. Durations do not depend on the machine.
* Deadlines are soft (penalised through tardiness).
* Synthetic workload knobs: offered load `ρ` (release window sized so that bottleneck work / capacity ≈ ρ)
  and deadline tightness `τ` (`d_i = r_i + ⌈τ p_i⌉`). Every experiment is seeded.
* Trace conversion assumptions A1–A6 are documented at the top of `src/trace.py`.

## Repository layout

```
main.py                    CLI: demo / solve a saved instance / run all experiments
src/
  instance.py              data model, JSON I/O, seeded generator
  baselines.py             list-scheduling engine + FCFS, SJF, Greedy least-loaded, Greedy-J (cost-aware)
  cpsat_model.py           CP-SAT model (weighted, min-cost, min-makespan, ε-constraints, warm start)
  milp_model.py            time-indexed MILP (Pyomo + HiGHS)
  metrics.py               makespan, cost, tardiness, utilisation, lower bound, normalised objective
  validate.py              independent feasibility checker (run on every schedule)
  simulate.py              robustness replay under perturbed durations
  trace.py                 Google 2011 trace part → instance
experiments/
  run_e1_methods.py ... run_e8_milp.py   one script per experiment, each writes results/*.csv
  plots.py                 results/*.csv → results/figures/*.png
  run_all.py               runs E1–E8 and the plots
tests/test_correctness.py  hand-solved / brute-force / validator / determinism checks
data/
  synthetic/*.json         generated instances (written by E1)
  trace/google2011_pool.csv  3000 usable finished tasks sampled from task_events part 0 (shipped)
  trace/google2011_s*.json   trace instances used in E7
results/                   CSVs, tables/*.md (mean ± std), figures/*.png, schedules/*.csv
```

## Libraries used

| Library | Purpose |
|---|---|
| `ortools` (CP-SAT) | primary optimiser |
| `pyomo` + `highspy` (HiGHS) | time-indexed MILP for comparison (E8) |
| `numpy`, `pandas` | data generation, metrics, result tables |
| `matplotlib` | figures |
| `pytest` (dev only) | correctness tests |

Exact versions are pinned in `requirements.txt` (and `uv.lock`).

## Setup

Requires **Python 3.12** (OR-Tools wheels can lag the newest Python release).

```bash
python3.12 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install pytest                   # only needed for the tests
```

Or, with [uv](https://docs.astral.sh/uv/): `uv sync`, then prefix the commands below with `uv run`.

All commands are run from the project root.

## How to run

```bash
# Quick demo: one 30-task instance, all five methods, validated, printed as a table
python main.py demo
python main.py demo --n 50 --m 6 --rho 1.5 --tau 1.5 --time-limit 20

# Solve a saved instance and write the CP-SAT schedule
python main.py solve data/synthetic/syn_n20_m4_rho1.0_tau2.0_s0.json --out schedule.csv

# Correctness tests (hand-solved instance, brute force, MILP = CP-SAT, validator, determinism)
python -m pytest -q

# Every experiment + every figure
python -m experiments.run_all            # full configuration, ~30 min on an 8-core laptop
python -m experiments.run_all --quick    # smoke configuration, ~3 min
```

Each experiment can also be run on its own, with `--quick`, `--time-limit S` and `--workers K` options:

| # | Command | Question | Output |
|---|---|---|---|
| E1 | `python -m experiments.run_e1_methods` | method comparison, 10 seeds × n ∈ {20, 50, 100} | `results/e1_methods.csv`, `figures/e1_methods.png` |
| E2 | `python -m experiments.run_e2_scalability` | CP-SAT solve time and gap vs n (10 → 100) | `e2_scalability.*` |
| E3 | `python -m experiments.run_e3_load` | load ρ ∈ [0.5, 1.5]: late tasks, utilisation, gain over baselines | `e3_load.*` |
| E4 | `python -m experiments.run_e4_pareto` | cost–makespan Pareto front (ε-constraint) vs weighted-sum sweep | `e4_pareto.*` |
| E5 | `python -m experiments.run_e5_anytime` | objective and gap vs time limit (1–60 s), warm vs cold start | `e5_anytime.*` |
| E6 | `python -m experiments.run_e6_robustness` | ±10–30 % duration noise: replayed plans vs greedy | `e6_robustness.*` |
| E7 | `python -m experiments.run_e7_trace` | same metrics as E1 on Google-trace samples | `e7_trace.*` |
| E8 | `python -m experiments.run_e8_milp` | MILP vs CP-SAT: same optimum, time, size vs horizon | `e8_milp.*`, `e8_milp_vs_cpsat.png` |
| – | `python -m experiments.plots` | redraw all figures from the CSVs | `results/figures/*.png` |

`results/tables/*.md` holds the mean ± std tables behind each figure.
`results/figures/usage_profile_greedy_vs_cpsat.png` shows per-machine CPU usage for one instance.

### Reproducibility notes

* Instances, baselines and the robustness draws are fully deterministic given the seed.
* CP-SAT runs with a **wall-clock** time limit and 8 parallel workers. When a solve stops at the limit
  (status FEASIBLE), the incumbent can differ slightly between machines and runs. Solves reported as
  OPTIMAL are reproducible. `tests/test_correctness.py::test_same_seed_same_results` checks this.
* E7 uses the shipped `data/trace/google2011_pool.csv`. If you delete it, the script re-downloads one 4 MB
  part of the public trace
  (`https://commondatastorage.googleapis.com/clusterdata-2011-2/task_events/part-00000-of-00500.csv.gz`).
* The MILP is solved in a separate Python process (`python -m src.milp_model`). On macOS, HiGHS and
  OR-Tools bundle conflicting native libraries, and calling HiGHS in a process that already loaded
  OR-Tools segfaults.

## Packaging the submission

```bash
./make_submission.sh <team_name>      # -> dist/<team_name>.zip
```

The zip contains the code, tests, data (including the trace pool) and results. It leaves out the
virtual environment, caches and the raw trace download.

## Correctness checks

Every schedule produced in every experiment passes `src/validate.py`, an independent per-slot checker:
each task is scheduled exactly once on a machine it fits, starts no earlier than its release, has
`end = start + p`, and stays within CPU and memory capacity in every slot. The solver's reported
makespan, cost and tardiness are also recomputed and compared. `tests/` additionally checks:

1. a 3-task hand-solved instance (optimal Cmax = 4),
2. single-machine sanity cases (serial ⇒ Cmax = Σp, unlimited capacity ⇒ Cmax = max(r+p) = LB),
3. CP-SAT = exhaustive brute force on 6 random 4-task instances,
4. MILP optimum = CP-SAT optimum on the same horizon,
5. CP-SAT is never worse than the best baseline it is warm-started from,
6. the same seed gives identical instances, baselines and optimal objectives.
