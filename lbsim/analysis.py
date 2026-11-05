"""Tables, statistical tests and figures from the experiment CSVs."""
import json
import os

import numpy as np
import pandas as pd

from . import plotstyle as ps
from .policies import LABELS, MAIN_POLICIES
from .stats import friedman_ranks, mean_ci, nemenyi_cd, pairwise, summary

plt = ps.plt

SCEN_LABELS = {
    "baseline": "Baseline (homogeneous)",
    "heterogeneous": "Heterogeneous",
    "bursty": "Bursty + heavy tail",
    "flash_crowd": "Flash crowd",
    "server_crash": "Server crash",
    "gray_failure": "Gray failure",
}
SCENARIOS = list(SCEN_LABELS)
METRICS = ["mean", "p50", "p95", "p99", "p999", "error_rate", "throughput", "slo_attain",
           "util_mean", "util_max", "util_jain", "util_cv", "queue_mean", "degraded_s"]


def _load(root, name):
    p = os.path.join(root, name, "runs.csv")
    return pd.read_csv(p) if os.path.exists(p) else None


def _save(fig, root, name):
    os.makedirs(os.path.join(root, "figures"), exist_ok=True)
    fig.savefig(os.path.join(root, "figures", name + ".png"))
    plt.close(fig)


def _md_table(df, floatfmt=None):
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |",
             "|" + "|".join("---" if i == 0 else "---:" for i in range(len(cols))) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines) + "\n"


def _write(root, name, text):
    os.makedirs(os.path.join(root, "tables"), exist_ok=True)
    with open(os.path.join(root, "tables", name), "w", encoding="utf-8") as f:
        f.write(text)


# ---- main comparison ----------------------------------------------------------

def metric_table(summ, metric, scale=1000.0, digits=0, lower=True, ci=True):
    """Policies x scenarios with mean (+- CI); best value in bold."""
    rows = []
    for p in MAIN_POLICIES:
        row = {"Policy": LABELS[p]}
        for s in SCENARIOS:
            g = summ[(summ.scenario == s)]
            v = g.loc[g.policy == p, metric].values
            h = g.loc[g.policy == p, metric + "_ci"].values
            if not len(v):
                row[SCEN_LABELS[s]] = "-"
                continue
            best = g[metric].min() if lower else g[metric].max()
            txt = f"{v[0] * scale:.{digits}f}"
            if ci and h[0] == h[0]:
                txt += f" ± {h[0] * scale:.{digits}f}"
            if np.isclose(v[0], best):
                txt = f"**{txt}**"
            row[SCEN_LABELS[s]] = txt
        rows.append(row)
    return pd.DataFrame(rows)


def main_tables(df, root):
    summ = summary(df, METRICS)
    ev_cols = [c for c in df.columns if c.split("_")[0] in ("spike", "failure", "rejoin", "slowdown", "restore")]
    ev = summary(df, ev_cols) if ev_cols else None
    os.makedirs(os.path.join(root, "tables"), exist_ok=True)
    summ.to_csv(os.path.join(root, "tables", "main_summary.csv"), index=False)
    if ev is not None:
        ev.to_csv(os.path.join(root, "tables", "main_events.csv"), index=False)
    _write(root, "main_p99.md", _md_table(metric_table(summ, "p99")))
    _write(root, "main_mean.md", _md_table(metric_table(summ, "mean", digits=1)))
    _write(root, "main_errors.md", _md_table(metric_table(summ, "error_rate", scale=100, digits=2)))
    _write(root, "main_jain.md", _md_table(metric_table(summ, "util_jain", scale=1, digits=3, lower=False)))
    _write(root, "main_slo.md", _md_table(metric_table(summ, "slo_attain", scale=100, digits=2, lower=False)))

    pw = pairwise(df, "ased", ["mean", "p99", "error_rate"])
    pw.to_csv(os.path.join(root, "tables", "pairwise_ased.csv"), index=False)
    rows = []
    for s in SCENARIOS:
        for p in MAIN_POLICIES:
            if p == "ased":
                continue
            r = pw[(pw.group == s) & (pw.policy == p)].set_index("metric")
            if r.empty:
                continue
            p99, mean, err = r.loc["p99"], r.loc["mean"], r.loc["error_rate"]
            rows.append({
                "Scenario": SCEN_LABELS[s], "vs": LABELS[p],
                "P99 ratio": f"{p99.ratio:.2f} [{p99.ratio_lo:.2f}, {p99.ratio_hi:.2f}]",
                "p (Holm)": _pfmt(p99.p_holm), "ASED wins": f"{int(round(p99.ref_wins * p99.n))}/{p99.n}",
                "Mean ratio": f"{mean.ratio:.2f}", "p (Holm) ": _pfmt(mean.p_holm),
                "Error diff (pp)": f"{err['diff'] * 100:+.2f}",
            })
    _write(root, "pairwise_ased.md", _md_table(pd.DataFrame(rows)))

    lines = []
    rank_rows = []
    for metric in ("p99", "mean"):
        sub = df[df.policy.isin(MAIN_POLICIES)]
        ranks, stat, p, n = friedman_ranks(sub, metric)
        cd = nemenyi_cd(len(ranks), n)
        lines.append(f"{metric}: Friedman chi2={stat:.1f}, p={p:.2e}, blocks={n}, "
                     f"k={len(ranks)}, Nemenyi CD={cd:.2f}")
        for s in SCENARIOS:
            r, *_ = friedman_ranks(sub[sub.scenario == s], metric, block=("seed",))
            for pol, v in r.items():
                rank_rows.append(dict(metric=metric, scenario=s, policy=pol, rank=v))
        for pol, v in ranks.items():
            rank_rows.append(dict(metric=metric, scenario="all", policy=pol, rank=v))
    pd.DataFrame(rank_rows).to_csv(os.path.join(root, "tables", "ranks.csv"), index=False)
    _write(root, "friedman.txt", "\n".join(lines) + "\n")
    return summ, pw


