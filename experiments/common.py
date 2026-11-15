"""Shared harness: run every method on one instance, validate, return metric rows."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from src import cpsat_model as cp
from src.baselines import BASELINES
from src.instance import Instance, Schedule
from src.metrics import Refs, Weights, evaluate, make_refs, objective
from src.validate import assert_valid

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
DATA = ROOT / "data"
WEIGHTS = Weights()  # (0.4, 0.3, 0.3), see src/metrics.py


def parser(desc: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--quick", action="store_true", help="small configuration for a fast smoke run")
    ap.add_argument("--time-limit", type=float, default=None, help="CP-SAT time limit per solve [s]")
    ap.add_argument("--workers", type=int, default=8, help="CP-SAT search workers")
    return ap


def run_methods(inst: Instance, time_limit: float, workers: int = 8, w: Weights = WEIGHTS,
                save_dir: Path | None = None) -> tuple[list[dict], dict[str, Schedule], Refs]:
    """FCFS, SJF, Greedy and CP-SAT (warm-started from the best baseline) on the same instance.

    Every schedule is validated; a violation raises immediately.
    """
    scheds: dict[str, Schedule] = {}
    for name, f in BASELINES.items():
        t0 = time.perf_counter()
        s = f(inst)
        s.info["solve_time"] = time.perf_counter() - t0
        scheds[name] = s
    refs = make_refs(inst, scheds["Greedy"])
    best = min((scheds[k] for k in BASELINES), key=lambda s: objective(inst, s, w, refs))
    s = cp.solve(inst, w, refs, cp.CpSatOptions(time_limit=time_limit, workers=workers, hint=best))
    if s is None:
        raise RuntimeError(f"CP-SAT found no solution on {inst.name}")
    s.info["hint_from"] = best.method
    scheds["CP-SAT"] = s

    rows = []
    for name, s in scheds.items():
        assert_valid(inst, s, s.info.get("reported"))
        row = evaluate(inst, s, w, refs)
        row.update({k: inst.meta.get(k) for k in ("seed", "rho", "tau")})
        rows.append(row)
        if save_dir is not None:
            s.save_csv(save_dir / f"{inst.name}__{name}.csv")
    return rows, scheds, refs


def save(df: pd.DataFrame, name: str) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    df.to_csv(path, index=False)
    print(f"wrote {path.relative_to(ROOT)} ({len(df)} rows)")
    return path


def summary(df: pd.DataFrame, by: list[str], cols: list[str]) -> pd.DataFrame:
    """mean ± std table, for printing and for the report."""
    g = df.groupby(by, sort=False)[cols]
    m, s = g.mean(), g.std().fillna(0)
    out = m.copy().astype(object)
    for c in cols:
        out[c] = [f"{a:.3f} ± {b:.3f}" for a, b in zip(m[c], s[c])]
    return out.reset_index()


def write_table(df: pd.DataFrame, name: str) -> None:
    path = RESULTS / "tables" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [str(c) for c in df.columns]
    fmt = lambda v: f"{v:.3f}" if isinstance(v, float) else str(v)  # noqa: E731
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    path.write_text("\n".join(lines) + "\n")
    print(f"wrote {path.relative_to(ROOT)}")
