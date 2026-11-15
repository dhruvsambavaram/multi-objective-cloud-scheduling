"""Read results/*.csv and write results/figures/*.png.

Colour rules: one fixed colour per method in every figure (validated, colour-blind
safe on adjacent pairs), markers as a second cue, recessive grid, single y-axis
per panel. Every figure's data is also in results/*.csv and results/tables/*.md.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from experiments.common import DATA, RESULTS  # noqa: E402

FIG = RESULTS / "figures"
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
METHODS = ["FCFS", "SJF", "Greedy", "Greedy-J", "CP-SAT"]
# Validated in this adjacency order (scripts/validate_palette.js, light surface): all checks pass.
COLOR = {"FCFS": "#eb6834", "SJF": "#1baf7a", "Greedy": "#eda100", "Greedy-J": "#e87ba4", "CP-SAT": "#2a78d6"}
MARKER = {"FCFS": "D", "SJF": "^", "Greedy": "s", "Greedy-J": "v", "CP-SAT": "o"}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "sans-serif", "font.size": 10, "text.color": INK, "axes.labelcolor": INK2,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": AXIS,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "lines.linewidth": 2, "lines.markersize": 7,
    "legend.frameon": False, "legend.fontsize": 9, "figure.dpi": 110, "savefig.dpi": 180,
})


def _save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / name, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote results/figures/{name}")


def _read(name):
    p = RESULTS / name
    return pd.read_csv(p) if p.exists() else None


def grouped_bars(ax, df, group, metric, groups, label_fmt=None):
    """Bars per method within each group, mean +/- std error bars."""
    k = len(METHODS)
    width = 0.8 / k
    x = np.arange(len(groups))
    for j, m in enumerate(METHODS):
        sub = df[df.method == m].groupby(group)[metric]
        mean = sub.mean().reindex(groups).to_numpy()
        std = sub.std().reindex(groups).fillna(0).to_numpy()
        pos = x - 0.4 + width * (j + 0.5)
        ax.bar(pos, mean, width * 0.92, color=COLOR[m], label=m, edgecolor=SURFACE, linewidth=1)
        lower = np.minimum(std, mean - min(0, np.nanmin(mean)))  # metrics here are >= 0: don't draw below 0
        ax.errorbar(pos, mean, yerr=[lower, std], fmt="none", ecolor=INK2, elinewidth=1, capsize=2)
        if label_fmt and m == "CP-SAT":
            for xx, v, e in zip(pos, mean, std):
                ax.annotate(label_fmt.format(v), (xx, v + e), xytext=(0, 3), textcoords="offset points",
                            ha="center", va="bottom", fontsize=8, color=INK2)
    ax.set_xticks(x, [str(g) for g in groups])


def method_legend(fig, methods=METHODS, lines=False):
    if lines:
        handles = [plt.Line2D([], [], color=COLOR[m], marker=MARKER[m]) for m in methods]
    else:
        handles = [plt.Rectangle((0, 0), 1, 1, color=COLOR[m]) for m in methods]
    fig.legend(handles, methods, loc="upper center", ncol=len(methods), bbox_to_anchor=(0.5, 1.02))


# ----------------------------------------------------------------------- E1
def plot_e1(df, name="e1_methods.png", group="n_tasks", xlabel="Number of tasks", title=None):
    groups = sorted(df[group].unique())
    panels = [("objective", "Normalised objective J (lower is better)", "{:.2f}"),
              ("makespan_over_lb", "Makespan / lower bound", "{:.2f}"),
              ("cost", "Cost (lease + activation)", "{:.0f}"),
              ("weighted_tardiness", "Weighted tardiness [slots]", None)]
    fig, axs = plt.subplots(2, 2, figsize=(10, 6.5))
    for ax, (metric, ttl, fmt) in zip(axs.flat, panels):
        grouped_bars(ax, df, group, metric, groups, fmt)
        ax.set_title(ttl, loc="left")
        ax.set_xlabel(xlabel)
    axs[0, 1].set_ylim(bottom=0.9)
    method_legend(fig)
    if title:
        fig.suptitle(title, y=1.07, fontweight="bold")
    fig.tight_layout()
    _save(fig, name)


# ----------------------------------------------------------------------- E2
def plot_e2(df):
    c = df[df.method == "CP-SAT"]
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
    g = c.groupby("n_tasks")
    for ax, col, ttl in ((axs[0], "solve_time", "CP-SAT solve time [s]"), (axs[1], "gap", "CP-SAT optimality gap at the time limit")):
        vals = c[col] * (100 if col == "gap" else 1)
        ax.scatter(c.n_tasks, vals, color=COLOR["CP-SAT"], alpha=0.35, s=22, linewidths=0)
        med = g[col].median() * (100 if col == "gap" else 1)
        ax.plot(med.index, med.values, color=COLOR["CP-SAT"], marker="o")
        ax.set_title(ttl + (" [%]" if col == "gap" else ""), loc="left")
        ax.set_xlabel("Number of tasks (machines = n/10, between 3 and 10)")
    tl = c.time_limit.iloc[0]
    axs[0].axhline(tl, color=MUTED, linewidth=1, linestyle="--")
    axs[0].annotate(f"time limit {tl:g}s", (c.n_tasks.min(), tl), xytext=(0, 4), textcoords="offset points", color=INK2, fontsize=8)
    axs[0].set_yscale("log")
    opt = g.status.apply(lambda s: (s == "OPTIMAL").mean())
    med_gap = g["gap"].median() * 100
    all_opt = [n for n, f in opt.items() if f == 1.0]
    if all_opt:  # one label for the run of fully-solved sizes instead of a label per point
        axs[1].annotate(f"n ≤ {max(all_opt)}: all solved to optimality", (min(all_opt), 0), xytext=(0, 10),
                        textcoords="offset points", fontsize=8, color=INK2)
    for n, frac in opt.items():
        if frac < 1.0:
            axs[1].annotate(f"{frac:.0%} optimal", (n, med_gap[n]), xytext=(-6, 8), textcoords="offset points",
                            ha="right", fontsize=8, color=INK2)
    fig.tight_layout()
    _save(fig, "e2_scalability.png")


# ----------------------------------------------------------------------- E3
def plot_e3(df):
    panels = [("objective_vs_cpsat", "Objective relative to CP-SAT"), ("makespan_vs_cpsat", "Makespan relative to CP-SAT"),
              ("n_late", "Late tasks (of 40)"), ("leased_util_cpu", "CPU utilisation of leased capacity")]
    fig, axs = plt.subplots(2, 2, figsize=(10, 6.5))
    for ax, (col, ttl) in zip(axs.flat, panels):
        g = df.groupby(["method", "rho"])[col]
        for m in METHODS:
            mean, std = g.mean()[m], g.std()[m].fillna(0)
            ax.plot(mean.index, mean.values, color=COLOR[m], marker=MARKER[m], label=m)
            ax.fill_between(mean.index, mean - std, mean + std, color=COLOR[m], alpha=0.10, linewidth=0)
        ax.set_title(ttl, loc="left")
        ax.set_xlabel("Offered load ρ")
    method_legend(fig, lines=True)
    fig.tight_layout()
    _save(fig, "e3_load.png")


# ----------------------------------------------------------------------- E4
def plot_e4(df):
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    front = df[df.on_front].sort_values("makespan")
    ax.step(front.makespan, front.cost, where="post", color=COLOR["CP-SAT"], linewidth=2, zorder=2)
    ax.scatter(front.makespan, front.cost, color=COLOR["CP-SAT"], s=55, zorder=3, edgecolor=SURFACE, linewidth=1.5,
               label="ε-constraint front (CP-SAT)")
    ws = df[df.kind == "weighted_sum"]
    ax.scatter(ws.makespan, ws.cost, facecolor="none", edgecolor=INK2, s=110, linewidth=1.3, zorder=4,
               label="weighted-sum sweep (α = 0…1)")
    for m in ("FCFS", "SJF", "Greedy", "Greedy-J"):
        r = df[df.kind == m]
        ax.scatter(r.makespan, r.cost, color=COLOR[m], marker=MARKER[m], s=70, zorder=5, edgecolor=SURFACE, linewidth=1.5, label=m)
        ax.annotate(m, (r.makespan.iloc[0], r.cost.iloc[0]), xytext=(7, -3), textcoords="offset points", fontsize=9, color=INK2)
    ax.set_xlabel("Makespan [slots]")
    ax.set_ylabel("Cost")
    ax.set_title("Cost vs makespan trade-off (" + df.instance.iloc[0] + ")", loc="left")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.legend(loc="upper right")
    fig.tight_layout()
    _save(fig, "e4_pareto.png")


# ----------------------------------------------------------------------- E5
def plot_e5(df):
    df = df.dropna(subset=["objective"])
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
    for warm, ls, mk, lab in ((True, "-", "o", "warm start (best baseline)"), (False, "--", "s", "cold start")):
        g = df[df.warm_start == warm].groupby("time_limit")
        axs[0].plot(g.objective_vs_best_found.mean(), color=COLOR["CP-SAT"], linestyle=ls, marker=mk, label=lab)
        axs[1].plot(g.gap.mean() * 100, color=COLOR["CP-SAT"], linestyle=ls, marker=mk, label=lab)
    base = (df.best_baseline_objective / df.groupby("instance").objective.transform("min")).mean()
    axs[0].axhline(base, color=COLOR["Greedy"], linewidth=1.5, linestyle=":")
    axs[0].annotate("best baseline", (df.time_limit.min(), base), xytext=(0, -12), textcoords="offset points", fontsize=8, color=INK2)
    axs[0].set_title("Objective / best found", loc="left")
    axs[1].set_title("Optimality gap [%]", loc="left")
    for ax in axs:
        ax.set_xscale("log")
        ax.set_xticks(sorted(df.time_limit.unique()), [f"{t:g}" for t in sorted(df.time_limit.unique())])
        ax.set_xlabel("Time limit [s]")
    axs[1].legend()
    fig.tight_layout()
    _save(fig, "e5_anytime.png")


# ----------------------------------------------------------------------- E6
E6_STYLE = {"CP-SAT plan (replayed)": (COLOR["CP-SAT"], "-", "o"),
            "Greedy plan (replayed)": (COLOR["Greedy"], "-", "s"),
            "Greedy re-run (clairvoyant)": ("#1baf7a", "--", "^")}


def plot_e6(df):
    panels = [("objective", "Normalised objective J"), ("makespan", "Makespan [slots]"),
              ("weighted_tardiness", "Weighted tardiness [slots]"), ("objective_degradation", "Objective vs own nominal plan [%]")]
    fig, axs = plt.subplots(2, 2, figsize=(10, 6.5))
    for ax, (col, ttl) in zip(axs.flat, panels):
        for pol, (c, ls, mk) in E6_STYLE.items():
            g = df[df.policy == pol].groupby("delta")[col]
            mean, std = g.mean(), g.std().fillna(0)
            k = 100 if col == "objective_degradation" else 1
            ax.plot(mean.index, mean * k, color=c, linestyle=ls, marker=mk, label=pol)
            ax.fill_between(mean.index, (mean - std) * k, (mean + std) * k, color=c, alpha=0.10, linewidth=0)
        ax.set_title(ttl, loc="left")
        ax.set_xlabel("Duration noise δ  (p̃ = p·(1+U[−δ, δ]))")
        ax.set_xticks([0, 0.1, 0.2, 0.3])
    handles = [plt.Line2D([], [], color=c, linestyle=ls, marker=mk) for c, ls, mk in E6_STYLE.values()]
    fig.legend(handles, list(E6_STYLE), loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout()
    _save(fig, "e6_robustness.png")


# ----------------------------------------------------------------------- E8
def plot_e8(df):
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
    styles = {"MILP (HiGHS)": (COLOR["Greedy"], "s"), "CP-SAT": (COLOR["CP-SAT"], "o")}
    A, B = df[df.part == "A"], df[df.part == "B"]
    for sv, (c, mk) in styles.items():
        g = A[A.solver == sv].groupby("n_tasks").solve_time.mean()
        axs[0].plot(g.index, g.values, color=c, marker=mk, label=sv)
        b = B[B.solver == sv].sort_values("H")
        axs[1].plot(b.H, b.n_binaries, color=c, marker=mk, label=sv)
    axs[0].set_yscale("log")
    axs[0].set_title("Solve time to optimality [s]", loc="left")
    axs[0].set_xlabel("Number of tasks (3 machines, H = greedy makespan)")
    axs[1].set_title("Boolean variables vs horizon H", loc="left")
    axs[1].set_xlabel("Horizon H [slots]  (8 tasks, 3 machines)")
    axs[0].legend()
    fig.tight_layout()
    _save(fig, "e8_milp_vs_cpsat.png")


# ----------------------------------------------------------------------- Gantt / usage profile
def plot_usage():
    """CPU usage per machine over time: Greedy vs CP-SAT on one E1 instance."""
    from src.instance import Instance

    name = "syn_n20_m4_rho1.0_tau2.0_s0"
    ipath = DATA / "synthetic" / f"{name}.json"
    paths = {m: RESULTS / "schedules" / "e1" / f"{name}__{m}.csv" for m in ("Greedy", "CP-SAT")}
    if not ipath.exists() or not all(p.exists() for p in paths.values()):
        return
    inst = Instance.load(ipath)
    scheds = {m: pd.read_csv(p) for m, p in paths.items()}
    H = max(s.end.max() for s in scheds.values())
    fig, axs = plt.subplots(inst.m, 2, figsize=(10, 1.15 * inst.m + 0.8), sharex=True, sharey=True, squeeze=False)
    for j, (meth, s) in enumerate(scheds.items()):
        for mc in inst.machines:
            ax = axs[mc.id, j]
            use = np.zeros(H)
            for r in s[s.machine == mc.id].itertuples():
                use[r.start:r.end] += inst.tasks[r.task].cpu
            ax.fill_between(np.arange(H + 1), np.append(use, use[-1]) / mc.cpu * 100, step="post",
                            color=COLOR[meth], alpha=0.85, linewidth=0)
            ax.set_ylim(0, 105)
            ax.set_yticks([0, 100], ["0", "100%"])
            if j == 0:
                ax.set_ylabel(f"M{mc.id} {mc.kind}", rotation=0, ha="right", va="center", fontsize=9)
            if mc.id == 0:
                cost = sum(m.fixed * (m.id in set(s.machine)) + m.price * s[s.machine == m.id].end.max()
                           if m.id in set(s.machine) else 0 for m in inst.machines)
                ax.set_title(f"{meth}: makespan {s.end.max()}, cost {cost}", loc="left")
        axs[-1, j].set_xlabel("Time [slots]")
    fig.suptitle("CPU usage per machine (" + name + ")", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    _save(fig, "usage_profile_greedy_vs_cpsat.png")


def main():
    for fname, fn in (("e1_methods.csv", plot_e1), ("e2_scalability.csv", plot_e2), ("e3_load.csv", plot_e3),
                      ("e4_pareto.csv", plot_e4), ("e5_anytime.csv", plot_e5), ("e6_robustness.csv", plot_e6),
                      ("e8_milp.csv", plot_e8)):
        df = _read(fname)
        if df is not None:
            fn(df)
    df = _read("e7_trace.csv")
    if df is not None:
        df["sample"] = "Google 2011 samples (60 tasks, 6 VMs)"
        plot_e1(df, "e7_trace.png", group="sample", xlabel="")
    plot_usage()


if __name__ == "__main__":
    main()