def _pfmt(p):
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def fig_main_bars(summ, root, metric="p99", fname="fig_main_p99", title="P99 response time (ms)"):
    fig, axes = plt.subplots(2, 3, figsize=(11, 6.4))
    for ax, s in zip(axes.flat, SCENARIOS):
        g = summ[summ.scenario == s].set_index("policy").loc[MAIN_POLICIES]
        vals = (g[metric] * 1000).values
        errs = (g[metric + "_ci"] * 1000).values
        cols = [ps.ACCENT if p == "ased" else ps.DEEMPH for p in MAIN_POLICIES]
        ps.hbars(ax, [LABELS[p] for p in MAIN_POLICIES], vals, cols, errs)
        ax.set_title(SCEN_LABELS[s])
        ax.tick_params(axis="y", labelsize=8)
        ax.tick_params(axis="x", labelsize=7.5)
    fig.suptitle(f"{title}: mean over 20 seeds, whiskers = 95% CI",
                 x=0.01, ha="left", fontsize=10, color=ps.INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    _save(fig, root, fname)


def fig_cd(df, root, metric="p99"):
    ranks, stat, p, n = friedman_ranks(df[df.policy.isin(MAIN_POLICIES)], metric)
    k = len(ranks)
    cd = nemenyi_cd(k, n)
    names = [LABELS[x] for x in ranks.index]
    vals = ranks.values
    half = (k + 1) // 2
    y0 = 0.82
    bottom = y0 - 0.20 - 0.11 * (half - 1)
    fig, ax = plt.subplots(figsize=(8.6, 3.0 * (1.04 - bottom)))
    ax.set_xlim(0.5, k + 0.5)
    ax.set_ylim(bottom, 1.04)
    ax.axis("off")
    ax.plot([1, k], [y0, y0], color=ps.INK2, lw=1)
    for r in range(1, k + 1):
        ax.plot([r, r], [y0, y0 + 0.03], color=ps.INK2, lw=1)
        ax.text(r, y0 + 0.06, str(r), ha="center", va="bottom", fontsize=8, color=ps.INK2)
    ax.plot([1, 1 + cd], [1.0, 1.0], color=ps.INK, lw=1.4, clip_on=False)
    ax.text(1 + cd + 0.08, 1.0, f"critical difference = {cd:.2f}", ha="left", va="center",
            fontsize=7.5, color=ps.INK2)
    for idx, (nm, v) in enumerate(zip(names, vals)):
        left = idx < half
        yy = y0 - 0.12 - 0.11 * (idx if left else k - 1 - idx)
        xe = 0.6 if left else k + 0.4
        col = ps.ACCENT if nm == "ASED" else ps.INK2
        ax.plot([v, v, xe], [y0, yy, yy], color=col, lw=0.9)
        ax.text(xe + (-0.05 if left else 0.05), yy, f"{nm} ({v:.2f})", ha="right" if left else "left",
                va="center", fontsize=8, color=ps.INK if nm == "ASED" else ps.INK2,
                fontweight="semibold" if nm == "ASED" else "normal")
    cliques, last_end = [], -1
    for i in range(k):
        j = i
        while j + 1 < k and vals[j + 1] - vals[i] < cd:
            j += 1
        if j > i and j > last_end:
            cliques.append((vals[i], vals[j]))
            last_end = j
    for c, (a, b) in enumerate(cliques):
        yy = y0 - 0.05 - 0.035 * c
        ax.plot([a - 0.03, b + 0.03], [yy, yy], color=ps.INK, lw=2.4, solid_capstyle="round")
    fig.suptitle(f"Mean rank on P99 over {n} scenario-seed blocks (1 = best). Friedman p = {p:.1e}; "
                 f"thick bars join policies the Nemenyi test cannot separate",
                 x=0.01, ha="left", fontsize=8.5, color=ps.INK2)
    _save(fig, root, "fig_cd_p99")


def fig_timeseries(series, root):
    pols = MAIN_POLICIES
    panels = [("server_crash", "Server crash: 2 servers fail at 50 s, rejoin cold at 90 s",
               [(50, 90, "down")]),
              ("gray_failure", "Gray failure: 3 servers at 30% speed from 50 s to 90 s",
               [(50, 90, "slowed")]),
              ("flash_crowd", "Flash crowd: arrival rate x1.75 from 60 s to 70 s",
               [(60, 70, "spike")])]
    fig, axes = plt.subplots(len(panels), 2, figsize=(11, 8.2), gridspec_kw={"width_ratios": [3, 1.3]})
    for row, (sc, title, shades) in enumerate(panels):
        ax, axe = axes[row]
        if sc not in series:
            continue
        for a, b, _ in shades:
            for x in (ax, axe):
                x.axvspan(a, b, color="#efeee9", zorder=0, lw=0)
        for p in pols:
            s = series[sc][p]
            t = np.array(s["t"]) + 0.5
            y = np.array(s["p95"], dtype=float)
            ls = (0, ps.DASHES[p]) if p in ps.DASHES else "-"
            ax.plot(t, y, color=ps.COLORS[p], lw=1.3 if p != "ased" else 1.9, ls=ls,
                    label=LABELS[p], zorder=3 if p == "ased" else 2)
            err = np.array(s["errors"]) / np.maximum(np.array(s["arrivals"]), 1) * 100
            axe.plot(t, err, color=ps.COLORS[p], lw=1.2 if p != "ased" else 1.8, ls=ls)
        ax.set_yscale("log")
        ax.set_ylim(40, 5000)
        ps.plain_log(ax.yaxis)
        ax.set_xlim(20, 120)
        axe.set_xlim(20, 120)
        ax.axhline(500, color=ps.MUTED, lw=0.8, ls=(0, (1, 2)))
        ax.text(21, 520, "SLO 500 ms", fontsize=7, color=ps.MUTED, va="bottom")
        ax.set_title(title)
        ax.set_ylabel("P95 per 1-s window (ms)")
        axe.set_ylabel("errors (% of window)")
        axe.set_ylim(-1, 100)
        axe.set_title("Error rate")
        if row == len(panels) - 1:
            ax.set_xlabel("time (s)")
            axe.set_xlabel("time (s)")
    axes[0][0].legend(ncol=6, loc="upper left", bbox_to_anchor=(0, 1.32), fontsize=8, handlelength=2.4)
    fig.tight_layout()
    _save(fig, root, "fig_timeseries")


def fig_util_heatmap(series, root, scenario="heterogeneous", warmup=20, duration=120):
    from matplotlib.colors import LinearSegmentedColormap
    from .scenarios import get_scenario
    sc = get_scenario(scenario)
    kinds = [f"{s.kind[0].upper()}{i}" for i, s in enumerate(sc.servers)]
    mat = []
    for p in MAIN_POLICIES:
        u = np.array(series[scenario][p]["util"])[warmup:duration]
        mat.append(u.mean(axis=0))
    mat = np.array(mat)
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    cmap = LinearSegmentedColormap.from_list("blues", ps.BLUES)
    im = ax.imshow(mat, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center", fontsize=6.8,
                    color="#ffffff" if mat[i, j] > 0.6 else ps.INK)
    ax.set_xticks(range(len(kinds)))
    ax.set_xticklabels(kinds, fontsize=7.5)
    ax.set_yticks(range(len(MAIN_POLICIES)))
    ax.set_yticklabels([LABELS[p] for p in MAIN_POLICIES])
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks(np.arange(-0.5, len(kinds)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(MAIN_POLICIES)), minor=True)
    ax.grid(which="minor", color=ps.SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    for x in (3.5, 8.5):
        ax.axvline(x, color=ps.SURFACE, lw=5)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=7.5, colors=ps.INK2)
    ax.set_title("Per-server utilization, heterogeneous scenario (seed 0). "
                 "S = 2 workers x0.8, M = 4 x1.0, L = 6 x1.2")
    fig.tight_layout()
    _save(fig, root, "fig_util_heatmap")


# ---- sensitivity --------------------------------------------------------------

SWEEPS = [("load", "offered load ρ", False), ("dispatchers", "load-balancer replicas D", True),
          ("cv", "service-time CV", False), ("speed_ratio", "fastest / slowest server speed", True)]


def sensitivity(df, root):
    summ = summary(df, ["mean", "p99", "error_rate"], by=("sweep", "x", "policy"))
    summ.to_csv(os.path.join(root, "tables", "sensitivity_summary.csv"), index=False)
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 7.2))
    for ax, (sw, xl, logx) in zip(axes.flat, SWEEPS):
        g = summ[summ.sweep == sw]
        for p in MAIN_POLICIES:
            h = g[g.policy == p].sort_values("x")
            if h.empty:
                continue
            ls = (0, ps.DASHES[p]) if p in ps.DASHES else "-"
            ax.plot(h.x, h.p99 * 1000, color=ps.COLORS[p], ls=ls, lw=2.0 if p == "ased" else 1.3,
                    marker="o", ms=3.2, mec=ps.SURFACE, mew=0.8, zorder=3 if p == "ased" else 2,
                    label=LABELS[p])
            if p == "ased":
                ax.fill_between(h.x, (h.p99 - h.p99_ci) * 1000, (h.p99 + h.p99_ci) * 1000,
                                color=ps.COLORS[p], alpha=0.12, lw=0)
        ax.set_yscale("log")
        ps.plain_log(ax.yaxis, subs=(1.0, 1.5, 2.0, 3.0, 5.0, 7.0))
        if logx:
            ax.set_xscale("log", base=2)
            ax.set_xticks(sorted(g.x.unique()))
            ax.set_xticklabels([f"{v:g}" for v in sorted(g.x.unique())])
        ax.set_xlabel(xl)
        ax.set_ylabel("P99 (ms)")
        ax.set_title(f"P99 vs {xl}")
    axes[0][0].legend(ncol=6, loc="upper left", bbox_to_anchor=(0, 1.22), fontsize=8)
    fig.tight_layout()
    _save(fig, root, "fig_sensitivity")

    g = df[df.sweep == "power_of_d"].copy()
    g["d"] = g.policy.map(lambda s: 12 if s == "lc" else int(s.split("=")[1]))
    fig, ax = plt.subplots(figsize=(6.4, 3.9))
    loads = sorted(g.x.unique())
    for c, rho in zip(ps.ORDINAL[1:], loads):
        h = g[g.x == rho].groupby("d")["mean"].mean() * 1000
        ax.plot(h.index, h.values, color=c, marker="o", ms=3.5, mec=ps.SURFACE, mew=0.8, lw=1.6)
        ax.annotate(f"ρ = {rho:g}", (h.index[0], h.values[0]), xytext=(-7, 0), textcoords="offset points",
                    ha="right", va="center", fontsize=7.5, color=ps.INK2)
    ax.set_xscale("log", base=2)
    ax.set_xticks([1, 2, 3, 4, 6, 12])
    ax.set_xticklabels(["1\n(random)", "2", "3", "4", "6", "12\n(LC)"])
    ax.set_yscale("log")
    ps.plain_log(ax.yaxis, subs=(1.0, 2.0, 5.0))
    ax.set_xlim(0.62, 14)
    ax.set_xlabel("servers sampled per request (d)")
    ax.set_ylabel("mean response time (ms)")
    ax.set_title("Power of d choices, homogeneous cluster, 4 replicas")
    fig.tight_layout()
    _save(fig, root, "fig_power_of_d")
    return summ


