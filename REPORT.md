# Multi-Objective Cloud Task Scheduling Under CPU, Memory, and Deadline Constraints

*Project topic: Cloud Computing Resource Allocation and Task Scheduling*

**Team:** `<TEAM NAME>` — `<Member 1>`, `<Member 2>`, `<Member 3>`

> Draft generated from the results in `results/`. All numbers are means ± std over the seeds stated
> in each experiment. Figures are in `results/figures/` and the tables behind them in `results/tables/`.

---

## 1. Problem statement and motivation

A cloud platform receives a batch of tasks. Each task has a CPU demand, a memory demand, a duration, a
release time, a deadline and a priority. The tasks must run on a small pool of heterogeneous virtual
machines that differ in capacity and price. The operator decides **which task runs on which machine
and when**. Three goals conflict:

* **finish early** (low makespan), which favours spreading work over many machines;
* **spend little**, which favours packing work onto few, cheap machines, because a leased VM costs
  money until its last task ends;
* **meet deadlines**, which favours starting urgent tasks early, wherever there is room.

We want to quantify this trade-off and answer three questions. Does an exact optimiser beat the simple
rules used in practice, and by how much? What changes as load grows? What happens when the duration
estimates the plan is built on are wrong?

**Scope.** Offline, deterministic batch scheduling: all tasks are known up front, 10–100 tasks,
3–10 machines, integer time slots (1 slot = 1 min), no preemption, no splitting of a task across
machines, and durations that do not depend on the machine. Deadlines are soft. Online arrivals and
rescheduling are out of scope.

## 2. Mathematical formulation

### 2.1 Data

| Symbol | Meaning |
|---|---|
| $i \in I$ | tasks: CPU $c_i$, memory $q_i$, duration $p_i$, release $r_i$, deadline $d_i$, weight $w_i$ |
| $m \in M$ | machines: CPU capacity $C_m$, memory capacity $Q_m$, price per slot $k_m$, activation fee $F_m$ |
| $M_i \subseteq M$ | machines that task $i$ fits on ($c_i \le C_m$, $q_i \le Q_m$) |
| $H$ | scheduling horizon |

Three VM types are used: small (4 CPU, 8 MEM, $k=2$, $F=10$), medium (8, 16, 3, 15) and large
(16, 32, 5, 20). Larger VMs cost more per slot but less per CPU unit, so there is a real choice between
one big machine and several small ones.

### 2.2 Cost model

The cost model determines whether a trade-off exists at all. Suppose cost were "busy time × price"
and durations did not depend on the machine. Then cost would depend only on the assignment, not on the
timing, and it would barely interact with makespan. We instead model a VM as **leased from time 0 until
its last task ends**, with an activation fee if it is used at all:

$$\text{Cost} = \sum_m \left(F_m\,y_m + k_m\,E_m\right)$$

With this model, using fewer or cheaper machines lowers cost but delays completion, which is the
conflict we want to study.

### 2.3 Normalised objective

The raw terms have incompatible units: slots, cost units, and weighted slots. Each term is therefore
divided by a natural reference:

$$\min\; J = \alpha\,\frac{C_{\max}}{LB} + \beta\,\frac{\text{Cost}}{\text{Cost}_{\text{greedy}}} + \gamma\,\frac{\sum_i w_i T_i}{\sum_i p_i}, \qquad (\alpha,\beta,\gamma) = (0.4,\,0.3,\,0.3)$$

* $C_{\max}/LB \ge 1$ measures how far the makespan is from a provable lower bound (§2.6).
* $\text{Cost}/\text{Cost}_{\text{greedy}}$ is cost relative to the greedy schedule (1.0 = as expensive as greedy).
* $\sum w_i T_i / \sum p_i$ is the (weighted) fraction of total work-time that is late.

Every term is dimensionless and has a meaning, so the weights express relative importance. We put
makespan first because completion time is the headline metric, and we weight cost and lateness equally.
§5.3 studies the whole trade-off rather than only this one weighting.

### 2.4 Time-indexed MILP

Variables: $x_{imt} \in \{0,1\}$ (task $i$ starts on $m$ at $t$, for $m \in M_i$ and $r_i \le t \le H-p_i$);
$y_m \in \{0,1\}$; and continuous $C_i, T_i, E_m, C_{\max} \ge 0$.

