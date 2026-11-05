from dataclasses import dataclass


@dataclass(frozen=True)
class ServerSpec:
    workers: int
    speed: float
    queue_cap: int
    kind: str = "std"

    @property
    def capacity(self):
        return self.workers * self.speed


def make_server(workers, speed, kind="std", queue_per_worker=16):
    return ServerSpec(workers, speed, workers * queue_per_worker, kind)


def homogeneous(n=12, workers=4, speed=1.0):
    return tuple(make_server(workers, speed, "std") for _ in range(n))


def heterogeneous():
    # three hardware generations, total capacity 48 worker-units (same as homogeneous)
    small = [make_server(2, 0.8, "small")] * 4
    medium = [make_server(4, 1.0, "medium")] * 5
    large = [make_server(6, 1.2, "large")] * 3
    return tuple(small + medium + large)


def speed_spread(ratio, n=12, workers=4):
    # geometric speeds between 1 and `ratio`, rescaled to mean 1
    if ratio == 1:
        return homogeneous(n, workers)
    raw = [ratio ** (i / (n - 1)) for i in range(n)]
    m = sum(raw) / n
    return tuple(make_server(workers, r / m, "spread") for r in raw)


def total_capacity(servers):
    return sum(s.capacity for s in servers)
