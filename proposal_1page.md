# Multi-Objective Cloud Task Scheduling Under CPU, Memory, and Deadline Constraints

*Project topic: Cloud Computing Resource Allocation and Task Scheduling*

**Team:** `<TEAM NAME>` — `<Member 1>`, `<Member 2>`, `<Member 3>`

**Problem and motivation.** A cloud platform receives batches of tasks, each with a CPU demand, a memory
demand, a duration, a release time and a deadline. It runs them on a small pool of heterogeneous
virtual machines that differ in capacity and price. The operator has to decide which task runs on
which machine and when. Finishing early, spending little, and meeting deadlines pull in different
directions: packing work onto fewer, cheaper machines saves money but delays completion. We study this
trade-off quantitatively, and we ask when an exact optimiser is actually worth it compared with the
simple rules used in practice.

**Scope.** Offline, deterministic batch scheduling: 10–100 tasks, 3–10 machines, integer time slots
(1 slot = 1 min), no preemption. Online arrivals and rescheduling are out of scope.

**Formulation.** Binary x[i,m,t] = 1 if task i starts on machine m at slot t; y_m = 1 if machine m is
used; completion C_i, tardiness T_i, makespan Cmax, machine lease end E_m.

```
minimise  α · Cmax / LB  +  β · Σ_m (F_m·y_m + k_m·E_m) / Cost_greedy  +  γ · Σ_i w_i·T_i / Σ_i p_i
```

subject to: each task starts exactly once, at or after its release time; at every slot the running CPU
and memory on each machine stay within its capacity; C_i = Σ (t + p_i) · x[i,m,t];
T_i ≥ C_i − d_i, T_i ≥ 0 (soft deadlines); Cmax ≥ C_i; E_m ≥ the end of every task on m. Each
objective term is normalised to a dimensionless quantity (makespan relative to a provable lower bound,
cost relative to a greedy schedule, and the fraction of work-time that is late), so the weights are
genuine relative importances.

**Method and solvers.** The primary optimiser is Google OR-Tools **CP-SAT**, using optional interval
variables and cumulative constraints, with a time limit and the reported optimality gap. Its model size
does not depend on the horizon. For comparison, the time-indexed **MILP** above is solved with
Pyomo + HiGHS on small instances, where its size grows linearly with the horizon. Baselines: First Come
First Served, Shortest Job First, Greedy least-loaded, and a cost-aware greedy. An independent checker
validates every schedule.

**Data.** Seeded synthetic workloads with an offered-load knob ρ and a deadline-tightness knob
τ. Results are then validated on samples of the public **Google 2011 cluster trace** (CPU/memory
requests and observed runtimes from one `task_events` part). Conversion assumptions are documented.

**Planned experiments.** (1) Method comparison on identical instances. (2) Solve time and gap versus
task count. (3) Deadline violations and utilisation as load increases. (4) The cost–makespan Pareto front
via the ε-constraint method, contrasted with a weighted-sum sweep. (5) Gap versus time limit.
(6) Robustness to ±10–30 % errors in duration estimates. (7) Real-trace samples. (8) MILP versus CP-SAT.

**Questions for the analysis.** Does optimisation always beat greedy, and does the answer change with
load? When do deadlines become infeasible? Does a tightly optimised plan stay good when durations are
wrong?