$$
\begin{aligned}
&\textstyle\sum_{m}\sum_{t} x_{imt} = 1 && \forall i &&\text{(start exactly once; release via index set)}\\
&\textstyle\sum_i \sum_{s=t-p_i+1}^{t} c_i\, x_{ims} \le C_m\, y_m && \forall m, t &&\text{(CPU capacity)}\\
&\textstyle\sum_i \sum_{s=t-p_i+1}^{t} q_i\, x_{ims} \le Q_m\, y_m && \forall m, t &&\text{(memory capacity)}\\
&\textstyle C_i = \sum_{m,t} (t+p_i)\, x_{imt} && \forall i &&\text{(completion)}\\
&T_i \ge C_i - d_i,\; T_i \ge 0 && \forall i &&\text{(soft deadline)}\\
&C_{\max} \ge C_i && \forall i &&\text{(makespan)}\\
&\textstyle E_m \ge \sum_t (t+p_i)\, x_{imt} && \forall i, m &&\text{(lease end; RHS is 0 if } i \notin m)\\
&x_{imt} \le y_m && &&\text{(tightening)}
\end{aligned}
$$

The model has $\approx \sum_i |M_i|\,(H - r_i - p_i + 1)$ binaries, so its size grows **linearly in the
horizon**. With 100 tasks, 10 machines and $H=300$, that is about 300 000 binaries.

### 2.5 CP-SAT model (primary)

The same model, written with scheduling primitives:

* $S_i \in [r_i, H-p_i]$ is the start of task $i$. Release times are encoded in the domain.
* For each $m \in M_i$: a Boolean $a_{im}$ and an **optional interval** $[S_i, S_i+p_i)$ that exists iff $a_{im}$.
* $\text{ExactlyOne}(a_{im} : m \in M_i)$ for every task.
* Per machine, one $\text{Cumulative}$ on CPU (demands $c_i$, capacity $C_m$) and one on memory.
* Exact definitions through max-equalities: $C_{\max} = \max_i (S_i+p_i)$; $T_i = \max(0, S_i+p_i-d_i)$;
  $y_m = \max_i a_{im}$; and $E_m = \max_i e_{im}$, where $e_{im} = S_i+p_i$ if $a_{im}$ and $0$ otherwise.
  Because these are equalities rather than bounds, the solver's reported makespan, cost and tardiness
  are exact, and the validator checks them.

The model has $\sum_i |M_i|$ Booleans and intervals, **independent of $H$**. CP-SAT only accepts integer
coefficients, so the three normalised weights are multiplied by $10^6$ and rounded
($\alpha/LB \to \text{round}(10^6\alpha/LB)$, etc.). The rounding error is below $10^{-5}$ in $J$.

The same model also supports the bi-objective study. A lexicographic "min cost, then makespan"
objective $(H+1)\cdot\text{Cost} + C_{\max}$ combined with $C_{\max} \le \varepsilon$ gives the
ε-constraint method.

### 2.6 Horizon and lower bound

* Safe horizon $H = \max_i r_i + \sum_i p_i$ (everything back to back always fits). CP-SAT uses this
  horizon at no extra cost, because its size does not depend on $H$. For the MILP we use the much
  tighter greedy makespan. This is valid because the greedy schedule is feasible within it, but it
  can in principle cut off weighted-optimal schedules that finish later.
* Lower bound:
  $LB = \max\big(\max_i (r_i+p_i),\ \lceil \sum_i c_i p_i / \sum_m C_m \rceil,\ \lceil \sum_i q_i p_i / \sum_m Q_m \rceil\big)$.

## 3. Methodology and solver details

**Baselines.** All baselines share one list-scheduling engine: tasks are ordered, then each is placed
at the earliest slot $t \ge r_i$ at which both resources are free for $[t, t+p_i)$. Ties are broken
deterministically.

| Method | Order | Machine choice |
|---|---|---|
| FCFS | release time | earliest feasible start |
| SJF | duration | earliest feasible start |
| Greedy (least-loaded) | release time | least committed normalised work $\sum p_i (c_i/C_m + q_i/Q_m)$ |
| Greedy-J (cost-aware) | release time | least increase of the objective $J$ |

