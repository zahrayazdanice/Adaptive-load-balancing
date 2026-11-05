import numpy as np
import pytest

from lbsim.cluster import heterogeneous, speed_spread, total_capacity
from lbsim.metrics import jain
from lbsim.stats import holm, mean_ci, rank_biserial, ratio_ci, wilcoxon_p
from lbsim.workload import Workload, bounded_pareto_mean, generate_trace, sample_work, service_moments


@pytest.mark.parametrize("wl", [Workload(service="exp"), Workload(service="lognormal", cv=1.5),
                                Workload(service="pareto"), Workload(service="det")])
def test_work_has_unit_mean_and_expected_scv(wl):
    x = sample_work(wl, 2_000_000, np.random.default_rng(0))
    m, scv = service_moments(wl)
    assert x.mean() == pytest.approx(1.0, rel=0.02)
    assert x.var() / x.mean() ** 2 == pytest.approx(scv, rel=0.12, abs=1e-9)


def test_bounded_pareto_mean_formula():
    rng = np.random.default_rng(1)
    a, r = 1.5, 100.0
    u = rng.random(2_000_000)
    x = (1.0 - u * (1.0 - r ** -a)) ** (-1.0 / a)
    assert x.mean() == pytest.approx(bounded_pareto_mean(a, r), rel=0.01)
    assert x.min() >= 1.0 and x.max() <= r


def test_poisson_rate_and_spike():
    wl = Workload(load=0.5, spikes=((100.0, 200.0, 2.0),))
    tr = generate_trace(wl, 48.0, 0.05, 300.0, 4, seed=0)
    lam = 0.5 * 48 / 0.05
    base = ((tr.times < 100) | (tr.times >= 200)).sum() / 200.0
    spike = ((tr.times >= 100) & (tr.times < 200)).sum() / 100.0
    assert base == pytest.approx(lam, rel=0.03)
    assert spike == pytest.approx(2 * lam, rel=0.03)
    assert set(np.unique(tr.disp)) == {0, 1, 2, 3}


def test_mmpp_keeps_average_rate():
    wl = Workload(load=0.5, arrivals="mmpp", burst_sojourn=2.0)
    rates = [len(generate_trace(wl, 48.0, 0.05, 400.0, 1, seed=s).times) / 400.0 for s in range(5)]
    assert np.mean(rates) == pytest.approx(480.0, rel=0.05)
    counts = np.histogram(generate_trace(wl, 48.0, 0.05, 400.0, 1, seed=9).times, bins=400)[0]
    assert counts.var() > 5 * counts.mean()


def test_cluster_capacities():
    assert total_capacity(heterogeneous()) == pytest.approx(48.0)
    sp = speed_spread(8)
    assert max(s.speed for s in sp) / min(s.speed for s in sp) == pytest.approx(8.0)
    assert np.mean([s.speed for s in sp]) == pytest.approx(1.0)


def test_jain_index():
    assert jain([1, 1, 1, 1]) == pytest.approx(1.0)
    assert jain([1, 0, 0, 0]) == pytest.approx(0.25)


def test_mean_ci_and_ratio():
    m, h = mean_ci([1, 2, 3, 4, 5])
    assert m == 3 and h == pytest.approx(1.9632, rel=1e-3)
    r, lo, hi = ratio_ci([2, 2, 2], [1, 1, 1])
    assert r == pytest.approx(2.0) and lo == pytest.approx(2.0)


def test_holm_adjustment():
    assert list(holm([0.01, 0.04, 0.03, 0.005])) == pytest.approx([0.03, 0.06, 0.06, 0.02])


def test_wilcoxon_and_effect_size():
    a = np.arange(1, 21) + 0.5
    b = np.arange(1, 21)
    assert wilcoxon_p(a, b) < 0.001
    assert rank_biserial(a, b) == pytest.approx(1.0)
    assert wilcoxon_p(b, b) == 1.0
