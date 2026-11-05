from dataclasses import dataclass


@dataclass(frozen=True)
class Crash:
    """Fail-stop crash; on recovery the server restarts cold and its speed ramps up."""
    servers: tuple
    at: float
    until: float = None
    warm_len: float = 15.0
    warm_from: float = 0.4


@dataclass(frozen=True)
class Slowdown:
    """Gray failure: the server keeps answering but runs at `factor` of its speed."""
    servers: tuple
    at: float
    until: float = None
    factor: float = 0.3


def expand_faults(faults):
    """Turn fault specs into a time-ordered list of (time, action, server, value)."""
    out = []
    for f in faults:
        for i in f.servers:
            if isinstance(f, Crash):
                out.append((f.at, "crash", i, None))
                if f.until is not None:
                    out.append((f.until, "recover", i, (f.warm_len, f.warm_from)))
            elif isinstance(f, Slowdown):
                out.append((f.at, "slow", i, f.factor))
                if f.until is not None:
                    out.append((f.until, "restore", i, None))
            else:
                raise TypeError(f)
    out.sort(key=lambda e: e[0])
    return out
