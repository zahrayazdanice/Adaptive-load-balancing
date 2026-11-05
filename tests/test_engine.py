import numpy as np
import pytest

from lbsim.engine import FAILED, OK, REJECTED, simulate
from lbsim.faults import Crash, Slowdown, expand_faults
from lbsim.metrics import summarize, windows
from lbsim.policies import MAIN_POLICIES
from lbsim.scenarios import get_scenario, main_scenarios


def short(name, **kw):
    return get_scenario(name).with_(duration=40.0, warmup=5.0, **kw)


@pytest.mark.parametrize("policy", MAIN_POLICIES)
def test_every_request_is_resolved(policy):
    sc = short("server_crash").with_(faults=(Crash((4, 9), 15.0, 30.0),), events=())
    res = simulate(sc, policy, 3)
    assert (res.status != 0).all()
    assert np.isin(res.status, [OK, REJECTED, FAILED]).all()
    ok = res.status == OK
    assert (res.t_resp[ok] > res.times[ok]).all()


def test_same_seed_is_deterministic():
    sc = short("bursty")
    a = simulate(sc, "ased", 7)
    b = simulate(sc, "ased", 7)
    assert np.array_equal(a.server, b.server)
    assert np.allclose(a.t_resp, b.t_resp)


def test_traces_are_shared_across_policies():
    sc = short("heterogeneous")
    t1, t2 = sc.trace(4), sc.trace(4)
    assert np.array_equal(t1.times, t2.times) and np.array_equal(t1.work, t2.work)
    assert not np.array_equal(sc.trace(5).times[:50], t1.times[:50])


def test_queue_never_exceeds_capacity():
    sc = short("heterogeneous").with_workload(load=1.3)
    res = simulate(sc, "rr", 1)
    caps = np.array([s.queue_cap for s in sc.servers])
    assert (res.queue <= caps).all()
    assert (res.status == REJECTED).any()


def test_crashed_server_serves_nothing_while_down():
    sc = short("server_crash").with_(faults=(Crash((4,), 10.0, 25.0),), events=())
    res = simulate(sc, "rr", 2)
    down = (res.times > 10.01) & (res.times < 25.0) & (res.server == 4)
    assert down.any()
    assert (res.status[down] == FAILED).all()
    detect = res.times[down].max()
    assert 10.0 + 1.9 <= detect <= 10.0 + 3.0 + 0.01   # third failed probe at 1 s spacing


def test_blackhole_failures_wait_for_timeout():
    sc = short("server_crash").with_(faults=(Crash((4,), 10.0, 25.0),), events=(), crash_mode="blackhole")
    res = simulate(sc, "rr", 2)
    f = (res.status == FAILED) & (res.times > 10.01)
    assert f.any()
    assert np.all(res.t_resp[f] - res.times[f] >= sc.timeout - 1e-9)


def test_outlier_detection_cuts_black_hole_traffic():
    sc = short("server_crash").with_(faults=(Crash((4, 9), 15.0, 35.0),), events=())
    base = summarize(simulate(sc, "lc", 1), sc)["failed"]
    od = summarize(simulate(sc.with_(outlier_detection=True), "lc", 1), sc)["failed"]
    assert od < 0.5 * base


def test_slowdown_increases_service_time():
    sc = short("gray_failure").with_(faults=(Slowdown((5,), 10.0, 30.0, 0.25),), events=())
    res = simulate(sc, "rr", 0)
    on5 = (res.server == 5) & (res.status == OK)
    before = np.nanmean(res.svc[on5 & (res.times < 9)])
    during = np.nanmean(res.svc[on5 & (res.times > 15) & (res.times < 28)])
    assert during > 2.5 * before


def test_utilization_matches_offered_load():
    sc = get_scenario("baseline").with_(duration=60.0)
    row = summarize(simulate(sc, "rr", 0), sc)
    assert row["util_mean"] == pytest.approx(0.8, abs=0.03)
    assert row["error_rate"] == 0


def test_fault_expansion_is_sorted():
    ev = expand_faults([Slowdown((1,), 30.0, 40.0), Crash((2,), 10.0, 20.0)])
    assert [e[0] for e in ev] == sorted(e[0] for e in ev)
    assert ev[0][1] == "crash" and ev[-1][1] == "restore"


def test_windows_count_all_arrivals():
    sc = short("flash_crowd")
    res = simulate(sc, "lc", 0)
    w = windows(res, sc)
    assert w.arrivals.sum() == len(res.times)
    assert (w.ok + w.errors == w.arrivals).all()


def test_all_main_scenarios_build():
    for sc in main_scenarios():
        assert sc.capacity == pytest.approx(48.0)
        assert sc.arrival_rate > 0
