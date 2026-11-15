# Team Study Guide: Multi-Objective Cloud Task Scheduling

*Project topic: Cloud Computing Resource Allocation and Task Scheduling*

Read this guide to understand the project end to end and to prepare for the demo and viva. Each
section answers one question: what we built, why, where it lives in the code, and what the
results mean. Code references are `file:line`.

**Suggested reading order:** §1–3 (everyone) → §4–6 (the core; everyone must be able to explain
these; start with the plain-English parts 4.1.0, 4.2.0, 4.3.0, the 4.5 worked solution and 5.2) → §7–8 (code map and walkthrough) → §9 (experiments) → §10 (numbers to memorise) → §11
(viva Q&A) → §12 (weak spots to own).

---

## 1. The project in 60 seconds

> A cloud provider has a batch of jobs and a small pool of virtual machines of different sizes and
> prices. We decide which job runs on which machine and when. The goals are to finish quickly, spend
> little, and meet deadlines, without ever exceeding a machine's CPU or memory. These goals conflict:
> packing jobs onto fewer machines saves money but delays completion. We wrote the problem as an
> optimisation model with a normalised objective. We solved it exactly with Google OR-Tools CP-SAT,
> compared it with four scheduling rules and a textbook MILP, and tested it on synthetic workloads and
> on real Google cluster data. CP-SAT is 12–16 % better overall, mostly by being 35–48 % cheaper while
> keeping completion time at its lower bound. We also mapped the full cost-vs-speed trade-off and
> showed that the optimised plan stays ahead even when job durations are 30 % wrong.

Three sentences to remember:

1. **What:** assign + time tasks on VMs under CPU, memory and release-time constraints; minimise makespan, cost and lateness.
2. **How:** CP-SAT with optional intervals + cumulative constraints, a normalised objective, the ε-constraint method for the trade-off, and a validator on every schedule.
3. **So what:** the optimiser wins mainly on cost; rules are close on makespan; the advantage shrinks but survives under duration noise.

---

## 2. The problem and our scope

### 2.1 Inputs

| Thing | Fields | In code |
|---|---|---|
| **Task** *i* | `cpu`, `mem` (units needed while running), `p` (duration, slots), `r` (release, earliest start), `d` (deadline), `w` (priority weight 1–3) | `src/instance.py:24` |
| **Machine** *m* | `cpu`, `mem` (capacity), `price` (cost per slot while leased, *k*), `fixed` (activation fee, *F*), `kind` | `src/instance.py:35` |
| **Instance** | list of tasks + list of machines + metadata | `src/instance.py:45` |

Three VM types (`src/instance.py:120`):

| Type | CPU | MEM | price/slot | fixed fee | price per CPU unit |
|---|---|---|---|---|---|
| small | 4 | 8 | 2 | 10 | 0.50 |
| medium | 8 | 16 | 3 | 15 | 0.375 |
| large | 16 | 32 | 5 | 20 | 0.31 |

Large VMs are more expensive per slot but cheaper per CPU unit (economies of scale). That makes
"one big machine vs several small ones" a real decision.

### 2.2 Output

A **schedule**: one row per task, `task, machine, start, end` (`src/instance.py:201`, `:209`).

### 2.3 Scope decisions (say these explicitly in the viva)

* **Offline and deterministic:** all tasks are known in advance, and durations are known exactly in the plan.
* **Discrete time:** integer slots, 1 slot = 1 minute.
* **No preemption:** a task runs start to finish on one machine and is never split.
* **Durations do not depend on the machine.**
* **Soft deadlines:** lateness is penalised, not forbidden.
* Size: 10–100 tasks, 3–10 machines.
* **Out of scope:** online arrivals, rescheduling, autoscaling. The proposal flagged overscoping as the main risk.

Why offline? It is the standard first model, it can be solved exactly, and it gives a clean
benchmark. We then test the main real-world weakness of that assumption (wrong durations) in E6.

### 2.4 Notation: every symbol used in this guide

Read `x_y` as "x with subscript y". For example, `p_i` is "the duration of task i". `REPORT.md` uses
the same symbols, with the few aliases listed in the last column.

**Indices and sets**

| Symbol | Meaning | In code | Alias in REPORT.md |
|---|---|---|---|
| i | a task (indexed 0, 1, 2, …). In the worked example the tasks are A, B, C | `Task.id` | |
| m | a machine (VM): M0, M1, … | `Machine.id` | |
| t, s | a time slot (minute). s is used for "a start slot" inside sums | slot index | |
| I, M | the set of all tasks, the set of all machines | `inst.tasks`, `inst.machines` | |
| M_i | machines that task i fits on (enough CPU and memory) | `inst.eligible(task)` | |

**Task data (inputs)**

| Symbol | Meaning | Unit | In code | Alias |
|---|---|---|---|---|
| cpu_i | CPU the task needs while it runs | CPU units | `Task.cpu` | c_i |
| mem_i | memory the task needs while it runs | MEM units | `Task.mem` | q_i |
| p_i | duration (processing time) | slots | `Task.p` | |
| r_i | release time: earliest allowed start | slot | `Task.r` | |
| d_i | deadline (soft): d_i = r_i + ⌈τ · p_i⌉ | slot | `Task.d` | |
| w_i | priority weight (1, 2 or 3) that multiplies its lateness | – | `Task.w` | |

**Machine data (inputs)**

| Symbol | Meaning | Unit | In code | Alias |
|---|---|---|---|---|
| CPU_m | CPU capacity of machine m | CPU units | `Machine.cpu` | C_m |
| MEM_m | memory capacity of machine m | MEM units | `Machine.mem` | Q_m |
| k_m | price per slot while machine m is leased | cost / slot | `Machine.price` | |
| F_m | one-off activation fee if machine m is used at all | cost | `Machine.fixed` | |

**Time horizon**

| Symbol | Meaning | In code |
|---|---|---|
| H | horizon: the last slot by which every task must have finished | `CpSatOptions.horizon`, `milp_model.solve(H=…)` |
| safe H | max_i r_i + Σ_i p_i: always big enough (everything back to back) | `Instance.safe_horizon()` |

**Decision variables: what the solver chooses**

| Symbol | Model | Type | Meaning | In code |
|---|---|---|---|---|
| x[i,m,t] | MILP | 0/1 | 1 if task i **starts** on machine m at slot t (written x_imt in the proposal) | `md.x` |
| y_m | both | 0/1 | 1 if machine m is used by at least one task | `md.y` / `y[m]` |
| S_i | CP-SAT | integer | start slot of task i (S_C = start of task C, etc.) | `S[i]` |
| a_im, a[i,m] | CP-SAT | 0/1 | 1 if task i runs on machine m. Switches its optional interval on | `a[i, m]` |
| interval [S_i, S_i + p_i) | CP-SAT | interval | the block occupied by task i on machine m, present only if a_im = 1 | `NewOptionalFixedSizeIntervalVar` |

**Derived quantities: computed from the decisions**

| Symbol | Meaning | Formula | In code |
|---|---|---|---|
| end_i, C_i | completion (end) time of task i | S_i + p_i | `end[i]`, `md.C` |
| T_i | tardiness (lateness) of task i | max(0, C_i − d_i) | `T[i]`, `md.T` |
| Cmax | makespan: when the last task finishes | max_i C_i | `Cmax`, `metrics.makespan` |
| E_m | lease end of machine m: when its last task finishes (0 if unused) | max over tasks on m of C_i | `E[m]`, `metrics.machine_end_times` |
| e_im | helper for E_m in CP-SAT: end_i if task i is on m, else 0 | | `e` in `build()` |
| Cost | total operating cost | Σ_m (F_m · y_m + k_m · E_m) | `metrics.cost` |
| Σ w_i T_i | weighted tardiness: total lateness, weighted by priority | Σ_i w_i · T_i | `metrics.tardiness` |

**Objective and normalisation**

