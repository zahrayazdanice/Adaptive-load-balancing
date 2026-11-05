"""Closed-form queueing results used to verify the simulator."""
import math

from .cluster import ServerSpec
from .scenarios import Scenario
from .workload import Workload


def erlang_c(c, a):
    """Probability that an arrival waits in M/M/c with offered load a = lambda / mu."""
    head = sum(a ** k / math.factorial(k) for k in range(c))
    tail = a ** c / math.factorial(c) * c / (c - a)
    return tail / (head + tail)


def mmc_response(lam, mu, c):
    return erlang_c(c, lam / mu) / (c * mu - lam) + 1.0 / mu


def mg1_response(lam, scv, es=1.0):
    """Pollaczek-Khinchine mean response time."""
    rho = lam * es
    return es + lam * es ** 2 * (1 + scv) / (2 * (1 - rho))


def mm1k_blocking(rho, k):
    """Blocking probability of M/M/1/K (K = total places in the system)."""
    if rho == 1:
        return 1.0 / (k + 1)
    return (1 - rho) * rho ** k / (1 - rho ** (k + 1))


def queue_scenario(name, workers=1, load=0.5, service="exp", cv=1.0, n_servers=1,
                   queue_cap=10 ** 7, duration=20000.0):
    servers = tuple(ServerSpec(workers, 1.0, queue_cap) for _ in range(n_servers))
    return Scenario(name, servers, Workload(load=load, service=service, cv=cv),
                    duration=duration, warmup=0.05 * duration, drain=0.05 * duration,
                    mean_service=1.0, net_delay=0.0, dispatchers=1,
                    health_interval=50.0, report_interval=50.0, slo=1e9)


def cases(duration=20000.0):
    """(scenario, metric, analytic value) triples; time unit = mean service time."""
    d = duration
    return [
        (queue_scenario("M/M/1 rho=0.5", load=0.5, duration=d), "mean", 2.0),
        (queue_scenario("M/M/1 rho=0.8", load=0.8, duration=d), "mean", 5.0),
        (queue_scenario("M/M/4 rho=0.8", workers=4, load=0.8, duration=d), "mean",
         mmc_response(3.2, 1.0, 4)),
        (queue_scenario("M/D/1 rho=0.7", load=0.7, service="det", duration=d), "mean",
         mg1_response(0.7, 0.0)),
        (queue_scenario("M/G/1 lognormal cv=1.5 rho=0.6", load=0.6, service="lognormal", cv=1.5,
                        duration=d), "mean", mg1_response(0.6, 1.5 ** 2)),
        (queue_scenario("M/M/1/5 rho=0.9 (blocking)", load=0.9, queue_cap=4, duration=d),
         "error_rate", mm1k_blocking(0.9, 5)),
        (queue_scenario("4 x M/M/1, random split, rho=0.7", load=0.7, n_servers=4, duration=d),
         "mean", 1.0 / (1.0 - 0.7)),
        (queue_scenario("M/M/4 rho=0.8 (utilization)", workers=4, load=0.8, duration=d),
         "util_mean", 0.8),
    ]
