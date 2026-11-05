import math

import pytest

from lbsim.engine import simulate
from lbsim.metrics import summarize
from lbsim.validation import cases, erlang_c, mm1k_blocking, mmc_response


def test_erlang_c_known_value():
    # M/M/2 with a = 1: P(wait) = 1/3
    assert erlang_c(2, 1.0) == pytest.approx(1 / 3)
    assert mmc_response(0.5, 1.0, 1) == pytest.approx(2.0)


def test_mm1k_blocking_sums_to_geometric_tail():
    assert mm1k_blocking(1.0, 4) == pytest.approx(0.2)
    assert 0 < mm1k_blocking(0.9, 5) < 0.2


@pytest.mark.parametrize("sc,metric,expected", cases(duration=15000.0), ids=lambda x: getattr(x, "name", ""))
def test_simulator_matches_queueing_theory(sc, metric, expected):
    vals = [summarize(simulate(sc, "p2c:d=1", seed), sc)[metric] for seed in range(3)]
    got = sum(vals) / len(vals)
    tol = 0.01 if metric == "error_rate" else 0.06 * expected
    assert math.isclose(got, expected, abs_tol=tol), (sc.name, got, expected)