FCFS, SJF and Greedy ignore cost, as the classic rules do. We added Greedy-J so that the comparison
also includes a heuristic that knows the objective, i.e. a myopic version of what CP-SAT optimises.

**Solvers.** OR-Tools CP-SAT 9.15 runs with 8 workers and a 10 s limit unless stated otherwise. It is
warm-started (`AddHint`) from the best baseline. The MILP uses Pyomo 6.10 with HiGHS 1.16.
The optimality gap is $(\text{obj} - \text{bound}) / \text{obj}$ from the solver.

**Validation.** An independent checker (`src/validate.py`) re-verifies **every schedule in every
experiment** with a plain per-slot loop that shares no code with the models. It checks: each task is
scheduled exactly once on a machine it fits; start $\ge r_i$; end $=$ start $+ p_i$; CPU and memory
within capacity in every slot. It also recomputes makespan, cost and tardiness and compares them with
the solver's reported values. Unit tests add further checks: a hand-solved 3-task instance;
single-machine identities; CP-SAT versus exhaustive brute force on 6 random 4-task instances; MILP
optimum = CP-SAT optimum; CP-SAT never worse than its warm start; same seed ⇒ same results.

**Data.** *Synthetic:* the generator is seeded. Demands are lognormal; durations are bimodal (≈75 %
short tasks around 4 slots, ≈25 % long jobs around 15 slots). Releases are spread over a window sized
so that bottleneck work / pool capacity equals the offered load $\rho$, and $d_i = r_i + \lceil\tau p_i\rceil$
(default $\rho = 1$, $\tau = 2$). *Real trace:* one part of the Google 2011 `task_events` table
(37 944 usable finished tasks). Runtime = FINISH − SCHEDULE, rounded up to minutes. CPU and memory
requests are scaled on the assumption that a large VM is 20 % of the trace's largest machine. Release
order and spacing are kept but rescaled to $\rho = 1$, deadlines are synthetic with $\tau = 2$, and
weights come from the trace priority tiers. The full list of conversion assumptions (A1–A6) is in
`src/trace.py`.

**Robustness protocol.** A plan is replayed as a *policy*: each task keeps its machine and its
position in that machine's start order, and starts as early as release, order and capacity allow under
the *actual* durations $\tilde p_i = \text{round}(p_i(1+\epsilon_i))$ with $\epsilon_i \sim U[-\delta,\delta]$.
All policies see the same random draws (common random numbers). We use 30 draws per δ and 5 instances.

## 4. Experiments

| # | Setting | Figure |
|---|---|---|
| E1 | 10 seeds × n ∈ {20, 50, 100} tasks (4, 6, 8 machines) | `e1_methods.png` |
| E2 | n = 10 … 100, 3 seeds, 10 s limit | `e2_scalability.png` |
| E3 | ρ ∈ {0.5, …, 1.5}, 40 tasks, 5 machines, 5 seeds | `e3_load.png` |
| E4 | ε-constraint front + 11-point weighted-sum sweep, 24 tasks, 5 machines, ρ = 2 | `e4_pareto.png` |
| E5 | time limits 1–60 s, warm vs cold start, 100 tasks, 8 machines, 2 seeds | `e5_anytime.png` |
| E6 | δ ∈ {0, 0.1, 0.2, 0.3}, 30 draws, 5 instances of 40 tasks | `e6_robustness.png` |
| E7 | 5 samples × 60 tasks from the Google trace, 6 VMs | `e7_trace.png` |
| E8 | MILP vs CP-SAT, n = 6 … 12, 3 machines; horizon scaling 1–4 × | `e8_milp_vs_cpsat.png` |

## 5. Results and analysis

### 5.1 Method comparison (E1, E7)

| n | best baseline J | CP-SAT J | improvement | CP-SAT cost vs Greedy | CP-SAT Cmax / LB |
|---|---|---|---|---|---|
| 20 | 0.640 ± 0.048 (Greedy-J) | **0.562 ± 0.036** | −12 % | −48 % | 1.008 |
| 50 | 0.686 ± 0.035 (Greedy-J) | **0.573 ± 0.024** | −16 % | −43 % | 1.000 |
| 100 | 0.698 ± 0.021 (FCFS) | **0.600 ± 0.028** | −14 % | −35 % | 1.009 |
| trace (60) | 0.709 ± 0.059 (Greedy-J) | **0.598 ± 0.020** | −16 % | −34 % | 1.000 |

