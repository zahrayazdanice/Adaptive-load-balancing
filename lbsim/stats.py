"""Statistics for paired, multi-seed comparisons."""
import numpy as np
import pandas as pd
from scipy import stats


def mean_ci(x, level=0.95):
    """Mean and half-width of the t confidence interval."""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n == 0:
        return np.nan, np.nan
    if n == 1:
        return float(x[0]), np.nan
    h = stats.t.ppf(0.5 + level / 2, n - 1) * x.std(ddof=1) / np.sqrt(n)
    return float(x.mean()), float(h)


def holm(pvals):
    """Holm-Bonferroni adjusted p-values."""
    p = np.asarray(pvals, float)
    m = len(p)
    adj = np.empty(m)
    running = 0.0
    for rank, idx in enumerate(np.argsort(p)):
        running = max(running, (m - rank) * p[idx])
        adj[idx] = min(1.0, running)
    return adj


def wilcoxon_p(a, b):
    d = np.asarray(a, float) - np.asarray(b, float)
    if np.allclose(d, 0):
        return 1.0
    return float(stats.wilcoxon(a, b).pvalue)


def rank_biserial(a, b):
    """Matched-pairs rank-biserial correlation; positive when a > b."""
    d = np.asarray(a, float) - np.asarray(b, float)
    d = d[d != 0]
    if len(d) == 0:
        return 0.0
    r = stats.rankdata(np.abs(d))
    return float((r[d > 0].sum() - r[d < 0].sum()) / r.sum())


def ratio_ci(a, b, level=0.95):
    """Geometric mean of a / b with a t interval on the log ratios."""
    lr = np.log(np.asarray(a, float) / np.asarray(b, float))
    m, h = mean_ci(lr, level)
    return float(np.exp(m)), float(np.exp(m - h)), float(np.exp(m + h))


def summary(df, metrics, by=("scenario", "policy")):
    rows = []
    for key, g in df.groupby(list(by), sort=False):
        row = dict(zip(by, key if isinstance(key, tuple) else (key,)))
        row["n"] = len(g)
        for m in metrics:
            row[m], row[m + "_ci"] = mean_ci(g[m])
        rows.append(row)
    return pd.DataFrame(rows)


LOWER_IS_BETTER = {"mean", "p50", "p95", "p99", "p999", "error_rate", "util_cv", "queue_mean",
                   "degraded_s"}


def pairwise(df, ref, metrics, by="scenario", ratio_metrics=("mean", "p95", "p99")):
    """Compare `ref` with every other policy, paired by seed, within each `by` group.

    Ratios are other / ref (> 1 means ref is better for latency metrics).
    Holm correction is applied per metric across all comparisons.
    """
    rows = []
    for grp, g in df.groupby(by, sort=False):
        piv = {m: g.pivot_table(index="seed", columns="policy", values=m) for m in metrics}
        for other in piv[metrics[0]].columns:
            if other == ref:
                continue
            for m in metrics:
                a, b = piv[m][other], piv[m][ref]
                ok = a.notna() & b.notna()
                a, b = a[ok].values, b[ok].values
                row = dict(group=grp, policy=other, metric=m, n=len(a),
                           ref_mean=float(b.mean()), other_mean=float(a.mean()),
                           p=wilcoxon_p(a, b), effect=rank_biserial(a, b))
                better = (b < a) if m in LOWER_IS_BETTER else (b > a)
                row["ref_wins"] = float(better.mean())
                if m in ratio_metrics:
                    row["ratio"], row["ratio_lo"], row["ratio_hi"] = ratio_ci(a, b)
                else:
                    row["diff"], row["diff_ci"] = mean_ci(a - b)
                rows.append(row)
    out = pd.DataFrame(rows)
    out["p_holm"] = np.nan
    for m in metrics:
        sel = out["metric"] == m
        out.loc[sel, "p_holm"] = holm(out.loc[sel, "p"].values)
    return out


def friedman_ranks(df, metric, block=("scenario", "seed")):
    """Mean rank of every policy (1 = best) and the Friedman test over blocks."""
    piv = df.pivot_table(index=list(block), columns="policy", values=metric)
    asc = metric in LOWER_IS_BETTER
    ranks = piv.rank(axis=1, ascending=asc)
    stat, p = stats.friedmanchisquare(*[piv[c].values for c in piv.columns])
    return ranks.mean().sort_values(), float(stat), float(p), len(piv)


def nemenyi_cd(k, n, alpha=0.05):
    """Critical difference of mean ranks (Demsar 2006)."""
    q = stats.studentized_range.ppf(1 - alpha, k, 1e6) / np.sqrt(2)
    return float(q * np.sqrt(k * (k + 1) / (6.0 * n)))
