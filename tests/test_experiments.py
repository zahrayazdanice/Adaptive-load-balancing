import json
import pathlib

import numpy as np
import pandas as pd
import pytest

from lbsim.experiments import ABLATION, DESIGN, _run_group
from lbsim.export import export_demo
from lbsim.policies import MAIN_POLICIES, POLICIES, parse_spec
from lbsim.scenarios import get_scenario
from lbsim.stats import friedman_ranks, pairwise

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_run_group_shares_one_trace():
    sc = get_scenario("heterogeneous").with_(duration=30.0, warmup=5.0)
    name, rows, series = _run_group((sc, 0, ["rr", "ased"], {"tag": 1}, True))
    assert name == "heterogeneous" and len(rows) == 2
    assert rows[0]["requests"] == rows[1]["requests"]
    assert set(series) == {"rr", "ased"} and len(series["rr"]["p95"]) == 30
    assert all(r["tag"] == 1 for r in rows)


def test_pairwise_and_ranks_on_synthetic_data():
    rng = np.random.default_rng(0)
    rows = []
    for seed in range(12):
        base = rng.uniform(1, 2)
        for p, f in [("a", 1.0), ("b", 1.3), ("c", 1.6)]:
            rows.append(dict(scenario="s", seed=seed, policy=p, p99=base * f, error_rate=0.0))
    df = pd.DataFrame(rows)
    pw = pairwise(df, "a", ["p99", "error_rate"])
    r = pw[(pw.policy == "c") & (pw.metric == "p99")].iloc[0]
    assert r.ratio == pytest.approx(1.6) and r.ref_wins == 1.0 and r.p_holm < 0.01
    ranks, stat, p, n = friedman_ranks(df, "p99")
    assert list(ranks.index) == ["a", "b", "c"] and n == 12 and p < 0.001


def test_experiment_specs_are_valid():
    for spec in list(ABLATION) + list(DESIGN):
        name, _ = parse_spec(spec)
        assert name in POLICIES


@pytest.mark.skipif(not (ROOT / "results" / "main" / "runs.csv").exists(), reason="results not generated")
def test_demo_export(tmp_path):
    export_demo(str(ROOT / "results"), str(tmp_path))
    text = (tmp_path / "data.js").read_text(encoding="utf-8")
    data = json.loads(text[len("window.LB_DATA = "):].rstrip().rstrip(";"))
    assert [p["id"] for p in data["policies"]] == MAIN_POLICIES
    assert set(data["summary"]) == {s["id"] for s in data["scenarios"]}
    assert set(data["summary"]["gray_failure"]) == set(MAIN_POLICIES)
    assert data["summary"]["gray_failure"]["ased"]["p99"][0] > 0
    crash = data["series"]["server_crash"]["ased"]
    assert len(crash["p95"]) == len(crash["err"]) >= int(data["duration"])


def test_demo_page_files_exist():
    html = (ROOT / "demo" / "index.html").read_text(encoding="utf-8")
    for name in ("data.js", "app.js", "style.css"):
        assert name in html and (ROOT / "demo" / name).exists()
