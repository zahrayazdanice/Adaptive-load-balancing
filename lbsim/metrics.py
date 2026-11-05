from dataclasses import dataclass

import numpy as np

from .engine import FAILED, OK, PENDING, REJECTED


def jain(x):
    x = np.asarray(x, float)
    s2 = float((x ** 2).sum())
    return float(x.sum() ** 2 / (len(x) * s2)) if s2 > 0 else 1.0


@dataclass
class Windows:
    start: np.ndarray
    arrivals: np.ndarray
    ok: np.ndarray
    errors: np.ndarray
    p50: np.ndarray
    p95: np.ndarray
    p99: np.ndarray

    @property
    def err_frac(self):
        return np.divide(self.errors, self.arrivals, out=np.zeros(len(self.arrivals)),
                         where=self.arrivals > 0)


def windows(res, sc, width=1.0):
    """Latency percentiles and error counts per window, keyed by arrival time."""
    t = res.times
    nb = int(np.ceil(sc.duration / width))
    b = np.minimum((t // width).astype(int), nb - 1)
    ok = res.status == OK
    arrivals = np.bincount(b, minlength=nb)
    oks = np.bincount(b[ok], minlength=nb)
    lat = (res.t_resp - t)[ok]
    bo = b[ok]
    order = np.argsort(bo, kind="stable")
    bo, lat = bo[order], lat[order]
    edges = np.searchsorted(bo, np.arange(nb + 1))
    p = np.full((nb, 3), np.nan)
    for w in range(nb):
        seg = lat[edges[w]:edges[w + 1]]
        if len(seg):
            p[w] = np.percentile(seg, [50, 95, 99])
    return Windows(np.arange(nb) * width, arrivals, oks, arrivals - oks, p[:, 0], p[:, 1], p[:, 2])


def degraded(win, sc):
    p95 = np.nan_to_num(win.p95, nan=np.inf)
    return (p95 > sc.slo) | (win.err_frac > 0.01)


def event_metrics(res, sc, win=None):
    win = win or windows(res, sc)
    deg = degraded(win, sc)
    lat = res.t_resp - res.times
    out = {}
    for name, a, b in sc.events:
        d = deg[int(a):int(b)]
        hit = np.flatnonzero(d)
        m = (res.times >= a) & (res.times < b)
        st = res.status[m]
        good = lat[m][st == OK]
        out[f"{name}_errors"] = int((st != OK).sum())
        out[f"{name}_p99"] = float(np.percentile(good, 99)) if len(good) else np.nan
        out[f"{name}_degraded"] = int(d.sum())
        out[f"{name}_ttr"] = float(hit[-1] + 1) if len(hit) else 0.0
    return out


def summarize(res, sc):
    t = res.times
    m = (t >= sc.warmup) & (t < sc.duration)
    st = res.status[m]
    lat = (res.t_resp - t)[m]
    n = int(m.sum())
    ok = st == OK
    good = lat[ok]
    p = np.percentile(good, [50, 95, 99, 99.9]) if len(good) else [np.nan] * 4
    span = sc.duration - sc.warmup
    row = dict(
        requests=n,
        ok=int(ok.sum()),
        rejected=int((st == REJECTED).sum()),
        failed=int((st == FAILED).sum()),
        unresolved=int((st == PENDING).sum()),
        error_rate=float(1.0 - ok.mean()),
        throughput=float(ok.sum() / span),
        mean=float(good.mean()),
        p50=float(p[0]), p95=float(p[1]), p99=float(p[2]), p999=float(p[3]),
        slo_attain=float((good <= sc.slo).sum() / n),
    )
    wm = (res.report_t > sc.warmup + 1e-9) & (res.report_t <= sc.duration + 1e-9)
    per_server = res.util[wm].mean(axis=0)
    row.update(
        util_mean=float(per_server.mean()),
        util_max=float(per_server.max()),
        util_jain=jain(per_server),
        util_cv=float(per_server.std() / per_server.mean()),
        queue_mean=float(res.queue[wm].mean()),
        queue_max=int(res.queue[wm].max()),
    )
    win = windows(res, sc)
    row["degraded_s"] = int(degraded(win, sc)[int(sc.warmup):int(sc.duration)].sum())
    if sc.events:
        row.update(event_metrics(res, sc, win))
    return row


def timeseries(res, sc):
    """Compact per-second series for plots and the demo page."""
    win = windows(res, sc)
    nb = len(win.start)
    util = res.util[:nb]
    return dict(
        t=win.start.tolist(),
        p50=np.round(win.p50 * 1000, 2).tolist(),
        p95=np.round(win.p95 * 1000, 2).tolist(),
        p99=np.round(win.p99 * 1000, 2).tolist(),
        arrivals=win.arrivals.tolist(),
        errors=win.errors.tolist(),
        util=np.round(util, 3).tolist(),
        queue=res.queue[:nb].tolist(),
    )