CP-SAT has the strictly lowest objective on all 78 instances across E1, E2, E3 and E7, by at least 5 %. **Almost all of its advantage comes from cost, not
from makespan.** Its makespan is within 1 % of the lower bound, so it is essentially optimal, but FCFS
also reaches 1.00–1.04 × LB. CP-SAT consolidates work: CPU utilisation of the capacity actually leased
rises from 0.39–0.59 (baselines) to 0.70–0.76, and on the instance in
`usage_profile_greedy_vs_cpsat.png` it runs all 20 tasks on the one large VM, for about half of
greedy's cost and a shorter makespan. Its weighted tardiness stays low (3.1–4.9 slots). By contrast,
Greedy and Greedy-J degrade badly at n = 100 (131 and 182 slots, 18 and 30 late tasks): a myopic rule
that saves cost early pays for it in lateness later. Greedy-J recovers only 28–55 % of CP-SAT's cost saving over Greedy (less as n grows). The real-trace samples (E7) reproduce the synthetic picture.

### 5.2 Scalability (E2, E8)

CP-SAT proves optimality for every instance with ≤ 30 tasks, in under 0.25 s. At 50 tasks it proves
1/3 of instances within 10 s (median gap 4.5 %). At 75 and 100 tasks it proves none, and the gaps are
19 % and 23 %. **The gap overstates how far from optimal these solutions are.** Their makespans equal
the lower bound, and E5 shows that 6× more time improves the objective by under 2 %. What the solver
cannot do is *prove* a good bound on the cost term, which is a bin-packing-like problem.

On small instances the MILP and CP-SAT reach **identical optima on all 12 instances** (E8). CP-SAT is 9–28× faster, although both are below 0.5 s at this size. The structural difference shows in the
horizon study: on a fixed 8-task instance the MILP grows from 483 to 2 571 binaries as $H$ goes from
29 to 116 slots, and its time grows with it, while CP-SAT's model stays at 27 assignment Booleans.
This is why CP-SAT is the primary solver. A 100-task instance with the safe horizon (≈ 900 slots)
would need hundreds of thousands of MILP binaries.

### 5.3 Cost–makespan trade-off (E4)

The ε-constraint method, which minimises cost subject to $C_{\max} \le \varepsilon$ for every integer
ε, gives a front of **16 non-dominated schedules, all proven optimal**, from (makespan 23, cost 313) to
(40, 220). The marginal price of speed is steep near the fast end: going from 24 to 23 slots costs
+7, and from 28 to 25 slots costs +32 in total. The front is nearly flat between 28 and 36 slots
(cost 256 → 248). Cutting cost by 30 % therefore costs 74 % more makespan.

The weighted-sum sweep over 11 values of α recovers **only 4 of the 16 points** (makespan 23, 25, 28
and 40), because it can only find *supported* points on the convex hull. At α = 1, where cost has zero
weight, it returns a dominated schedule (23, 374). This is why we use ε-constraints for the front. All
four baselines are dominated by a wide margin. For example, Greedy-J's (27, 408) costs 47 % more than
the front point at the same makespan (27, 278).

### 5.4 Load sensitivity (E3)

The baselines' objective is 13–31 % above CP-SAT at **every** load level, and the gap does not grow
with ρ. This partly contradicts the expectation that greedy ≈ optimal at low load. For **makespan
alone** the expectation holds: at ρ = 0.5 FCFS and Greedy are within 1 % of CP-SAT (0.994 ×, i.e. a
fraction of a slot shorter, because CP-SAT accepts it in exchange for cost). As load rises, the
makespan gap widens modestly, to 6–10 % at ρ = 1.5 (20 % for SJF). The cost advantage, however, exists
whenever there is idle capacity to consolidate, and idle capacity is largest at *low* load. So:

* **When load is low, the optimiser saves money, not time.** If cost does not matter, a simple FCFS
  rule is close to optimal at no computational cost.
* **When load is high, the optimiser also saves time.** Constraints bind, and good packing starts to
  pay off on makespan as well.

