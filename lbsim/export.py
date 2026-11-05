"""Write the experiment results as demo/data.js for the local demo page."""
import json
import os
import time

import numpy as np
import pandas as pd

from .analysis import SCEN_LABELS, SCENARIOS
from .faults import Crash, Slowdown
from .plotstyle import COLORS, COLORS_DARK, DASHES
from .policies import FAMILIES, LABELS, MAIN_POLICIES
from .scenarios import main_scenarios
from .stats import summary

METRICS = ["mean", "p95", "p99", "error_rate", "throughput"]


def _r(x, k=8):
    x = float(x)
    return None if np.isnan(x) else round(x, k)


def _shade(sc):
    """Periods during which a fault or a spike is active."""
    out = []
    for f in sc.faults:
        n = len(f.servers)
        if isinstance(f, Crash):
            out.append([f.at, f.until or sc.duration, f"{n} servers down"])
        elif isinstance(f, Slowdown):
            out.append([f.at, f.until or sc.duration, f"{n} servers at {f.factor:.0%} speed"])
    for a, b, m in sc.workload.spikes:
        out.append([a, b, f"arrivals x{m:g}"])
    return out


def _series(v):
    p95 = [None if x is None or x != x else x for x in v["p95"]]
    err = [round(100.0 * e / a, 2) if a else 0.0 for e, a in zip(v["errors"], v["arrivals"])]
    return dict(p95=p95, err=err)


def export_demo(root="results", out_dir="demo"):
    main = pd.read_csv(os.path.join(root, "main", "runs.csv"))
    summ = summary(main, METRICS)
    with open(os.path.join(root, "main", "series_seed0.json")) as f:
        series = json.load(f)
    scen = main_scenarios()
    data = {
        "generated": time.strftime("%Y-%m-%d"),
        "seeds": int(main.seed.nunique()),
        "warmup": scen[0].warmup,
        "duration": scen[0].duration,
        "policies": [dict(id=p, label=LABELS[p], family=FAMILIES[p], color=COLORS[p],
                          dark=COLORS_DARK[p], dash=list(DASHES.get(p, ())))
                     for p in MAIN_POLICIES],
        "scenarios": [dict(id=s.name, label=SCEN_LABELS[s.name], about=s.title, shade=_shade(s))
                      for s in scen],
        "summary": {s: {p: {m: [_r(r[m]), _r(r[m + "_ci"])] for m in METRICS}
                        for p, r in summ[summ.scenario == s].set_index("policy").iterrows()}
                    for s in SCENARIOS},
        "series": {s: {p: _series(series[s][p]) for p in MAIN_POLICIES} for s in SCENARIOS},
    }
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "data.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write("window.LB_DATA = ")
        json.dump(data, f, separators=(",", ":"))
        f.write(";\n")
    print(f"demo data -> {path} ({os.path.getsize(path) / 1024:.0f} KB)")
    return path
