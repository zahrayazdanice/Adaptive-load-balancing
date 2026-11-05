from dataclasses import dataclass, replace

from .cluster import heterogeneous, homogeneous, total_capacity
from .faults import Crash, Slowdown
from .workload import Workload, generate_trace


@dataclass(frozen=True)
class Scenario:
    name: str
    servers: tuple
    workload: Workload
    title: str = ""
    duration: float = 120.0
    warmup: float = 20.0
    drain: float = 30.0
    mean_service: float = 0.05        # seconds on a speed-1.0 worker
    net_delay: float = 0.0005         # one-way LB <-> server
    dispatchers: int = 4              # independent load-balancer replicas
    health_interval: float = 1.0
    health_fall: int = 3
    health_rise: int = 2
    report_interval: float = 1.0
    svc_ewma_alpha: float = 0.05      # server-side smoothing of processing time
    faults: tuple = ()
    events: tuple = ()                # (name, start, end) analysis windows
    crash_mode: str = "refuse"        # refuse: connection reset | blackhole: request times out
    timeout: float = 1.0
    outlier_detection: bool = False
    od_consecutive: int = 5
    od_ejection: float = 10.0
    od_max_fraction: float = 0.5
    slo: float = 0.5

    @property
    def capacity(self):
        return total_capacity(self.servers)

    @property
    def arrival_rate(self):
        return self.workload.load * self.capacity / self.mean_service

    def trace(self, seed):
        return generate_trace(self.workload, self.capacity, self.mean_service,
                              self.duration, self.dispatchers, seed)

    def with_(self, **kw):
        return replace(self, **kw)

    def with_workload(self, **kw):
        return replace(self, workload=replace(self.workload, **kw))


HOM = homogeneous()
HET = heterogeneous()

# server indices in HET: 0-3 small, 4-8 medium, 9-11 large
CRASHED = (4, 9)
SLOWED = (5, 6, 10)


def main_scenarios():
    return [
        Scenario("baseline", HOM, Workload(load=0.8, service="exp"),
                 title="Homogeneous servers, Poisson arrivals, exponential service"),
        Scenario("heterogeneous", HET, Workload(load=0.8, service="lognormal", cv=1.5),
                 title="Heterogeneous servers, lognormal service (CV 1.5)"),
        Scenario("bursty", HET, Workload(load=0.7, service="pareto", arrivals="mmpp"),
                 title="MMPP bursts and heavy-tailed (bounded Pareto) service"),
        Scenario("flash_crowd", HET, Workload(load=0.6, spikes=((60.0, 70.0, 1.75),)),
                 title="Flash crowd: arrival rate x1.75 for 10 s",
                 events=(("spike", 60.0, 90.0),)),
        Scenario("server_crash", HET, Workload(load=0.7),
                 title="Two servers crash at 50 s and rejoin cold at 90 s",
                 faults=(Crash(CRASHED, 50.0, 90.0),),
                 events=(("failure", 50.0, 90.0), ("rejoin", 90.0, 120.0))),
        Scenario("gray_failure", HET, Workload(load=0.7),
                 title="Three servers slow down to 30% speed between 50 s and 90 s",
                 faults=(Slowdown(SLOWED, 50.0, 90.0, 0.3),),
                 events=(("slowdown", 50.0, 90.0), ("restore", 90.0, 120.0))),
    ]


def get_scenario(name):
    for s in main_scenarios():
        if s.name == name:
            return s
    raise KeyError(name)
