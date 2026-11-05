import random
from collections import Counter
from types import SimpleNamespace

import pytest

from lbsim.engine import Dispatcher
from lbsim.policies import (ASED, MAIN_POLICIES, OK, LeastConnections, LeastResponseTime, PowerOfD,
                            RoundRobin, WeightedRoundRobin, label, make_policy, parse_spec)

FAILED = 3


def setup(n=4, workers=(2, 4, 4, 6), speeds=(0.8, 1.0, 1.0, 1.2), D=1):
    ctx = SimpleNamespace(n=n, workers=list(workers), speeds=list(speeds),
                          weights=[w * s for w, s in zip(workers, speeds)], mean_service=0.05,
                          dispatchers=D)
    lb = Dispatcher(0, n)
    return ctx, lb


def set_eligible(lb, el):
    lb.eligible[:] = el
    for i in range(len(lb.mask)):
        lb.mask[i] = i in el


def test_six_policies_are_registered():
    assert MAIN_POLICIES == ["rr", "wrr", "lc", "p2c", "lrt", "ased"]


def test_round_robin_cycles_and_skips_ineligible():
    ctx, lb = setup()
    p = RoundRobin(ctx, lb, random.Random(1))
    first = [p.choose(0) for _ in range(8)]
    assert sorted(first[:4]) == [0, 1, 2, 3] and first[:4] == first[4:]
    set_eligible(lb, [0, 2])
    assert set(p.choose(0) for _ in range(10)) == {0, 2}


def test_smooth_wrr_matches_weights_exactly():
    ctx, lb = setup(workers=(1, 2, 3, 4), speeds=(1, 1, 1, 1))
    p = WeightedRoundRobin(ctx, lb, random.Random(3))
    picks = Counter(p.choose(0) for _ in range(1000))
    assert [picks[i] for i in range(4)] == [100, 200, 300, 400]


def test_smooth_wrr_interleaves():
    ctx, lb = setup(workers=(5, 1, 1, 1), speeds=(1, 1, 1, 1))
    p = WeightedRoundRobin(ctx, lb, random.Random(0))
    longest = run = 0
    for _ in range(32):
        run = run + 1 if p.choose(0) == 0 else 0
        longest = max(longest, run)
    assert longest <= 3


def test_least_connections_picks_min_and_breaks_ties_uniformly():
    ctx, lb = setup()
    p = LeastConnections(ctx, lb, random.Random(5))
    lb.out[:] = [3, 1, 2, 5]
    assert p.choose(0) == 1
    lb.out[:] = [1, 0, 0, 0]
    c = Counter(p.choose(0) for _ in range(3000))
    assert set(c) == {1, 2, 3} and min(c.values()) > 850


def test_p2c_never_picks_unique_worst_server():
    ctx, lb = setup()
    p = PowerOfD(ctx, lb, random.Random(2), d=2)
    lb.out[:] = [1, 1, 1, 9]
    assert 3 not in {p.choose(0) for _ in range(2000)}


def test_power_of_one_is_uniform_and_respects_eligibility():
    ctx, lb = setup()
    p = PowerOfD(ctx, lb, random.Random(2), d=1)
    c = Counter(p.choose(0) for _ in range(8000))
    assert all(1800 < c[i] < 2200 for i in range(4))
    set_eligible(lb, [1, 3])
    assert {p.choose(0) for _ in range(200)} == {1, 3}


def test_lrt_prefers_fast_then_accounts_for_load():
    ctx, lb = setup()
    p = LeastResponseTime(ctx, lb, random.Random(0))
    for i, rtt in enumerate([0.2, 0.05, 0.1, 0.1]):
        p.on_response(0, i, OK, rtt, 0.05, 0)
    assert p.choose(0) == 1
    lb.out[:] = [0, 5, 0, 0]
    assert p.choose(0) in (2, 3)


def test_ased_learns_speed_and_avoids_errors():
    ctx, lb = setup(workers=(4, 4, 4, 4), speeds=(1, 1, 1, 1))
    p = ASED(ctx, lb, random.Random(0))
    for i, s in enumerate([0.10, 0.05, 0.05, 0.05]):
        p.on_response(0.0, i, OK, s, s, 0)
    assert p.choose(0.0) != 0              # slow server loses at equal load
    lb.out[:] = [0, 2, 2, 2]
    assert p.choose(0.0) == 0              # but wins when the fast ones are busy
    lb.out[:] = [0, 0, 0, 0]
    for _ in range(3):
        p.on_response(1.0, 1, FAILED, 0.001, 0.0, -1)
    assert p.score(1, 1.0) > 5 * p.score(2, 1.0)
    assert p.score(1, 20.0) == pytest.approx(p.score(2, 20.0), rel=1e-3)


def test_ased_concurrency_compensation_scales_local_count():
    ctx, lb = setup(workers=(4, 4, 4, 4), speeds=(1, 1, 1, 1), D=4)
    p = ASED(ctx, lb, random.Random(0))
    lb.out[:] = [1, 0, 0, 0]
    assert p.score(0, 0) == pytest.approx(0.05 * 5 / 4)
    q = ASED(ctx, lb, random.Random(0), comp=0)
    assert q.score(0, 0) == pytest.approx(0.05 * 2 / 4)


def test_ased_fcfs_form_is_flat_while_workers_are_free():
    ctx, lb = setup(workers=(4, 4, 4, 4), speeds=(1, 1, 1, 1))
    p = ASED(ctx, lb, random.Random(0), form="fcfs")
    lb.out[:] = [0, 3, 4, 7]
    assert p.score(0, 0) == p.score(1, 0) == pytest.approx(0.05)
    assert p.score(2, 0) == pytest.approx(0.05 * 1.25) and p.score(3, 0) == pytest.approx(0.05 * 2)


def test_spec_parsing_and_labels():
    assert parse_spec("ased:d=2,form=fcfs,beta=0.0") == ("ased", {"d": 2, "form": "fcfs", "beta": 0.0})
    assert label("p2c:d=3") == "P2C(d=3)"
    ctx, lb = setup()
    assert isinstance(make_policy("p2c:d=3", ctx, lb, random.Random(0)), PowerOfD)