| Symbol | Meaning | Value / formula | In code |
|---|---|---|---|
| J | the normalised objective we minimise | α·Cmax/LB + β·Cost/Cost_ref + γ·Σ w_i T_i / Σ p_i | `metrics.objective` |
| α, β, γ | weights on makespan, cost and tardiness | 0.4, 0.3, 0.3 | `Weights.alpha/beta/gamma` |
| LB | lower bound on makespan (nothing can finish sooner) | max(max_i(r_i + p_i), ⌈Σ cpu_i·p_i / Σ CPU_m⌉, ⌈Σ mem_i·p_i / Σ MEM_m⌉) | `metrics.makespan_lb`, `Refs.lb` |
| Cost_ref, Cost_greedy | cost of the Greedy schedule, used to normalise cost (same thing, two names) | | `Refs.cost_ref` |
| Σ p_i | total work, used to normalise tardiness | | `Refs.work` |
| SCALE | 10⁶: multiplies J's coefficients so CP-SAT gets integers | | `cpsat_model.SCALE` |
| cost_ub | an upper bound on cost, used as the multiplier in `makespan` mode | Σ_m (F_m + k_m · H) | `build()` |
| ε | the cap Cmax ≤ ε in the ε-constraint method (E4) | | `CpSatOptions.makespan_cap` |

**Experiment knobs**

| Symbol | Meaning | Typical values | In code |
|---|---|---|---|
| n | number of tasks | 10–100 | `generate(n_tasks=…)` |
| ρ (rho) | offered load: how busy the pool is during the arrival window | 0.5–1.5 (1.0 default) | `generate(rho=…)` |
| τ (tau) | deadline tightness: d_i = r_i + ⌈τ · p_i⌉. Smaller is tighter | 2.0 | `generate(tau=…)` |
| δ (delta) | duration-noise level in E6 | 0, 0.1, 0.2, 0.3 | `simulate.perturb(delta=…)` |
| ε_i | the random error of task i, drawn uniformly from [−δ, δ] | | `perturb` |
| p̃_i | actual (noisy) duration: round(p_i · (1 + ε_i)) | | `perturb` |

**Math symbols**

