"""Discrete-event simulation of a cluster behind several load-balancer replicas.

Life of a request: arrival at a dispatcher -> policy picks a server -> network
hop -> server (start, queue, or reject when the queue is full) -> completion ->
network hop -> response at the dispatcher. Crashed servers reset connections
(or swallow them in blackhole mode); a shared active health checker removes
them after `health_fall` failed probes.
"""
import heapq
import math
import random
import time
from collections import deque
from dataclasses import dataclass
from itertools import count
from types import SimpleNamespace

import numpy as np

from .faults import expand_faults
from .policies import make_policy

PENDING, OK, REJECTED, FAILED = 0, 1, 2, 3
_ARRIVE, _DEPART, _RESPONSE, _HEALTH, _SAMPLE, _FAULT, _UNEJECT = range(7)
INF = math.inf


class Server:
    __slots__ = ("idx", "workers", "speed", "queue_cap", "busy", "queue", "running", "up",
                 "factor", "warm_t0", "warm_t1", "warm_from", "epoch", "area", "last_t",
                 "log_svc", "log_prior")

    def __init__(self, idx, spec, mean_service):
        self.idx = idx
        self.workers = spec.workers
        self.speed = spec.speed
        self.queue_cap = spec.queue_cap
        self.busy = 0
        self.queue = deque()
        self.running = set()
        self.up = True
        self.factor = 1.0
        self.warm_t0 = self.warm_t1 = -1.0
        self.warm_from = 1.0
        self.epoch = 0
        self.area = 0.0
        self.last_t = 0.0
        self.log_prior = math.log(mean_service)
        self.log_svc = self.log_prior

    def rate(self, t):
        r = self.speed * self.factor
        if t < self.warm_t1:
            frac = (t - self.warm_t0) / (self.warm_t1 - self.warm_t0)
            r *= self.warm_from + (1.0 - self.warm_from) * frac
        return r

    def in_system(self):
        return self.busy + len(self.queue)


class Dispatcher:
    __slots__ = ("idx", "out", "eligible", "mask", "ejected_until", "fails", "n_ejected", "policy")

    def __init__(self, idx, n):
        self.idx = idx
        self.out = [0] * n
        self.eligible = list(range(n))
        self.mask = [True] * n
        self.ejected_until = [-INF] * n
        self.fails = [0] * n
        self.n_ejected = 0
        self.policy = None


@dataclass
class RunResult:
    times: np.ndarray
    t_resp: np.ndarray
    status: np.ndarray
    server: np.ndarray
    svc: np.ndarray
    report_t: np.ndarray
    util: np.ndarray       # [window, server] busy fraction
    queue: np.ndarray      # [window, server] waiting requests at report time
    busy: np.ndarray       # [window, server] busy workers at report time
    up: np.ndarray         # [window, server]
    events: int
    wall: float


