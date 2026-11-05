"""Experiment definitions and a parallel runner.

Every job runs all requested policies on one shared trace (common random
numbers), so policy differences are paired by seed.
"""
import json
import os
import platform
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from .cluster import speed_spread
from .engine import simulate
from .metrics import summarize, timeseries
from .policies import MAIN_POLICIES
from .scenarios import get_scenario, main_scenarios
from .validation import cases

EVAL_SEEDS = list(range(20))
SWEEP_SEEDS = list(range(10))
DEV_SEEDS = list(range(1000, 1006))   # used only while designing ASED

ABLATION = {
    "ased": "ASED (full)",
    "ased:learn=0": "static speeds (no learning)",
    "ased:beta=0.0": "no error penalty",
    "ased:comp=0": "no concurrency compensation",
    "ased:d=2": "two-choice sampling",
    "ased:form=fcfs": "FCFS expected-delay form",
    "ased:qfb=1": "piggybacked queue instead of D*o",
}

DESIGN = {
    "ased:d=2,form=fcfs": "v1: two-choice, FCFS form",
    "ased:form=fcfs": "v2: full scan, FCFS form",
    "ased:d=2": "v3: two-choice, linear form",
    "ased:comp=0": "v4: full scan, linear, local count",
    "ased:qfb=1": "v5: full scan, linear, queue feedback",
    "ased": "v6: full scan, linear, D*o (final)",
    "lrt": "LRT (reference)",
    "lc": "LC (reference)",
}


def _run_group(job):
    sc, seed, specs, tags, keep = job
    trace = sc.trace(seed)
    rows, series = [], {}
    for spec in specs:
        res = simulate(sc, spec, seed, trace)
        row = dict(tags)
        row.update(scenario=sc.name, policy=spec, seed=seed, wall=res.wall, events=res.events)
        row.update(summarize(res, sc))
        rows.append(row)
        if keep:
            series[spec] = timeseries(res, sc)
    return sc.name, rows, series


def run_jobs(jobs, workers=None, label=""):
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    rows, series = [], {}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, (name, r, s) in enumerate(ex.map(_run_group, jobs, chunksize=1), 1):
            rows += r
            if s:
                series[name] = s
            if i % max(1, len(jobs) // 10) == 0 or i == len(jobs):
                print(f"  [{label}] {i}/{len(jobs)} groups, {time.time() - t0:.0f}s")
    return pd.DataFrame(rows), series


def main_jobs(seeds):
    return [(sc, s, MAIN_POLICIES, {}, s == seeds[0]) for sc in main_scenarios() for s in seeds]


def sensitivity_jobs(seeds):
    het = get_scenario("heterogeneous").with_(duration=80.0)
    hom = get_scenario("baseline").with_(duration=80.0)
    jobs = []

    def add(sweep, x, sc, specs=MAIN_POLICIES):
        sc = sc.with_(name=f"{sweep}={x}")
        jobs.extend((sc, s, specs, {"sweep": sweep, "x": x}, False) for s in seeds)

    for rho in (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95):
        add("load", rho, het.with_workload(load=rho))
    for d in (1, 2, 4, 8, 16):
        add("dispatchers", d, het.with_(dispatchers=d))
    for cv in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        add("cv", cv, het.with_workload(cv=cv))
    for ratio in (1, 2, 4, 8, 16):
        add("speed_ratio", ratio, het.with_(servers=speed_spread(ratio)))
    pod = ["p2c:d=1", "p2c:d=2", "p2c:d=3", "p2c:d=4", "p2c:d=6", "lc"]
    for rho in (0.7, 0.8, 0.9, 0.95):
        add("power_of_d", rho, hom.with_workload(load=rho), pod)
    return jobs


def ablation_jobs(seeds):
    return [(sc, s, list(ABLATION), {}, False) for sc in main_scenarios() for s in seeds]


def failure_jobs(seeds):
    base = get_scenario("server_crash")
    jobs = []
    for mode in ("refuse", "blackhole"):
        for od in (False, True):
            sc = base.with_(crash_mode=mode, outlier_detection=od,
                            name=f"crash_{mode}_{'od' if od else 'hc'}")
            tags = {"crash_mode": mode, "outlier_detection": od}
            jobs.extend((sc, s, MAIN_POLICIES, tags, False) for s in seeds)
    return jobs


def design_jobs(seeds):
    return [(sc, s, list(DESIGN), {}, False) for sc in main_scenarios() for s in seeds]


def _validation_job(args):
    idx, seed, duration = args
    sc, metric, expected = cases(duration)[idx]
    res = simulate(sc, "p2c:d=1", seed)
    return dict(case=sc.name, metric=metric, analytic=expected, seed=seed,
                value=summarize(res, sc)[metric])


def run_validation(out_dir, seeds=range(10), duration=40000.0, workers=None):
    n = len(cases(duration))
    jobs = [(i, s, duration) for i in range(n) for s in seeds]
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        df = pd.DataFrame(list(ex.map(_validation_job, jobs)))
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(os.path.join(out_dir, "validation_runs.csv"), index=False)
    return df


def write_meta(out_dir, name, seeds, df, seconds):
    meta = dict(
        experiment=name, seeds=list(seeds), runs=len(df), seconds=round(seconds, 1),
        python=sys.version.split()[0], numpy=np.__version__, pandas=pd.__version__,
        platform=platform.platform(), date=time.strftime("%Y-%m-%d %H:%M"),
    )
    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)


EXPERIMENTS = {
    "main": (main_jobs, EVAL_SEEDS),
    "sensitivity": (sensitivity_jobs, SWEEP_SEEDS),
    "ablation": (ablation_jobs, EVAL_SEEDS),
    "failure": (failure_jobs, EVAL_SEEDS),
    "design": (design_jobs, DEV_SEEDS),
}


def run_experiment(name, root="results", seeds=None, workers=None):
    out_dir = os.path.join(root, name)
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    if name == "validation":
        df = run_validation(out_dir, seeds=seeds or range(10), workers=workers)
        write_meta(out_dir, name, seeds or range(10), df, time.time() - t0)
        return df
    make, default_seeds = EXPERIMENTS[name]
    seeds = list(seeds if seeds is not None else default_seeds)
    df, series = run_jobs(make(seeds), workers, name)
    df.to_csv(os.path.join(out_dir, "runs.csv"), index=False)
    if series:
        with open(os.path.join(out_dir, "series_seed%d.json" % seeds[0]), "w") as f:
            json.dump(series, f, separators=(",", ":"))
    write_meta(out_dir, name, seeds, df, time.time() - t0)
    print(f"{name}: {len(df)} runs in {time.time() - t0:.0f}s -> {out_dir}")
    return df