# ---- ablation / failure semantics / design --------------------------------------

def ablation(df, root):
    from .experiments import ABLATION
    from .stats import holm, ratio_ci, wilcoxon_p
    variants = [v for v in ABLATION if v != "ased"]
    rows = []
    for s in SCENARIOS:
        g = df[df.scenario == s]
        piv = g.pivot_table(index="seed", columns="policy", values="p99")
        pive = g.pivot_table(index="seed", columns="policy", values="error_rate")
        for v in variants:
            r, lo, hi = ratio_ci(piv[v], piv["ased"])
            rows.append(dict(scenario=s, variant=v, p99_ratio=r, lo=lo, hi=hi,
                             p=wilcoxon_p(piv[v], piv["ased"]),
                             err_diff=float((pive[v] - pive["ased"]).mean())))
    res = pd.DataFrame(rows)
    res["p_holm"] = holm(res.p.values)
    res.to_csv(os.path.join(root, "tables", "ablation.csv"), index=False)
    crash = df[df.scenario == "server_crash"].groupby("policy")["error_rate"].agg(["mean", "std", "count"])
    table = []
    for v in variants:
        row = {"Variant": ABLATION[v]}
        for s in SCENARIOS:
            r = res[(res.scenario == s) & (res.variant == v)].iloc[0]
            star = "*" if r.p_holm < 0.05 else ""
            row[SCEN_LABELS[s]] = f"{r.p99_ratio:.2f}{star}"
        row["Crash error rate"] = f"{crash.loc[v, 'mean'] * 100:.2f}%"
        table.append(row)
    table.append({"Variant": ABLATION["ased"], **{SCEN_LABELS[s]: "1.00" for s in SCENARIOS},
                  "Crash error rate": f"{crash.loc['ased', 'mean'] * 100:.2f}%"})
    _write(root, "ablation.md", _md_table(pd.DataFrame(table)))

    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    div = LinearSegmentedColormap.from_list("div", ["#1c5cab", "#86b6ef", "#f0efec", "#ef9a99", "#b42b2b"])
    mat = res.pivot(index="variant", columns="scenario", values="p99_ratio").loc[variants, SCENARIOS]
    sig = res.pivot(index="variant", columns="scenario", values="p_holm").loc[variants, SCENARIOS]
    fig, (ax, axe) = plt.subplots(1, 2, figsize=(11.2, 3.9), gridspec_kw={"width_ratios": [3.2, 1]})
    im = ax.imshow(np.log2(mat.values), cmap=div, norm=TwoSlopeNorm(0, -1, 1), aspect="auto")
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat.values[i, j]
            ax.text(j, i, f"{v:.2f}" + ("*" if sig.values[i, j] < 0.05 else ""), ha="center",
                    va="center", fontsize=7.8, color="#ffffff" if abs(np.log2(v)) > 0.7 else ps.INK)
    ax.set_xticks(range(len(SCENARIOS)))
    ax.set_xticklabels([SCEN_LABELS[s] for s in SCENARIOS], rotation=20, ha="right")
    ax.set_yticks(range(len(variants)))
    ax.set_yticklabels([ABLATION[v] for v in variants])
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks(np.arange(-0.5, len(SCENARIOS)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(variants)), minor=True)
    ax.grid(which="minor", color=ps.SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02, ticks=[-1, -0.5, 0, 0.5, 1])
    cb.ax.set_yticklabels(["0.5", "0.71", "1", "1.41", "≥2"])
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=7.5, colors=ps.INK2)
    ax.set_title("P99 of variant / P99 of full ASED (>1 = worse, * Holm p < 0.05, 20 seeds)")
    order = variants + ["ased"]
    se = crash["std"] / np.sqrt(crash["count"])
    ps.hbars(axe, [ABLATION[v] if v != "ased" else "full ASED" for v in order],
             [crash.loc[v, "mean"] * 100 for v in order],
             [ps.ACCENT if v == "ased" else ps.DEEMPH for v in order],
             [1.96 * se.loc[v] * 100 for v in order], fmt="{:.2f}%")
    axe.set_yticklabels([])
    axe.set_title("Error rate, server crash")
    axe.set_xlabel("% of requests")
    fig.tight_layout()
    _save(fig, root, "fig_ablation")
    return res