Deadlines: CP-SAT is not the method with the fewest late tasks. SJF is (0.2–0.8 late tasks), because
it pushes short tasks first. CP-SAT accepts 2–3 slightly late tasks when that saves more cost than it
adds tardiness (weighted tardiness counts lateness in slots). This is the weighting doing its job, and
γ is the knob that changes it.

### 5.5 Anytime behaviour (E5)

On 100-task instances CP-SAT's incumbent is within 8.5 % of the best schedule found after 1 s, 2.8 %
after 5 s and 0.5 % after 30 s, and it already beats the best baseline (1.17×) after 1 s. The proven
gap, however, stays at 26–36 % throughout, which again shows that the bound, not the incumbent, is the
weak side. The warm start helps only at very short limits (1.085 vs 1.109 at 1 s). After that, CP-SAT's
own heuristics find better solutions than the baselines anyway. In practice, a 5–10 s limit captures
almost all of the benefit.

### 5.6 Robustness to duration errors (E6)

| δ | CP-SAT plan J | Greedy plan J | CP-SAT degradation | Greedy degradation |
|---|---|---|---|---|
| 0 | 0.579 | 0.774 | — | — |
| 0.1 | 0.601 | 0.774 | +3.9 % | 0.0 % |
| 0.2 | 0.628 | 0.781 | +8.6 % | +0.9 % |
| 0.3 | 0.661 | 0.804 | +14.3 % | +3.9 % |

The tightly packed optimal plan **is** more fragile. With ±30 % duration errors it loses 14 % of its
quality, against 4 % for greedy, and its weighted tardiness rises from 1.8 to 14 slots. The reason is
that a consolidated plan has no slack: when a task overruns, everything queued behind it on the same
machine slips. But even at δ = 0.3 the replayed CP-SAT plan is still **18 % better** than greedy. It
is also better than greedy re-run with perfect knowledge of the true durations. That clairvoyant
greedy does about as well as the replayed greedy plan (0.797 vs 0.804 at δ = 0.3, slightly worse at
smaller δ), so knowing the durations does not help a myopic rule. The advantage of optimising shrinks under uncertainty but
does not disappear in the tested range. A linear extrapolation of the trend suggests the two
would meet only well beyond ±30 %, which we have not tested.

## 6. Discussion

* **Does an optimiser always beat greedy?** On our objective, yes, on every instance and at every load,
  by 12–16 % in J. But the gain is almost entirely cost. On makespan alone FCFS is within 0–4 % of
  optimal, and on missed deadlines SJF is better. Whether the optimiser is "worth it" depends on
  whether cost matters to the operator.
* **When is it not worth it?** When only completion time matters and load is low (E3). Also for large
  instances when a proof of optimality is required: beyond about 50 tasks CP-SAT finds near-optimal
  schedules quickly but cannot certify them within seconds (E2, E5).
* **What if durations are wrong?** The optimised plan degrades about 4× faster than greedy but stays
  ahead up to ±30 %. A natural extension is to plan with padded durations or to keep slack on the
  machines, which would trade a little nominal cost for robustness.
* **Why CP-SAT over MILP?** Identical optima where both can be solved, a model size independent of the
  horizon, and native cumulative constraints (E8).
* **Why ε-constraint over weighted sums?** The weighted sum misses 12 of 16 Pareto-optimal schedules
  and can return dominated ones (E4).

**Limitations.** Deadlines are synthetic, including on the trace. The trace scaling of requests (A3)
and of release times (A4) is an assumption. Durations do not depend on the machine. CP-SAT results
under a wall-clock limit can vary slightly between machines. The MILP comparison only covers small
instances.

## 7. Conclusion

We formulated multi-objective cloud task scheduling as both a time-indexed MILP and an interval-based
CP-SAT model with a normalised, interpretable objective, and validated every schedule independently.
CP-SAT is optimal up to about 30 tasks and near-optimal up to 100 within seconds. It reduces the
combined objective by 12–16 % and cost by 35–48 % relative to classic rules while keeping makespan at
its lower bound, on synthetic workloads and on Google trace samples alike. The ε-constraint front
makes the cost of speed explicit. The robustness study shows that the optimised plan's advantage
shrinks, but survives, under realistic duration errors.