class Simulator:
    def __init__(self, sc, policy, seed=0, trace=None):
        self.sc = sc
        self.policy_spec = policy
        n = len(sc.servers)
        self.n = n
        if trace is None:
            trace = sc.trace(seed)
        self.times = trace.times.tolist()
        self.work = trace.work.tolist()
        self.disp = trace.disp.tolist()
        m = len(self.times)
        self.srv_of = [-1] * m
        self.t_resp = [math.nan] * m
        self.status = [PENDING] * m
        self.svc = [math.nan] * m

        self.servers = [Server(i, s, sc.mean_service) for i, s in enumerate(sc.servers)]
        self.healthy = [True] * n
        self.hc_ok = [0] * n
        self.hc_fail = [0] * n
        self.ctx = SimpleNamespace(
            n=n,
            workers=[s.workers for s in sc.servers],
            speeds=[s.speed for s in sc.servers],
            weights=[s.capacity for s in sc.servers],
            mean_service=sc.mean_service,
            dispatchers=sc.dispatchers,
        )
        base = int(np.random.SeedSequence([seed, 11]).generate_state(1)[0])
        self.lbs = []
        for d in range(sc.dispatchers):
            lb = Dispatcher(d, n)
            lb.policy = make_policy(policy, self.ctx, lb, random.Random(base + 7919 * d))
            self.lbs.append(lb)
        self.feedback = self.lbs[0].policy.feedback

        self.heap = []
        self.seq = count()
        self.prev_area = [0.0] * n
        self.series = {"t": [], "util": [], "queue": [], "busy": [], "up": []}
        push = heapq.heappush
        push(self.heap, (sc.health_interval, next(self.seq), _HEALTH))
        push(self.heap, (sc.report_interval, next(self.seq), _SAMPLE))
        for t, action, i, value in expand_faults(sc.faults):
            push(self.heap, (t, next(self.seq), _FAULT, action, i, value))

    # ---- control-plane events -------------------------------------------------

    def _refresh(self, lb, t):
        el = [i for i in range(self.n) if self.healthy[i] and lb.ejected_until[i] <= t]
        if not el:
            el = list(range(self.n))
        lb.eligible[:] = el
        mask = lb.mask
        for i in range(self.n):
            mask[i] = False
        for i in el:
            mask[i] = True

    def _health(self, t):
        sc = self.sc
        changed = False
        for i, s in enumerate(self.servers):
            if s.up:
                self.hc_fail[i] = 0
                self.hc_ok[i] += 1
                if not self.healthy[i] and self.hc_ok[i] >= sc.health_rise:
                    self.healthy[i] = True
                    changed = True
            else:
                self.hc_ok[i] = 0
                self.hc_fail[i] += 1
                if self.healthy[i] and self.hc_fail[i] >= sc.health_fall:
                    self.healthy[i] = False
                    changed = True
        if changed:
            for lb in self.lbs:
                self._refresh(lb, t)
        nt = t + sc.health_interval
        if nt <= self.t_stop:
            heapq.heappush(self.heap, (nt, next(self.seq), _HEALTH))

    def _sample(self, t):
        """Monitoring only: per-server utilization, queue and state once per interval."""
        R = self.sc.report_interval
        util, queue, busy, up = [], [], [], []
        for i, s in enumerate(self.servers):
            s.area += s.busy * (t - s.last_t)
            s.last_t = t
            util.append((s.area - self.prev_area[i]) / (s.workers * R))
            self.prev_area[i] = s.area
            queue.append(len(s.queue))
            busy.append(s.busy)
            up.append(s.up)
        ser = self.series
        ser["t"].append(t)
        ser["util"].append(util)
        ser["queue"].append(queue)
        ser["busy"].append(busy)
        ser["up"].append(up)
        nt = t + R
        if nt <= self.t_stop:
            heapq.heappush(self.heap, (nt, next(self.seq), _SAMPLE))

    def _fail_response(self, k, t):
        sc = self.sc
        tt = t + sc.net_delay
        if sc.crash_mode == "blackhole":
            tt = max(tt, self.times[k] + sc.timeout)
        heapq.heappush(self.heap, (tt, next(self.seq), _RESPONSE, k, FAILED))

    def _fault(self, t, action, i, value):
        s = self.servers[i]
        if action == "crash" and s.up:
            s.area += s.busy * (t - s.last_t)
            s.last_t = t
            victims = list(s.running) + list(s.queue)
            s.running.clear()
            s.queue.clear()
            s.busy = 0
            s.epoch += 1
            s.up = False
            for k in victims:
                self._fail_response(k, t)
        elif action == "recover" and not s.up:
            s.area += s.busy * (t - s.last_t)
            s.last_t = t
            s.up = True
            s.warm_t0, s.warm_t1 = t, t + value[0]
            s.warm_from = value[1]
            s.log_svc = s.log_prior
        elif action == "slow":
            s.factor = value
        elif action == "restore":
            s.factor = 1.0

    def _outlier(self, lb, i, code, t):
        sc = self.sc
        if code == FAILED:
            lb.fails[i] += 1
            if (lb.fails[i] >= sc.od_consecutive and lb.ejected_until[i] <= t
                    and lb.n_ejected < int(sc.od_max_fraction * self.n)):
                lb.fails[i] = 0
                lb.ejected_until[i] = t + sc.od_ejection
                lb.n_ejected += 1
                self._refresh(lb, t)
                heapq.heappush(self.heap, (t + sc.od_ejection, next(self.seq), _UNEJECT, lb.idx, i))
        elif code == OK:
            lb.fails[i] = 0

    # ---- main loop ------------------------------------------------------------

    def run(self):
        wall0 = time.perf_counter()
        sc = self.sc
        self.t_stop = sc.duration + sc.drain
        heap, seq = self.heap, self.seq
        push, pop = heapq.heappush, heapq.heappop
        times, work, disp = self.times, self.work, self.disp
        servers, lbs = self.servers, self.lbs
        srv_of, t_resp, status, svc = self.srv_of, self.t_resp, self.status, self.svc
        net, ms, a_s = sc.net_delay, sc.mean_service, sc.svc_ewma_alpha
        od, feedback, t_stop = sc.outlier_detection, self.feedback, self.t_stop
        log, exp = math.log, math.exp

        n_req = len(times)
        k = 0
        nxt = times[0] if n_req else INF
        events = 0
        while True:
            if heap and heap[0][0] <= nxt:
                ev = pop(heap)
                t = ev[0]
                if t > t_stop:
                    break
                events += 1
                kind = ev[2]
                if kind == _DEPART:
                    _, _, _, r, i, ep = ev
                    s = servers[i]
                    if ep != s.epoch:
                        continue
                    s.running.discard(r)
                    s.log_svc += a_s * (log(svc[r]) - s.log_svc)
                    push(heap, (t + net, next(seq), _RESPONSE, r, OK))
                    if s.queue:
                        r2 = s.queue.popleft()
                        st = work[r2] * ms / s.rate(t)
                        svc[r2] = st
                        s.running.add(r2)
                        push(heap, (t + st, next(seq), _DEPART, r2, i, s.epoch))
                    else:
                        s.area += s.busy * (t - s.last_t)
                        s.last_t = t
                        s.busy -= 1
                elif kind == _ARRIVE:
                    _, _, _, r, i = ev
                    s = servers[i]
                    if not s.up:
                        self._fail_response(r, t)
                    elif s.busy < s.workers:
                        s.area += s.busy * (t - s.last_t)
                        s.last_t = t
                        s.busy += 1
                        st = work[r] * ms / s.rate(t)
                        svc[r] = st
                        s.running.add(r)
                        push(heap, (t + st, next(seq), _DEPART, r, i, s.epoch))
                    elif len(s.queue) < s.queue_cap:
                        s.queue.append(r)
                    else:
                        push(heap, (t + net, next(seq), _RESPONSE, r, REJECTED))
                elif kind == _RESPONSE:
                    _, _, _, r, code = ev
                    i = srv_of[r]
                    lb = lbs[disp[r]]
                    lb.out[i] -= 1
                    t_resp[r] = t
                    status[r] = code
                    if od:
                        self._outlier(lb, i, code, t)
                    if feedback:
                        s = servers[i]
                        if code == OK:
                            lb.policy.on_response(t, i, code, t - times[r], exp(s.log_svc),
                                                  s.busy + len(s.queue))
                        else:
                            lb.policy.on_response(t, i, code, t - times[r], 0.0, -1)
                elif kind == _HEALTH:
                    self._health(t)
                elif kind == _SAMPLE:
                    self._sample(t)
                elif kind == _FAULT:
                    self._fault(t, ev[3], ev[4], ev[5])
                elif kind == _UNEJECT:
                    lb = lbs[ev[3]]
                    lb.n_ejected -= 1
                    self._refresh(lb, t)
            elif k < n_req:
                t = nxt
                lb = lbs[disp[k]]
                i = lb.policy.choose(t)
                lb.out[i] += 1
                srv_of[k] = i
                push(heap, (t + net, next(seq), _ARRIVE, k, i))
                k += 1
                nxt = times[k] if k < n_req else INF
            else:
                break

        ser = self.series
        return RunResult(
            times=np.asarray(times),
            t_resp=np.asarray(t_resp),
            status=np.asarray(status, dtype=np.int8),
            server=np.asarray(srv_of, dtype=np.int16),
            svc=np.asarray(svc),
            report_t=np.asarray(ser["t"]),
            util=np.asarray(ser["util"]),
            queue=np.asarray(ser["queue"]),
            busy=np.asarray(ser["busy"]),
            up=np.asarray(ser["up"], dtype=bool),
            events=events + n_req,
            wall=time.perf_counter() - wall0,
        )


def simulate(sc, policy, seed=0, trace=None):
    return Simulator(sc, policy, seed, trace).run()