def failure_semantics(df, root):
    summ = summary(df, ["failure_errors", "failure_p99", "error_rate", "p99"],
                   by=("crash_mode", "outlier_detection", "policy"))
    summ.to_csv(os.path.join(root, "tables", "failure_summary.csv"), index=False)
    conds = [("refuse", False, "Connection refused, health checks only"),
             ("refuse", True, "Connection refused, + outlier detection"),
             ("blackhole", False, "Blackhole (1 s timeout), health checks only"),
             ("blackhole", True, "Blackhole (1 s timeout), + outlier detection")]
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 6.6))
    rows = []
    for ax, (mode, od, ttl) in zip(axes.flat, conds):
        g = summ[(summ.crash_mode == mode) & (summ.outlier_detection == od)].set_index("policy").loc[MAIN_POLICIES]
        cols = [ps.ACCENT if p == "ased" else ps.DEEMPH for p in MAIN_POLICIES]
        ps.hbars(ax, [LABELS[p] for p in MAIN_POLICIES],
                 g.failure_errors.values, cols, g.failure_errors_ci.values)
        ax.set_title(ttl)
        ax.set_xlabel("failed + rejected requests during the 40 s outage")
        for p in MAIN_POLICIES:
            rows.append({"Condition": ttl, "Policy": LABELS[p],
                         "Failed requests": f"{g.loc[p, 'failure_errors']:.0f} ± {g.loc[p, 'failure_errors_ci']:.0f}",
                         "Outage P99 (ms)": f"{g.loc[p, 'failure_p99'] * 1000:.0f}"})
    fig.suptitle("Failure semantics: 2 of 12 servers crash at 50 s (mean of 20 seeds, 95% CI)",
                 x=0.01, ha="left", fontsize=10, color=ps.INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    _save(fig, root, "fig_failure_semantics")
    _write(root, "failure_semantics.md", _md_table(pd.DataFrame(rows)))
    return summ


def design(df, root):
    from .experiments import DESIGN
    summ = summary(df, ["mean", "p99", "error_rate"])
    rows = []
    for spec, name in DESIGN.items():
        row = {"Variant": name}
        for s in SCENARIOS:
            g = summ[(summ.scenario == s) & (summ.policy == spec)]
            row[SCEN_LABELS[s]] = f"{g['mean'].values[0] * 1000:.1f} / {g['p99'].values[0] * 1000:.0f}"
        rows.append(row)
    _write(root, "design_exploration.md", _md_table(pd.DataFrame(rows)))
    summ.to_csv(os.path.join(root, "tables", "design_summary.csv"), index=False)


def validation(root):
    p = os.path.join(root, "validation", "validation_runs.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p)
    rows = []
    for case, g in df.groupby("case", sort=False):
        m, h = mean_ci(g.value)
        a = g.analytic.iloc[0]
        rows.append({"Case": case, "Metric": g.metric.iloc[0], "Analytic": f"{a:.4f}",
                     "Simulated (95% CI)": f"{m:.4f} ± {h:.4f}", "Rel. error": f"{(m - a) / a * 100:+.2f}%",
                     "CI covers analytic": "yes" if abs(m - a) <= h else "no"})
    tab = pd.DataFrame(rows)
    _write(root, "validation.md", _md_table(tab))
    return tab


def key_numbers(summ, pw, root):
    out = {}
    for s in SCENARIOS:
        g = summ[summ.scenario == s].set_index("policy")
        dep = g.loc[MAIN_POLICIES]
        out[s] = dict(
            best_p99=LABELS[dep.p99.idxmin()], best_mean=LABELS[dep["mean"].idxmin()],
            ased_p99_ms=round(g.loc["ased", "p99"] * 1000, 1),
            ased_mean_ms=round(g.loc["ased", "mean"] * 1000, 1),
            ased_err_pct=round(g.loc["ased", "error_rate"] * 100, 3),
            rank_p99=int(dep.p99.rank().loc["ased"]), rank_mean=int(dep["mean"].rank().loc["ased"]),
        )
    with open(os.path.join(root, "tables", "key_numbers.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


def analyze_all(root="results"):
    ps.setup()
    os.makedirs(os.path.join(root, "tables"), exist_ok=True)
    validation(root)
    main = _load(root, "main")
    if main is not None:
        summ, pw = main_tables(main, root)
        fig_main_bars(summ, root)
        fig_cd(main, root)
        sp = os.path.join(root, "main", "series_seed0.json")
        if os.path.exists(sp):
            with open(sp) as f:
                series = json.load(f)
            fig_timeseries(series, root)
            fig_util_heatmap(series, root)
        key_numbers(summ, pw, root)
    for name, fn in (("sensitivity", sensitivity), ("ablation", ablation),
                     ("failure", failure_semantics), ("design", design)):
        df = _load(root, name)
        if df is not None:
            fn(df, root)
    print("analysis written to", os.path.join(root, "tables"), "and", os.path.join(root, "figures"))
    if main is not None:
        from .export import export_demo
        export_demo(root)