| Symbol | Read as |
|---|---|
| Σ | "sum of". Σ_i means "add up over all tasks i" |
| max_i | "the largest value over all tasks i" |
| ⌈ x ⌉ | "x rounded **up** to a whole number" (ceiling), e.g. ⌈3.5⌉ = 4 |
| ∈, ⊆ | "is in", "is a subset of" |
| [a, b) | the time interval from a up to, but not including, b. [0, 3) = minutes 0, 1, 2 |
| ≤, ≥ | at most, at least |
| gap | (best schedule's objective − best proven bound) / best schedule's objective |

---

## 3. Choosing the objective: the most important modelling decisions

### 3.1 What "cost" means

**Option we rejected:** cost = Σ (busy time × price). Durations don't depend on the machine, so this
cost depends only on *which* machine runs each task, not on timing. It barely interacts with
makespan, so there would be no real trade-off to study.

**Option we chose:** a VM is **leased from time 0 until its last task finishes** (`E_m`), plus an
activation fee if it is used at all (`y_m`):

```
Cost = Σ_m ( F_m · y_m  +  k_m · E_m )
```

Now using fewer machines saves fees and lease time, but tasks queue, so makespan grows. That is a
genuine conflict. Code: `src/metrics.py:68` (`cost`) and `:61` (`machine_end_times`).

### 3.2 Why normalise

The raw terms have different units: slots, money, and weighted slots. Adding `0.4·slots + 0.3·money`
is meaningless, and the result changes if you change currency. So each term is divided by a natural
reference, which makes it dimensionless:

```
J = α · Cmax / LB  +  β · Cost / Cost_greedy  +  γ · Σ w_i T_i / Σ p_i
```

| Term | Meaning of value 1.0 | Reference computed in |
|---|---|---|
| `Cmax / LB` | makespan equals a provable lower bound (can't do better) | `makespan_lb`, `src/metrics.py:48` |
| `Cost / Cost_greedy` | as expensive as the greedy schedule | `make_refs`, `src/metrics.py:57` |
| `Σ w T / Σ p` | (weighted) late time equals total work time | `Refs.work` |

The weights (α, β, γ) = **(0.4, 0.3, 0.3)** (`src/metrics.py:27`). Makespan is the headline metric, and
cost and lateness count equally. Because each term is dimensionless, the weights really are relative
importances. The objective is computed in `objective()`, `src/metrics.py:90`.

### 3.3 The lower bound LB (`src/metrics.py:48`)

```
LB = max(  max_i (r_i + p_i),                       a task can't finish before release + duration
           ceil( Σ cpu_i·p_i / Σ CPU_m ),           total CPU work spread perfectly over all machines
           ceil( Σ mem_i·p_i / Σ MEM_m ) )          same for memory
```

This is a valid bound because no schedule can beat any of the three. We use it (a) to normalise
makespan and (b) to judge quality without proof of optimality: CP-SAT's makespan is 1.00–1.01 × LB.

### 3.4 Where you would change the objective

* Weights: `Weights` in `src/metrics.py:27`; the default used everywhere is `experiments/common.py` (`WEIGHTS`).
* CP-SAT objective line: `src/cpsat_model.py:121`.
* MILP objective line: `src/milp_model.py:81`.

---

## 4. The two optimisation models

### 4.1.0 In plain English: what the MILP(Mixed Integer Linear Program) is, how it is solved, and why

**What it is: a giant yes/no spreadsheet.** Picture one sheet per machine. Each row is a task and each
column is a time slot (minute 0, 1, 2, …). Every cell asks one yes/no question: *"does this task
**start** on this machine at this minute?"* A schedule is just a choice of which cells to tick.

```
 One sheet per machine. Each cell asks: "does this task START here?"   (worked example §4.5, H = 5)

   Sheet "Machine 0"     minute →   0     1     2     3     4
                                 ┌─────┬─────┬─────┬─────┬─────┐
   Task A  (p=3, r=0)            │  ✔  │  ·  │  ·  │  –  │  –  │  – = cell doesn't exist
                                 ├─────┼─────┼─────┼─────┼─────┤      (A would end after H)
   Task B  (p=2, r=0)            │  ✔  │  ·  │  ·  │  ·  │  –  │
                                 ├─────┼─────┼─────┼─────┼─────┤
   Task C  (p=1, r=1)            │  –  │  ·  │  ·  │  ✔  │  ·  │  – at minute 0 = before release
                                 └─────┴─────┴─────┴─────┴─────┘
   Rule "exactly one tick per row" (summed over ALL machine sheets) = every task starts once.
   Number of cells = tasks × machines × minutes  →  this is why the MILP grows with the horizon.
```


The rules (constraints) are simple arithmetic on the ticks:

* **Exactly one tick per task** across all sheets: every task starts once, somewhere.
* **No tick before the release time:** those cells simply don't exist.
* **Capacity:** for every machine and every minute, add up the CPU of all tasks *running* at that
minute (started recently enough to still be going). The total must not exceed the machine's CPU.
The same goes for memory.
* Completion time, lateness, makespan and lease end are then just sums and "≥" relations over the ticks.

Everything is a **linear** equation or inequality in 0/1 variables. That is what "Mixed-Integer
Linear Program" means: linear maths, with some variables forced to be whole numbers (0 or 1).

```
 ┌─ How a START tick becomes "running at minute t" ──────────────────────────────────────┐
 │  A lasts 3 minutes, so A is running at minute 2 if it started at minute 0, 1 or 2:    │
 │                                                                                       │
 │      minute:   0   1   2                                                              │
 │      start 0:  ■   ■   ■   ← running at 2                                             │
 │      start 1:      ■   ■   ■                                                          │
 │      start 2:          ■   ■   ■                                                      │
 │                                                                                       │
 │  Capacity row for minute 2 on a 4-CPU machine (one such row per machine per minute):  │
 │      2·(x[A,0] + x[A,1] + x[A,2])  +  2·(x[B,1] + x[B,2])  +  4·x[C,2]   ≤  4 · y     │
 │        A's possible starts              B's (p = 2)            C's (p = 1)            │
 └───────────────────────────────────────────────────────────────────────────────────────┘
```


**How the solver (HiGHS) finds the best one: branch and bound.**

1. **Relax:** pretend a cell may be ticked *partially* (e.g. 0.3 of a start). That makes it an

   ordinary linear program, solvable very fast. Its answer is a **lower bound**: the real answer
    can't be better than the relaxed one.
2. **Branch:** if some cell came out fractional, split into two sub-problems: "this cell = 0" and

   "this cell = 1". Solve each relaxation again.
3. **Bound / prune:** keep the best real (all-integer) schedule found so far. Any sub-problem whose

   relaxed bound is already worse than that cannot contain anything better, so discard it unopened.
4. Stop when every branch is solved or pruned. The best integer schedule is then **proven optimal**.

   If time runs out first, the distance between the best schedule and the best bound is the **gap**.

```
 Branch and bound as a tree (illustrative numbers, minimising makespan)

                     ┌──────────────────────────────────┐
                     │ ROOT: relaxed LP (ticks may be   │
                     │ fractional)  bound = 3.5         │
                     │ x[C,1] = 0.5  ← fractional!      │
                     └────────────────┬─────────────────┘
                     branch on x[C,1] │
               ┌──────────────────────┴───────────────────────┐
     ┌─────────┴──────────┐                         ┌─────────┴──────────┐
     │ x[C,1] = 0         │                         │ x[C,1] = 1         │
     │ LP bound = 4.0     │                         │ LP bound = 5.0     │
     │ all ticks integer! │                         │ 5 ≥ best known (4) │
     │ ★ schedule Cmax 4  │                         │ ✂ PRUNE: can't win │
     └────────────────────┘                         └────────────────────┘

 ┌─ The optimality gap, read off the solver at any moment ───────────────┐
 │   worse  ▲  best schedule found so far (incumbent)  ─────  J = 0.60   │
 │          │                    gap = (0.60 − 0.45) / 0.60 = 25 %       │
 │   better ▼  best proven bound (no schedule can beat) ─────  J = 0.45  │
 │   gap = 0  ⇒  proven optimal                                          │
 └───────────────────────────────────────────────────────────────────────┘
```

**Why we built it:** it is the classic textbook formulation (it is literally the `x_imt` from our
proposal), it is easy to write down and check, and a general-purpose solver can prove optimality.
**Why it is not our main solver:** the spreadsheet has one column per minute. Double the time
horizon and you double the number of cells. Linear-programming relaxations of "is it running at
minute t" are also weak (fractional ticks can smear a task across many minutes), so the bounds are
loose and branching takes long.

### 4.1 Time-indexed MILP (the textbook formulation; `src/milp_model.py`)

**Decision variable:** `x[i,m,t] = 1` if task *i* **starts** on machine *m* at slot *t*. It only exists
for machines the task fits on and for `r_i ≤ t ≤ H − p_i`, so release times are enforced by the index set.

| Constraint | Maths | Code |
|---|---|---|
| start exactly once | Σ_m Σ_t x[i,m,t] = 1 | `milp_model.py:52` |
| CPU capacity per slot | Σ over tasks *running* at t of cpu_i · x ≤ CPU_m · y_m | `milp_model.py:69` (rule at `:61`) |
| memory capacity | same with mem | `milp_model.py:70` |
| completion | C_i = Σ (t + p_i) · x[i,m,t] | `milp_model.py:71` |
| tardiness | T_i ≥ C_i − d_i, T_i ≥ 0 | `milp_model.py:72` |
| makespan | Cmax ≥ C_i | `milp_model.py:73` |
| machine lease end | E_m ≥ Σ_t (t+p_i) x[i,m,t] (0 if i not on m) | `milp_model.py:74` |
| tightening | x ≤ y_m | `milp_model.py:76` |

"Running at t" means started in `[t − p_i + 1, t]`. That is how a start variable turns into occupancy.

**Its weakness:** ~ (#task-machine pairs) × H binaries. Size grows **linearly with the horizon H**.
At 100 tasks, 10 machines and H = 300 that is about 300 000 binaries.

**Practical note:** the MILP is solved in a separate Python process (`_solve_in_subprocess`,
`milp_model.py:133`). HiGHS and OR-Tools ship conflicting native libraries and segfault when both are
loaded in one process on macOS. If asked, it is an engineering workaround and does not affect results.

### 4.2.0 In plain English: what the CP-SAT model is, how it is solved, and why

**What it is: sliding blocks on lanes.** Forget the per-minute grid. Think of each task as a
**block**: its *width* is its duration and its *height* is its CPU need. Each machine is a **lane**
with a ceiling at its CPU capacity. The model asks only two questions per task:

1. **Which lane?** (a yes/no per eligible machine, with exactly one yes)
2. **Where does the block start?** (one whole number: the start minute)

The block only "exists" on the lane you picked. That is an **optional interval**. The key rule is
**Cumulative**: on each lane, at every moment, the heights of the blocks stacked there must not poke
through the ceiling. A second, invisible stack does the same for memory. It is like Tetris where blocks
may overlap in time as long as their total height fits.

```
 One LANE per machine. Each task is a BLOCK: width = duration, height = CPU.
 The worked example (§4.5) on its single 4-CPU lane:

   CPU
    4 ┤══════════════════════════  ← ceiling = machine capacity (Cumulative constraint)
      │   B     B     ·     C
    3 │   B     B     ·     C       stacked height ≤ ceiling at every minute
    2 │   A     A     A     C       minute 0: A+B = 4 ✓   minute 2: A = 2 ✓   minute 3: C = 4 ✓
    1 │   A     A     A     C
      └─────┴─────┴─────┴─────┴──►  minute
         0     1     2     3

 With several machines, every task has one possible block per lane, and exactly one is "switched on":

   Lane M0 (large) │ ▓▓▓ task 7 ▓▓▓        │     ▓ = interval present   (a[7,M0] = 1)
   Lane M1 (small) │ ░░░ task 7 ░░░        │     ░ = interval absent    (a[7,M1] = 0)
   Lane M2 (small) │ ░░░ task 7 ░░░        │     ExactlyOne(a[7,·]) → one lane only

 ┌─ What CP-SAT decides per task ──────────────────────────────────┐
 │  which lane?   a[i,m] ∈ {0,1} for each machine it fits on       │
 │  start?        S_i  = one integer in [r_i, H − p_i]             │
 │  ⇒ ~2 decisions per task, no matter how long the timeline is    │
 └─────────────────────────────────────────────────────────────────┘
```


Because a task is one block (not one tick per minute), the model has the same size whether the
timeline is 50 or 5 000 minutes long.

**How CP-SAT finds the best one: a mix of four techniques, run in parallel.**

1. **Propagation (reasoning):** every constraint actively narrows down what is still possible.

   *"A and B already fill the 4-CPU machine during minutes 0–2, so C (needs 4 CPU) cannot start before
    minute 3."* This cuts away huge parts of the search before trying anything.
2. **Search (guessing):** when reasoning alone can't decide, it guesses ("put task 7 on machine 2"),

   propagates, and continues.
3. **Learning from failures (the "SAT" part):** when a guess leads to a contradiction, it records a

   short reason (a "clause") so that it never makes that combination of mistakes again.
4. **Improving good solutions (LNS):** it takes the best schedule so far, frees a random part of it,

   and re-optimises that part. It also solves LP relaxations to get a **lower bound** and hence a gap.

With 8 workers, eight different strategies run at once and share what they find.

```
 How CP-SAT searches (one worker; 8 workers run variations of this in parallel)

     ┌──────────────┐   "put task 7 on M2,     ┌──────────────┐
     │    DECIDE    │ ──── start it at 12" ──► │  PROPAGATE   │  every constraint removes
     │   (a guess)  │                          │  (reasoning) │  values that can't work
     └──────▲───────┘                          └──────┬───────┘
            │ no conflict: next decision              │ conflict? (a variable has no value left)
            │                                         ▼
     ┌──────┴───────┐                          ┌──────────────┐
     │  BACKTRACK   │ ◄──── undo the guess ─── │    LEARN     │  store a short "never do
     │              │                          │  (a clause)  │  this combination" rule
     └──────────────┘                          └──────────────┘
   alongside:  LNS = free part of the best schedule and re-optimise it  → better solutions
               LP relaxation                                           → lower bound → gap

 ┌─ Propagation example (worked example, once A and B are placed at minute 0) ──┐
 │  before:   S_C ∈ {1, 2, 3, 4}                                                │
 │  known:    minute 1 uses 4/4 CPU (A+B), minute 2 uses 2/4 (A)                │
 │  rule:     C needs 4 CPU for 1 minute → no room at 1, no room at 2           │
 │  after:    S_C ∈ {3, 4}            ← two values removed without guessing     │
 └──────────────────────────────────────────────────────────────────────────────┘
```

**Why it is our main solver:** the problem *is* scheduling, and CP-SAT has scheduling built in
(intervals and cumulative with specialised reasoning). The model size doesn't grow with the horizon.
In our tests it found the same optima as the MILP, 9–28× faster.

### 4.2 CP-SAT model (the primary solver; `src/cpsat_model.py`)

CP-SAT is Google's constraint-programming + SAT + LP hybrid solver. Instead of one variable per time
slot, we use **interval variables**.

| Element | Meaning | Code |
|---|---|---|
| `S_i ∈ [r_i, H − p_i]` | start time of task *i* (release enforced by the domain) | `cpsat_model.py:73` |
| `a_im` (Boolean) | task *i* runs on machine *m* | `cpsat_model.py:77` |
| optional interval `[S_i, S_i+p_i)` | exists **only if** `a_im` is true | `cpsat_model.py:80` |
| `ExactlyOne(a_im)` | each task on exactly one machine | `cpsat_model.py:82` |
| `Cumulative` (CPU) | at every moment, Σ cpu of present intervals ≤ capacity | `cpsat_model.py:96` |
| `Cumulative` (MEM) | same for memory | `cpsat_model.py:97` |
| `T_i = max(end_i − d_i, 0)` | exact tardiness | `cpsat_model.py:84` |
| `y_m = max_i a_im` | machine used | `cpsat_model.py:98` |
| `E_m = max_i e_im` | lease end (e_im = end_i if on m, else 0) | `cpsat_model.py:100–106` |
| `Cmax = max_i end_i` | makespan | `cpsat_model.py:109` |
| objective | weighted J, scaled to integers | `cpsat_model.py:121` |

Key points to be able to say:

* **Model size doesn't depend on H**: it has one Boolean + one interval per (task, machine) pair. That is 932 pairs for our largest instances versus hundreds of thousands of MILP binaries.
* **Cumulative is a "global constraint"** with strong dedicated propagation (energetic reasoning, timetabling). It knows the problem is scheduling, whereas the MILP sees only rows of numbers.
* **We used max-equalities, not just inequalities.** That makes the reported makespan, cost and tardiness *exact*, so the validator can check them against recomputed values.
* **Integer coefficients:** CP-SAT accepts only integers, so `objective_coefficients` (`cpsat_model.py:51`) multiplies α/LB, β/Cost_ref, γ/Σp by `SCALE = 10⁶` (`:35`) and rounds. The error is below 10⁻⁵ in J.
* **Warm start:** `_add_hint` (`cpsat_model.py:135`) gives the solver the best baseline schedule as a starting point.
* **Solver parameters** (`solve`, `cpsat_model.py:157`): `max_time_in_seconds` (default 10), `num_workers` = 8, `random_seed`. We read `ObjectiveValue()` and `BestObjectiveBound()` to compute the **gap = (obj − bound)/obj**.

### 4.3.0 What an "objective mode" is, and its role in each model

**Two halves of every optimisation model.**

* The **constraints** define *which schedules are allowed*: capacity, release, run once. This is the
**feasible set**. Think of it as the set of all legal schedules.
* The **objective** defines *which allowed schedule is best*: the score we minimise.

Keep the constraints and change only the objective, and you get a *different* "best" schedule from
the *same* set of legal schedules. An **objective mode** is simply our switch for *which score* the
solver minimises. It is the `objective=` option in `CpSatOptions` (`cpsat_model.py:39`).

| Mode | "Best" means | Formula given to the solver | Used in |
|---|---|---|---|
| `weighted` (default) | best balance of speed, cost and lateness | `J` scaled to integers (`cpsat_model.py:121`) | E1, E2, E3, E5, E6, E7, E8; E4's weighted-sum sweep (with different α, β) |
| `cost` | cheapest; among equally cheap, fastest | `cost·(H+1) + Cmax` (`:123`) | E4: the ε-constraint points and the cheapest endpoint |
| `makespan` | fastest; among equally fast, cheapest | `Cmax·(cost_ub+1) + cost` (`:125`) | E4: the fastest endpoint |

```
 Same feasible set, three objective modes → three different "best" schedules (E4 instance)

   cost
   400 ┤  •      •    •         •        • = a legal schedule (satisfies all constraints)
       │     •  •   •     •              ● = Pareto front (can't improve one goal without
   313 ┤  ◆  ◄── `makespan` mode               hurting the other)
       │    ●  •     •    •
   288 ┤      ●   ★  ◄── `weighted` mode: best J; WHICH front point depends on α, β, γ
       │            ●  •
   256 ┤             ●  ●  ●  •
       │                       ●
   220 ┤                          ■  ◄── `cost` mode
       └──┬─────────┬─────────┬────────┬──►  makespan
          23        28        33       40
```

**What "lexicographic" means.** Like sorting words in a dictionary: compare the first letter, and look
at the second only on a tie. For `cost` mode we multiply cost by `H+1`, a number larger than any
possible makespan. Then saving even 1 unit of cost is worth more than any makespan change, and makespan
only breaks ties. Why bother with the tie-break? Without it the solver could return a schedule with
the same cost but a needlessly late finish, which is a point that is *dominated*, not on the Pareto front.

```
 ┌─ `cost` mode, lexicographic score = cost × (H+1) + Cmax        (H = 40, so H+1 = 41) ─┐
 │                                                                                       │
 │   schedule P:  cost 250, Cmax 35   →  250·41 + 35 = 10 285                            │
 │   schedule Q:  cost 250, Cmax 34   →  250·41 + 34 = 10 284   ← beats P (tie on cost)  │
 │   schedule R:  cost 249, Cmax 40   →  249·41 + 40 = 10 249   ← beats both: 1 unit of  │
 │                                                                cost outweighs any     │
 │                                                                makespan difference    │
 └───────────────────────────────────────────────────────────────────────────────────────┘
```

**Caps are not modes.** `makespan_cap` (ε) and `cost_cap` add an extra *constraint* ("finish by
minute ε"). They shrink the feasible set and leave the objective alone. The ε-constraint method in E4
is "mode = `cost`" plus "cap = ε", repeated for every ε.

```
 ε-constraint: `cost` mode + the cap "Cmax ≤ ε", repeated for every ε

   cost        allowed │ cut off by the cap
       │  ●            │
       │     ●         │
       │        ●  ◄── cheapest schedule left of the line = the front point for this ε
       │          ┊ ●  │
       │          ┊    ●
       │          ┊    │   ●
       └──────────┴────┴───────►  makespan
                       ε          slide ε from fastest to cheapest → trace the whole front
```

**Role in each model and method:**

| | Constraints | Objective |
|---|---|---|
| **CP-SAT** | intervals + cumulative + ExactlyOne | any of the three modes, ± caps |
| **MILP** | the tick-grid rows | only the weighted `J` (`milp_model.py:81`), with fractional coefficients (no integer scaling needed). It exists to check CP-SAT's `J` optimum (E8), so only one mode is required |
| **Baselines** | satisfied *by construction* (each task is placed only where it fits) | **none**: they follow a rule and never compare alternatives. Greedy-J is the exception: it uses `J`'s formula to choose a machine, but only for one task at a time |
| **Scoring (all methods)** | checked by the validator | every schedule, from any method, is scored with the same `J` by `metrics.objective` (`metrics.py:90`) |

```
                 ┌────────────── the SAME constraints (the feasible set) ─────────────────┐
   CP-SAT    ──► │ minimise  weighted J   |   cost (lex)   |   makespan (lex)   ± ε cap   │
   MILP      ──► │ minimise  weighted J only (to cross-check CP-SAT in E8)                │
   Baselines ──► │ no objective: follow a rule   (Greedy-J: J for one task at a time)     │
                 └────────────────────────────────────┬───────────────────────────────────┘
                                                      ▼  each method outputs a schedule
                                 validate.check()  →  metrics.objective() = J
                                   (feasible?)          (the shared scoreboard)
```

So the objective plays two roles: it is the **target** the solvers minimise, and the **scoreboard**
every method is judged on. Same scoreboard, same instances, which is why the comparison is fair.

### 4.3 Other objective modes (for the trade-off study)

`CpSatOptions.objective` (`cpsat_model.py:39`):

* `"weighted"`: the J above (default).
* `"cost"`: lexicographic, minimise cost first, then makespan: `cost·(H+1) + Cmax` (`:123`). The (H+1) multiplier means one unit of cost always outweighs any makespan difference.
* `"makespan"`: lexicographic the other way round (`:125`).
* `makespan_cap`: adds `Cmax ≤ ε` (`:114`). This is the **ε-constraint**.

### 4.4 The horizon H

* Safe: `H = max r_i + Σ p_i` (`Instance.safe_horizon`, `src/instance.py:66`); running everything back to back always fits.
* CP-SAT uses the safe H because its size doesn't depend on H, so it costs nothing.
* The MILP uses the **greedy makespan** as H to stay small. This is valid (a feasible schedule exists within it) but could, in principle, cut off a weighted-optimal schedule that finishes later. Admit this if asked.

### 4.5 Worked example (do this one by hand before the viva)

**Problem.** `tests/test_correctness.py:23`: one machine with **4 CPU** (and plenty of memory),
price 1 per slot, no activation fee. All deadlines are 10, so nobody is late here.

| Task | CPU | duration p | release r |
|---|---|---|---|
| A | 2 | 3 | 0 |
| B | 2 | 2 | 0 |
| C | 4 | 1 | 1 |

Try it yourself first: what is the shortest possible makespan?

#### Solution

**Step 1: find the lower bound before searching** (`metrics.makespan_lb`).

* Release bound: max(r + p) = max(0+3, 0+2, 1+1) = **3**.
* CPU-work bound: total CPU·time = 2·3 + 2·2 + 4·1 = 14 CPU-slots on a 4-CPU machine, so at least
14 / 4 = 3.5, rounded up to **4** slots.
* Memory bound: negligible here.
* **LB = max(3, 4) = 4.** No schedule can finish before minute 4.

**Step 2: reason about the conflict.** C needs all 4 CPUs, so nothing may run beside it. A and B
(2 + 2 = 4 CPU) can run *together*. C can't start before minute 1.

**Step 3: compare the options.**

| Option | Schedule | Makespan |
|---|---|---|
| ① A and B together first, C after | A [0,3), B [0,2), C [3,4) | **4** |
| ② C first (at its release), then A and B | C [1,2), A [2,5), B [2,4) | 5 |
| ③ B, then C in the gap, then A | B [0,2), C [2,3), A [3,6) | 6 |

Note: in option ① minute 2 runs only A (2 of 4 CPUs idle). Can C use that gap? No: C needs 4 CPUs
and A is still running.

```
   Option ①  Cmax = 4          Option ②  Cmax = 5            Option ③  Cmax = 6
   minute   0 1 2 3            minute   0 1 2 3 4            minute   0 1 2 3 4 5
   A        ■ ■ ■ ·            A        · · ■ ■ ■            A        · · · ■ ■ ■
   B        ■ ■ · ·            B        · · ■ ■ ·            B        ■ ■ · · · ·
   C        · · · ■            C        · ■ · · ·            C        · · ■ · · ·
   CPU /4   4 4 2 4            CPU /4   0 4 4 4 2            CPU /4   2 2 4 2 2 2
                               ↑ minute 0 wasted              ↑ A and B never share
```

**Step 4: check feasibility slot by slot** (exactly what the validator does):

| minute | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| A (2 CPU) | ■ | ■ | ■ | |
| B (2 CPU) | ■ | ■ | | |
| C (4 CPU) | | | | ■ |
| **CPU used / 4** | 4 | 4 | 2 | 4 |

Never above 4, every task starts at or after its release, so it is feasible.

**Step 5: prove optimality.** Option ① reaches makespan 4 = LB. The lower bound says nothing can be
faster, so ① is **optimal**. No search is needed here: the bound alone proves it. This is exactly how
we judge large instances, where CP-SAT's makespan is 1.00–1.01 × LB.

```
 ┌─ Why ① is provably optimal ────────────────────────────────────────────────┐
 │   from above:  best schedule found (option ①)       Cmax = 4               │
 │                                                        ║  gap = 0          │
 │   from below:  lower bound LB = ⌈14 CPU-slots / 4⌉   = 4                   │
 │                                                                            │
 │   nothing can be below the floor, and ① touches the floor  ⇒  optimal      │
 └────────────────────────────────────────────────────────────────────────────┘
```

**Step 6: what each model "sees".**

* **CP-SAT:** `S_A = 0, S_B = 0, S_C = 3`, `a_A,0 = a_B,0 = a_C,0 = 1`, `Cmax = 4`. Propagation does
the work: once A and B occupy [0,2), the cumulative constraint immediately rules out C at 1 and 2.
* **MILP** with H = 5: the ticked cells are `x[A,0,0] = x[B,0,0] = x[C,0,3] = 1` and everything else is
0, out of 12 binaries in total (A has 3 possible starts, B 4, C 4, plus `y`). Capacity row for
minute 1: `2·x[A,0,0] + 2·x[A,0,1] + 2·x[B,0,0] + 2·x[B,0,1] + 4·x[C,0,1] ≤ 4·y`, which gives 2 + 2 = 4 ≤ 4 ✓.
* **Objective J** (weights 0.4, 0.3, 0.3; references LB = 4, Cost_greedy = 4, Σp = 6):
J = 0.4·4/4 + 0.3·4/4 + 0.3·0/6 = **0.70**.

**Step 7: what the baselines do** (all verified by running the code):

| Method | Order of placement | Result | Makespan |
|---|---|---|---|
| FCFS | A, B, C (by release) | A at 0, B at 0, C at the first full-free minute = 3 | **4** ✓ |
| Greedy / Greedy-J | A, B, C | same as FCFS (there is only one machine) | **4** ✓ |
| **SJF** | **C, B, A** (shortest first) | C grabs [1,2) first; B can't fit across minute 1 so it goes to [2,4); A goes to [2,5) | **5** ✗ |

```
 ┌─ The SJF trap, step by step (order: shortest first = C → B → A) ────────────────┐
 │                                    minute   0 1 2 3 4                           │
 │  1) C placed at its release, 1     C        · ■ · · ·    minute 1 now FULL 4/4  │
 │  2) B needs 2 minutes in a row:    [0,2) crosses minute 1 ✗  →  [2,4) ✓         │
 │                                    B        · · ■ ■ ·                           │
 │  3) A needs 3 minutes in a row:    [0,3) ✗, [1,4) ✗  →  [2,5) ✓ (2+2 = 4 fits)  │
 │                                    A        · · ■ ■ ■                           │
 │  result: minute 0 wasted, Cmax = 5.  The early choice for C was never revisited.│
 └─────────────────────────────────────────────────────────────────────────────────┘
```

**The lesson:** a rule makes each decision once, in a fixed order, and never revisits it. SJF commits
C to minute 1 before it "knows" that this blocks A and B. An optimiser looks at all decisions together.
This is the whole project in miniature.

---

## 5. The baselines (`src/baselines.py`)

### 5.1 The four rules

All four are **list scheduling**: put the tasks in an order, then place each one at the earliest time
it fits on the chosen machine.

```
for task in order(tasks):
    m = choose_machine(task)
    t = earliest t ≥ r_i where task fits on m for [t, t + p_i)     ← Profile.earliest_fit
    commit
```

| Method | Order | Machine choice | Code |
|---|---|---|---|
| **FCFS** | release time | earliest start | `baselines.py:116` |
| **SJF** | shortest duration first | earliest start | `:120` |
| **Greedy** (least-loaded) | release time | least committed normalised work Σ p (cpu/CPU_m + mem/MEM_m) | `:124`, rule `:93` |
| **Greedy-J** (cost-aware) | release time | machine whose placement increases J the least | `:128` |

* `Profile` (`baselines.py:31`) stores CPU and memory usage per slot on one machine.
`earliest_fit` (`:45`) is the core helper. It builds a "slot has room" mask and uses a prefix sum to
find the first window of p free slots. Every baseline and the robustness simulator depend on it,
and it is unit-tested (`tests/test_correctness.py`, `test_earliest_fit_respects_both_resources`).
* **Why Greedy-J exists:** FCFS, SJF and Greedy ignore cost entirely, so beating them on cost alone
would be a weak claim. Greedy-J knows the objective but decides one task at a time (myopically). It
shows how much of the gain comes from *global* optimisation rather than just *caring about cost*.
* Ties are broken deterministically (start, price, id), so results are reproducible.

### 5.2 How the optimisation models, the objective and the scheduling methods fit together

**They all solve the same problem and produce the same kind of answer** (a table of task → machine,
start, end). They obey the same constraints, and the validator checks them with the same code. They
differ only in **how they decide**:

| | Baselines (FCFS, SJF, Greedy) | Greedy-J | CP-SAT / MILP |
|---|---|---|---|
| Type | **constructive heuristic**: a rule | heuristic that uses the objective | **exact optimisation**: model + solver |
| Knows the constraints? | yes, places each task only where it fits | yes | yes, as equations / global constraints |
| Knows the objective J? | no | yes, but one task at a time | yes, all tasks at once |
| Revisits a decision? | never (single pass) | never | constantly (search, backtracking, LNS) |
| Guarantee | none | none | proven optimal, or a proven gap |
| Time | milliseconds | milliseconds | 0.01 s to the time limit |

A baseline schedule is one particular point inside the feasible set the optimisation models
describe. The solver searches the whole set. That is why the solver can never do worse once it is
given the baseline as a starting point.

**The baselines are not only competitors. They also feed the optimisation models:**

```
                  ┌──────────── LB (metrics.makespan_lb) ────────────┐  normalises makespan
                  │                                                   ▼
 instance ──► baselines ──► Greedy's cost ─────────────────────► objective J  (the scoreboard)
                  │         (Cost_ref, normalises cost)               ▲
                  │                                                   │ minimised by
                  ├──► best baseline ──► warm-start hint ──────► CP-SAT model
                  └──► Greedy makespan ─► horizon H ───────────► MILP model
```

1. **Normalisation:** Greedy's cost is `Cost_ref` in J (`make_refs`, `metrics.py:57`). "Cost 1.0"

   means "as expensive as greedy".
2. **Warm start:** the best baseline (by J) is handed to CP-SAT as its first solution

   (`_add_hint`). CP-SAT starts from a good schedule and only has to improve it.
3. **Horizon:** Greedy's makespan is the MILP's horizon H in E8. A schedule exists within it, which

   keeps the tick-grid small.
4. **A sandwich around the optimum:** the best baseline gives an **upper bound** (the optimum is at

   least this good) and LB gives a **lower bound** on makespan. The solver's job is to close the gap
    between them, and we can judge how close it got even without a proof.
5. **Shared machinery:** the baselines' `Profile.earliest_fit` engine is reused by the robustness

   simulator (`simulate.replay`). Replaying a plan is just list scheduling with machine and order fixed.

**How the objective links everything:**

* For **CP-SAT and the MILP**, J is the *target*. The solver searches for the schedule with the lowest J.
* For **Greedy-J**, J is a *local guide*: "which machine raises J least for this one task right now?"
* For **FCFS, SJF and Greedy**, J plays no role while scheduling. It is only the *scoreboard* afterwards.
* For **every method**, J (and the separate makespan, cost and tardiness numbers) is computed by the
same `metrics.evaluate`, so the comparison is fair.

**What this means for interpreting results:** the gap between Greedy-J and CP-SAT (12–16 %) is the
value of **global** optimisation, i.e. looking at all tasks together. The gap between the cost-blind
rules and Greedy-J is the value of simply **caring about cost**. Report both. Examiners like seeing
that you separated the two effects.

---

## 6. How we know the results are correct

### 6.1 The independent validator (`src/validate.py`)

`check()` (`validate.py:19`) is run on **every schedule in every experiment** (through `assert_valid`,
called in `experiments/common.py` `run_methods`). It deliberately shares no code with the models: it is
a plain loop over every slot. It checks:

1. every task is scheduled exactly once;
2. on a machine it fits;
3. start ≥ release, and end = start + duration;
4. CPU and memory within capacity at every slot on every machine;
5. the solver's *reported* makespan, cost and tardiness equal values recomputed from scratch.

Why it matters: a wrong cumulative constraint would produce schedules that look great and are
impossible. The validator would catch that immediately.

### 6.2 Tests (`tests/test_correctness.py`, run `python -m pytest -q`, 19 tests)

| Test | What it proves |
|---|---|
| hand instance | CP-SAT gives the hand-computed optimum (Cmax = 4) |
| single machine, serial | when tasks can't overlap, Cmax = Σ p |
| single machine, unlimited capacity | Cmax = max(r + p) = LB, for CP-SAT and every baseline |
| brute force ×6 | on random 4-task instances, CP-SAT = exhaustive enumeration of all schedules |
| validator negatives | overlap, early start, missing task, wrong duration, wrong reported value are all caught |
| CP-SAT ≥ best baseline | with a warm start it is never worse than the hint |
| MILP = CP-SAT | same optimum on the same horizon |
| determinism | same seed gives an identical instance, identical baselines, identical optimal objective |
| replay | the robustness simulator produces valid schedules and keeps machine assignments |

---

## 7. Code map: what is where

```
main.py                     CLI: `demo`, `solve <instance.json>`, `experiments`
src/
  instance.py               Task / Machine / Instance / Schedule; JSON load/save; generator
  metrics.py                cost, makespan, tardiness, utilisation, LB, normalised objective J, evaluate()
  baselines.py              Profile (resource timeline), FCFS, SJF, Greedy, Greedy-J
  cpsat_model.py            CP-SAT build + solve (+ ε-constraint, lexicographic modes, warm start)
  milp_model.py             Pyomo time-indexed MILP solved by HiGHS (in a subprocess)
  validate.py               independent feasibility + reported-value checker
  simulate.py               perturb() durations, replay() a plan as a policy
  trace.py                  Google 2011 trace → Instance (assumptions A1–A6 at the top)
experiments/
  common.py                 run_methods(): all 5 methods on one instance, validate, metric rows
  run_e1_methods.py … run_e8_milp.py   one script per experiment → results/*.csv + tables/*.md
  plots.py                  CSVs → results/figures/*.png
  run_all.py                runs everything (`--quick` for a 3-minute smoke run)
tests/test_correctness.py   the checks in §6.2
data/synthetic/*.json       the instances used in E1 (every method reads the same file)
data/trace/                 google2011_pool.csv (3000 real tasks) + the 5 trace instances
results/                    e*.csv (raw), tables/*.md (mean ± std), figures/*.png, schedules/*.csv
REPORT.md                   report draft      proposal_1page.md   1-page proposal
```

**Most important files to read, in order:** `metrics.py` → `cpsat_model.py` (`build`) →
`baselines.py` → `validate.py` → `experiments/common.py`. Together they are about 500 lines.

---

## 8. Walkthrough: what happens when you run `python main.py demo`

1. `main.py` → `generate(30, 5, seed=0, rho=1.0, tau=2.0)` (`instance.py:150`):
   * picks 5 VMs (machine 0 always large, so every task fits somewhere);
   * draws CPU/memory demands (lognormal: mostly small, a few big) and durations (bimodal: 75 % short around 4 slots, 25 % long around 15);
   * spreads release times over a window sized for load ρ (`offered_load_window`, `:140`);
   * sets deadlines `d = r + ceil(τ·p)`.
2. `run_methods(inst, …)` (`experiments/common.py`):
   1. runs the 4 baselines;
   2. computes the normalisation refs (`make_refs`) from Greedy: LB, Greedy's cost, Σp;
   3. picks the baseline with the best J and uses it as the **warm start**;
   4. builds and solves the CP-SAT model;
   5. runs the **validator** on all 5 schedules;
   6. computes metrics with `evaluate()` (`metrics.py:117`).
3. Prints a table, for example (seed 0):

```
  method  objective  makespan  cost  weighted_tardiness  machines_used
    FCFS      0.652        21   326                   1              5
     SJF      0.768        26   356                   0              5
  Greedy      0.910        30   391                  21              5
Greedy-J      0.662        21   303                  16              5
  CP-SAT      0.563        21   203                   4              2      OPTIMAL, gap 0 %
```

Read it like this: CP-SAT has the same makespan as the best rule (21 = LB) at about 40 % lower cost,
because it uses 2 machines instead of 5.

---

## 9. The experiments: question → setup → result → takeaway

Common settings: CP-SAT time limit 10 s, 8 workers, warm start from the best baseline, weights
(0.4, 0.3, 0.3), ρ = 1, τ = 2 unless stated. Every number below is in `results/tables/`.

### E1: method comparison (`run_e1_methods.py`, `figures/e1_methods.png`)

* **Question:** how much better is CP-SAT than the rules?
* **Setup:** 10 seeds × {20, 50, 100} tasks on {4, 6, 8} machines.
* **Result:** J of CP-SAT 0.56 / 0.57 / 0.60 vs best baseline 0.64 / 0.69 / 0.70, i.e. **−12 % / −16 % / −14 %**. Cost is −48 / −43 / −35 % vs Greedy. Makespan is 1.00–1.01 × LB. Utilisation of leased CPU is 0.70–0.76 vs 0.39–0.59.
* **Takeaway:** the gain is **mainly cost**, from consolidating work onto fewer, larger machines (see `figures/usage_profile_greedy_vs_cpsat.png`, where CP-SAT runs all 20 tasks on one large VM). FCFS is already near-optimal on makespan. Greedy and Greedy-J build up large tardiness at 100 tasks (131 and 182 slots).

### E2: scalability (`run_e2_scalability.py`, `figures/e2_scalability.png`)

* **Question:** how does solve time grow with problem size?
* **Setup:** n = 10 … 100 tasks (machines = n/10, 3–10), 3 seeds, 10 s limit.
* **Result:** proven optimal for n ≤ 30 in < 0.25 s. At n = 50, 1 of 3 proven (gap 4.5 %). At n = 75 / 100 none are proven (gap 19 % / 23 %), **yet makespan = LB in every case**.
* **Takeaway:** the large gaps come from a weak *bound* on the cost part, not from bad *solutions*. Proving optimal machine consolidation is bin-packing-hard.

### E3: load sensitivity (`run_e3_load.py`, `figures/e3_load.png`)

* **Question:** does the optimiser's advantage grow with load?
* **Setup:** ρ ∈ {0.5, 0.75, 1.0, 1.25, 1.5}, 40 tasks, 5 machines, 5 seeds.
* **Result:** baselines are 13–31 % worse in J at **every** load, and the gap doesn't grow. On *makespan alone*, FCFS/Greedy are within 1 % at ρ = 0.5 and 6–10 % behind at ρ = 1.5. SJF has the fewest late tasks.
* **Takeaway:** at low load the optimiser saves money, not time. At high load it saves both. If you care only about completion time at low load, a simple rule is enough. This partly contradicts the plan's expectation that greedy ≈ optimal at low load: that holds for makespan, not for the combined objective.

### E4: Pareto front (`run_e4_pareto.py`, `figures/e4_pareto.png`)

* **Question:** what is the actual cost-vs-speed trade-off?
* **Setup:** a capacity-bound instance (24 tasks, 5 machines, ρ = 2). For **every integer ε** between the fastest and the cheapest schedule: minimise cost subject to Cmax ≤ ε. We compare this with an 11-point weighted-sum sweep.
* **Result:** **16 non-dominated schedules, all proven optimal**, from (makespan 23, cost 313) to (40, 220). The weighted sum finds **only 4** of them and returns one dominated point. All baselines are far above the front (Greedy-J at (27, 408) vs front (27, 278), i.e. 47 % more expensive).
* **Takeaway:** a 30 % cost reduction costs 74 % more makespan. Speed is expensive near the fast end, and the curve is flat in the middle. The ε-constraint method is necessary because weighted sums only find points on the convex hull.

### E5: anytime behaviour (`run_e5_anytime.py`, `figures/e5_anytime.png`)

* **Question:** how much time does CP-SAT need? Does the warm start help?
* **Setup:** 100 tasks, 8 machines, ρ = 1.2, time limits 1–60 s, with and without warm start.
* **Result:** within 8.5 % of the best schedule found at 1 s, 2.8 % at 5 s, 0.5 % at 30 s. It beats the best baseline (1.17×) already at 1 s. The gap stays at 26–36 %. The warm start helps only at 1 s.
* **Takeaway:** 5–10 s is enough in practice. The gap is the bound's problem, not the solution's.

### E6: robustness (`run_e6_robustness.py`, `src/simulate.py`, `figures/e6_robustness.png`)

* **Question:** what if the durations we planned with are wrong (proposal Question 3)?
* **Method:** a plan's start times become meaningless when durations change, so we replay it as a **policy**: keep each task's machine and its order on that machine, then start every task as early as release, order and capacity allow under the *actual* durations p̃ = round(p·(1 + U[−δ, δ])) (`replay`, `simulate.py:28`). Every policy sees the same random draws (common random numbers). 30 draws × 5 instances.
* **Result:** at δ = 0.3 the CP-SAT plan loses **14 %** of its quality vs **4 %** for greedy. Its tardiness rises from 1.8 to 14. But it is still **18 % better** than greedy, and better than a greedy that knows the true durations.
* **Takeaway:** tight optimal plans are more fragile (no slack), but the advantage survives realistic estimation errors.

### E7: real Google trace (`run_e7_trace.py`, `src/trace.py`, `figures/e7_trace.png`)

* **Data:** one 4 MB part of the 2011 Google cluster trace `task_events`, which gives 37 944 usable finished tasks. We ship a 3000-task pool in `data/trace/google2011_pool.csv`. The experiment uses 5 samples of 60 tasks on 6 VMs.
* **Conversion assumptions (A1–A6, top of** `src/trace.py`**):** runtime = FINISH − SCHEDULE rounded up to minutes; requests normalised to the largest Google machine, with our large VM assumed to be 20 % of it; release order kept but rescaled to load ρ = 1; deadlines synthetic (τ = 2); weights from priority tiers.
* **Result:** CP-SAT J 0.60 vs best baseline 0.71 (−16 %), makespan = LB, cost −34 % vs Greedy. This reproduces the synthetic picture.

### E8: MILP vs CP-SAT (`run_e8_milp.py`, `figures/e8_milp_vs_cpsat.png`)

* **Question:** why use CP-SAT and not the textbook MILP?
* **Setup:** 6–12 tasks, 3 machines, same H for both. Then one 8-task instance with H scaled 1–4×.
* **Result:** **identical optima on all 12 instances**; CP-SAT is 9–28× faster (both below 0.5 s at this size). As H goes from 29 to 116, MILP binaries grow from 483 to 2 571 and its time grows with them, while CP-SAT stays at 27 assignment Booleans.
* **Takeaway:** both are correct; the MILP doesn't scale with the horizon. This is evidence for the solver choice.

---

## 10. Numbers to remember

| Fact | Value |
|---|---|
| Objective improvement over best baseline | **12–16 %** (synthetic and trace) |
| Cost reduction vs Greedy | **35–48 %** |
| CP-SAT makespan vs lower bound | **1.00–1.01 ×** |
| Instances where CP-SAT strictly best | **78 / 78** (margin ≥ 5 %) |
| Proven optimal up to | **30 tasks** (< 0.25 s) |
| Gap at 100 tasks, 10 s | **23 %** (but makespan = LB, and +60 s improves < 2 %) |
| Pareto front | **16 points**, weighted sum finds **4** |
| Robustness at ±30 % | CP-SAT −14 % vs greedy −4 %, CP-SAT still **18 %** better |
| MILP = CP-SAT optimum | **12 / 12** instances, CP-SAT **9–28×** faster |
| Weights (α, β, γ) | **(0.4, 0.3, 0.3)** |
| Integer scaling | **× 10⁶**, rounded |

---

## 11. Likely viva questions, with answers

**Q: Why CP-SAT rather than MILP?**
The time-indexed MILP needs one binary per (task, machine, time slot), so it grows with the horizon:
about 300k binaries at 100 tasks and H = 300. CP-SAT uses one optional interval per (task, machine)
pair, independent of H, and its cumulative constraint has dedicated scheduling propagation. E8 shows
identical optima where both can be solved, CP-SAT 9–28× faster, and MILP size growing linearly with H.

**Q: How did you choose α, β, γ? Why normalise?**
The raw terms have different units, so their weighted sum would be meaningless and would depend on
the currency. We divide each term by a natural reference: the lower bound, the greedy cost, and total
work. That makes each term dimensionless with a clear meaning (1.0 = at the bound, as expensive as
greedy, as late as the total work). Then the weights are relative importances. We put makespan
slightly first (0.4) and cost and lateness equal (0.3 each). E4 shows the whole trade-off, so the
conclusions don't hinge on one weighting.

**Q: Why ε-constraint and not a weighted-sum sweep?**
A weighted sum can only find points on the convex hull of the front (supported points). Our front
isn't convex: the sweep found 4 of 16 Pareto-optimal schedules and returned a dominated one at α = 1,
because with zero weight on cost, any cost is "optimal". The ε-constraint method finds every point.

**Q: Is your schedule optimal?**
Proven optimal (gap 0) up to 30 tasks, and for every point on the Pareto front. For larger
instances, not proven. But the makespan equals the lower bound (so it is optimal in that term), the
incumbent improves under 2 % with 6× more time, and the remaining gap is the solver's weak bound on
the cost term. We also verified CP-SAT against brute force on tiny instances and against the MILP on
small ones.

**Q: How do you know the schedules are feasible?**
An independent per-slot validator, sharing no code with the models, checks every schedule in every
experiment. It also recomputes the solver's reported objective terms. There are 19 unit tests,
including a hand-solved instance and brute force.

**Q: What happens if durations are wrong?**
E6: we replay the plan as a policy under ±10–30 % noise. The optimised plan degrades faster (−14 % vs
−4 % at ±30 %) because it is tightly packed with no slack, but it stays 18 % better than greedy.

**Q: When is the optimiser not worth it?**
When only completion time matters and load is low: FCFS is within 1 % on makespan at ρ = 0.5 (E3).
Also when you need a *proof* of optimality for large instances quickly (E2). SJF is also better if
the only goal is the fewest late tasks.

**Q: Why does CP-SAT have more late tasks than SJF sometimes?**
Because the objective trades off. CP-SAT accepts a couple of slightly late tasks when that saves more
cost than it adds in weighted tardiness. Raise γ to change that.

**Q: Why is cost "leased from time 0"? Isn't that unrealistic?**
It models reserving a VM for the batch window. More importantly, it is what creates the trade-off:
with pure busy-time pricing and machine-independent durations, cost wouldn't depend on timing at all
(§3.1). We say this explicitly as a modelling choice.

**Q: Why is the gap 23 % if the solution is good?**
The gap compares with the solver's best *proven bound*. For the cost term that bound comes from a
bin-packing-like relaxation that is weak. The solutions themselves are within 1.4 % of what 60 s
finds, and their makespan equals our independent LB.

**Q: What does the warm start do, and does it matter?**
`AddHint` gives the best baseline schedule as the initial solution. It helps only at very short time
limits (1 s); CP-SAT finds better solutions quickly on its own.

**Q: What is the horizon and why does it matter?**
H is the last slot a task may end in. CP-SAT uses the safe bound max r + Σp, which is free for it.
The MILP uses the greedy makespan to stay tractable. That is valid, but it can restrict weighted
solutions that finish later.

**Q: How did you use the Google trace?**
One part of the 2011 `task_events` table. Runtime = FINISH − SCHEDULE. CPU and memory requests are
scaled assuming our large VM is 20 % of Google's largest machine. Release order is kept but rescaled
to load 1, and deadlines are synthetic. Every assumption is listed at the top of `src/trace.py`.

**Q: Why is the comparison fair?**
Every method reads the same instance file. All are validated by the same checker and scored by the
same `evaluate()`. We added Greedy-J so we are not only beating cost-blind rules. E6 uses common
random numbers for all policies.

**Q: Is it reproducible?**
Instances, baselines and noise draws are all seeded. CP-SAT under a wall-clock limit with 8 threads
can vary slightly when it stops early (status FEASIBLE). Results with status OPTIMAL are reproducible,
and a test checks this.

**Q: How would you extend it?**
Online arrivals with rolling-horizon re-solving; robust planning (padded durations or slack);
machine-dependent speeds; hard deadlines with admission control; per-minute billing.

---

## 12. Weak spots: own them before the examiner raises them

* **The baselines ignore cost**, so part of the gain is "caring about cost". That is why we added Greedy-J. CP-SAT still beats it by 12–16 %.
* **Synthetic deadlines** everywhere, including on the trace. The trace has no deadlines.
* **Trace scaling assumptions** (VM = 20 % of the largest Google machine, rescaled releases) are our choices, not facts from the data.
* **The MILP comparison is small-instance only**, and the MILP uses a tighter horizon.
* **Large-instance gaps are not closed**, so we can't claim optimality beyond about 30–50 tasks.
* **Wall-clock time limits** mean slight run-to-run variation for non-optimal solves.
* **Lease-from-0 cost** is a modelling choice. Other billing models change the trade-off.

---

## 13. Demo script (about 5 minutes)

```bash
python main.py demo                       # 1. one instance, all 5 methods, validated table (≈ 2 s)
python main.py demo --n 60 --rho 1.5      # 2. heavier load: watch the makespan gap grow
python -m pytest -q                       # 3. correctness: 19 tests incl. brute force (≈ 1 min)
open results/figures/usage_profile_greedy_vs_cpsat.png   # 4. WHY CP-SAT wins (consolidation)
open results/figures/e4_pareto.png        # 5. the trade-off + weighted-sum failure
open results/figures/e6_robustness.png    # 6. robustness answer
```

Have `src/cpsat_model.py` open at `build()` (line 60) to point at the intervals (`:80`), ExactlyOne
(`:82`) and cumulative (`:96`) lines while you explain the model.

---

## 14. Who should master what

Split the reading as the plan suggests, but **everyone** must be able to explain §3 and §4.

| Member | Own deeply | Files |
|---|---|---|
| A: data and robustness | generator, ρ/τ knobs, trace conversion, replay simulator, E6, E7 | `instance.py`, `trace.py`, `simulate.py`, `run_e6*`, `run_e7*` |
| B: baselines and evaluation | list scheduling, `earliest_fit`, Greedy-J, validator, metrics and LB, tests, E1, E3 | `baselines.py`, `validate.py`, `metrics.py`, `tests/`, `run_e1*`, `run_e3*` |
| C: models and solver | CP-SAT model, MILP, scaling, ε-constraint, gap, E2, E4, E5, E8 | `cpsat_model.py`, `milp_model.py`, `run_e2*`, `run_e4*`, `run_e5*`, `run_e8*` |

**Self-test:** each member should be able to (1) write the MILP on a whiteboard, (2) explain one
cumulative constraint with a picture, (3) recompute the hand example in §4.5, and (4) explain any
figure in `results/figures/` in two sentences.
