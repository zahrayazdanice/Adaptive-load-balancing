import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Workload:
    load: float = 0.7
    service: str = "lognormal"      # exp | lognormal | pareto | det
    cv: float = 1.5                 # lognormal only
    pareto_alpha: float = 1.2
    pareto_ratio: float = 1000.0    # H / L of the bounded Pareto
    arrivals: str = "poisson"       # poisson | mmpp
    burst_high: float = 1.5
    burst_low: float = 0.5
    burst_sojourn: float = 2.0
    spikes: tuple = ()              # ((start, end, multiplier), ...)


@dataclass
class Trace:
    times: np.ndarray
    work: np.ndarray
    disp: np.ndarray
    rate: float


def bounded_pareto_mean(alpha, ratio):
    # mean of BP(alpha, L=1, H=ratio)
    if alpha == 1:
        return math.log(ratio) / (1 - 1 / ratio)
    return (alpha / (alpha - 1)) * (1 - ratio ** (1 - alpha)) / (1 - ratio ** -alpha)


def service_moments(wl):
    """Mean (always 1) and squared coefficient of variation of the work distribution."""
    if wl.service == "exp":
        return 1.0, 1.0
    if wl.service == "lognormal":
        return 1.0, wl.cv ** 2
    if wl.service == "det":
        return 1.0, 0.0
    a, r = wl.pareto_alpha, wl.pareto_ratio
    m1 = bounded_pareto_mean(a, r)
    if a == 2:
        m2 = 2 * math.log(r) / (1 - r ** -2)
    else:
        m2 = (a / (2 - a)) * (r ** (2 - a) - 1) / (1 - r ** -a)
    return 1.0, m2 / m1 ** 2 - 1


def sample_work(wl, n, rng):
    """Service demands with mean 1, in units of the mean service time."""
    if wl.service == "exp":
        return rng.exponential(1.0, n)
    if wl.service == "lognormal":
        s2 = math.log(1 + wl.cv ** 2)
        return rng.lognormal(-s2 / 2, math.sqrt(s2), n)
    if wl.service == "pareto":
        a, r = wl.pareto_alpha, wl.pareto_ratio
        u = rng.random(n)
        x = (1.0 - u * (1.0 - r ** -a)) ** (-1.0 / a)
        return x / bounded_pareto_mean(a, r)
    if wl.service == "det":
        return np.ones(n)
    raise ValueError(f"unknown service distribution {wl.service}")


def mmpp_path(wl, duration, rng):
    """Two-state Markov-modulated rate multiplier as (segment starts, levels)."""
    starts, levels = [], []
    t, high = 0.0, rng.random() < 0.5
    while t < duration:
        starts.append(t)
        levels.append(wl.burst_high if high else wl.burst_low)
        t += rng.exponential(wl.burst_sojourn)
        high = not high
    return np.array(starts), np.array(levels)


def rate_multiplier(wl, t, path=None):
    m = np.ones_like(t)
    if path is not None:
        starts, levels = path
        m = levels[np.searchsorted(starts, t, side="right") - 1]
    for a, b, f in wl.spikes:
        m = np.where((t >= a) & (t < b), m * f, m)
    return m


def generate_trace(wl, capacity, mean_service, duration, dispatchers, seed):
    """Arrival times, work and dispatcher ids; shared by all policies for a given seed."""
    ss = np.random.SeedSequence([seed, 7])
    r_arr, r_svc, r_disp = [np.random.default_rng(s) for s in ss.spawn(3)]
    lam = wl.load * capacity / mean_service
    path = mmpp_path(wl, duration, r_arr) if wl.arrivals == "mmpp" else None
    peak = max(wl.burst_high, wl.burst_low) if path is not None else 1.0
    for _, _, f in wl.spikes:
        peak *= max(f, 1.0)
    n = r_arr.poisson(lam * peak * duration)
    cand = np.sort(r_arr.uniform(0.0, duration, n))
    keep = r_arr.random(n) < rate_multiplier(wl, cand, path) / peak
    times = cand[keep]
    work = sample_work(wl, len(times), r_svc)
    disp = r_disp.integers(0, dispatchers, len(times))
    return Trace(times, work, disp, lam)
