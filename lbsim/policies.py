"""Load-balancing policies.

Each dispatcher (load-balancer replica) owns one policy instance. A policy sees
`lb.eligible` (servers that passed health checks and are not ejected), `lb.out`
(requests this dispatcher has in flight per server) and, if `feedback` is set,
every response that comes back to its own dispatcher.
"""
import math

OK = 1


class Policy:
    feedback = False   # receives on_response

    def __init__(self, ctx, lb, rng):
        self.ctx = ctx
        self.lb = lb
        self.rng = rng
        self.n = ctx.n

    def choose(self, t):
        raise NotImplementedError

    def on_response(self, t, i, code, rtt, svc, qlen):
        pass

    def _argmin(self, cands, key):
        best, bv, ties = -1, math.inf, 0
        r = self.rng.random
        for i in cands:
            v = key(i)
            if v < bv:
                best, bv, ties = i, v, 1
            elif v == bv:
                ties += 1
                if r() * ties < 1.0:
                    best = i
        return best

    def _two(self):
        el = self.lb.eligible
        m = len(el)
        r = self.rng.random
        a = int(r() * m)
        b = int(r() * (m - 1))
        if b >= a:
            b += 1
        return el[a], el[b]


class RoundRobin(Policy):
    def __init__(self, ctx, lb, rng):
        super().__init__(ctx, lb, rng)
        self.ptr = rng.randrange(self.n)

    def choose(self, t):
        mask, n, i = self.lb.mask, self.n, self.ptr
        for _ in range(n):
            if mask[i]:
                break
            i = (i + 1) % n
        self.ptr = (i + 1) % n
        return i


class WeightedRoundRobin(Policy):
    """Smooth weighted round robin (the nginx algorithm) with static capacity weights."""

    def __init__(self, ctx, lb, rng):
        super().__init__(ctx, lb, rng)
        self.w = list(ctx.weights)
        self.cw = [0.0] * self.n
        for _ in range(rng.randrange(4 * self.n)):
            self.choose(0.0)

    def choose(self, t):
        w, cw = self.w, self.cw
        best, bv, total = -1, -math.inf, 0.0
        for i in self.lb.eligible:
            c = cw[i] + w[i]
            cw[i] = c
            total += w[i]
            if c > bv:
                best, bv = i, c
        cw[best] -= total
        return best


class LeastConnections(Policy):
    def choose(self, t):
        out = self.lb.out
        return self._argmin(self.lb.eligible, out.__getitem__)


class PowerOfD(Policy):
    """Sample d servers uniformly, send to the one with fewest in-flight requests.

    d = 2 is the power of two choices; d = 1 is uniform random routing.
    """

    def __init__(self, ctx, lb, rng, d=2):
        super().__init__(ctx, lb, rng)
        self.d = int(d)

    def choose(self, t):
        el, out = self.lb.eligible, self.lb.out
        if self.d == 1:
            return el[int(self.rng.random() * len(el))]
        if len(el) == 1:
            return el[0]
        if self.d == 2:
            a, b = self._two()
            if out[a] != out[b]:
                return a if out[a] < out[b] else b
            return a if self.rng.random() < 0.5 else b
        cands = el if self.d >= len(el) else self.rng.sample(el, self.d)
        return self._argmin(cands, out.__getitem__)


class LeastResponseTime(Policy):
    """argmin EWMA(response time) * (in_flight + 1), full scan (NGINX Plus / Citrix style)."""
    feedback = True

    def __init__(self, ctx, lb, rng, alpha=0.1):
        super().__init__(ctx, lb, rng)
        self.alpha = alpha
        self.ewma = [0.0] * self.n

    def on_response(self, t, i, code, rtt, svc, qlen):
        if code == OK:
            e = self.ewma[i]
            self.ewma[i] = rtt if e == 0.0 else e + self.alpha * (rtt - e)

    def choose(self, t):
        out, ew = self.lb.out, self.ewma
        return self._argmin(self.lb.eligible, lambda i: ew[i] * (out[i] + 1))


class ASED(Policy):
    """Adaptive Shortest Expected Delay (the policy proposed in this project).

    Every dispatcher scores each eligible server by the expected delay of one
    more request and sends the request to the smallest score:

        score_i = S_i * (D * o_i + 1) / c_i / (1 - e_i)

    S_i  processing time piggybacked by server i (server-side log-EWMA), so
         speed differences, slowdowns and cold starts are learned online
    o_i  requests this dispatcher has in flight to i; with D replicas sharing
         the traffic, D * o_i estimates the server's queue (as in C3)
    c_i  worker count of server i, known from service discovery
    e_i  time-decaying error rate seen by this dispatcher (connection failures
         and rejections), so a fast-failing server cannot become a black hole

    The keyword switches reproduce the variants of the design exploration and
    the ablation study (sampling, FCFS form, no learning, no compensation, ...).
    """
    feedback = True

    def __init__(self, ctx, lb, rng, beta=0.5, tau=2.0, max_err=0.95, d=0, weighted=1,
                 form="lin", learn=1, comp=1, qfb=0):
        super().__init__(ctx, lb, rng)
        self.beta, self.tau, self.max_err = beta, tau, max_err
        self.d, self.weighted, self.form = int(d), bool(weighted), form
        self.learn, self.qfb = bool(learn), bool(qfb)
        self.c = list(ctx.workers)
        self.D = ctx.dispatchers if comp else 1
        ms = ctx.mean_service
        self.S = [ms] * self.n if self.learn else [ms / s for s in ctx.speeds]
        self.err = [0.0] * self.n
        self.terr = [0.0] * self.n
        self.fb = [0] * self.n
        self.sent = [0] * self.n

    def on_response(self, t, i, code, rtt, svc, qlen):
        if code == OK:
            if self.learn:
                self.S[i] = svc
            if self.qfb:
                self.fb[i], self.sent[i] = qlen, 0
        if self.beta > 0:
            e = self.err[i]
            if e > 0.0:
                e *= math.exp(-(t - self.terr[i]) / self.tau)
            self.err[i] = e + self.beta * ((code != OK) - e)
            self.terr[i] = t

    def score(self, i, t):
        c, s = self.c[i], self.S[i]
        n = self.fb[i] + self.sent[i] if self.qfb else self.D * self.lb.out[i]
        if self.form == "lin":
            est = s * (n + 1) / c
        else:
            q = n + 1 - c
            est = s * (1.0 + q / c) if q > 0 else s
        e = self.err[i]
        if e > 1e-4:
            e *= math.exp(-(t - self.terr[i]) / self.tau)
            est /= 1.0 - min(e, self.max_err)
        return est

    def _sample2(self):
        el = self.lb.eligible
        if not self.weighted:
            return self._two()
        ws = [self.c[i] / self.S[i] for i in el]
        tot = sum(ws)
        r = self.rng.random
        x, ia = r() * tot, len(el) - 1
        for j, w in enumerate(ws):
            x -= w
            if x < 0:
                ia = j
                break
        x, ib = r() * (tot - ws[ia]), (ia - 1 if ia > 0 else 1)
        for j, w in enumerate(ws):
            if j != ia:
                x -= w
                if x < 0:
                    ib = j
                    break
        return el[ia], el[ib]

    def choose(self, t):
        el = self.lb.eligible
        if len(el) == 1:
            i = el[0]
        elif self.d == 0 or self.d >= len(el):
            i = self._argmin(el, lambda j: self.score(j, t))
        else:
            a, b = self._sample2()
            sa, sb = self.score(a, t), self.score(b, t)
            if sa != sb:
                i = a if sa < sb else b
            else:
                i = a if self.rng.random() < 0.5 else b
        if self.qfb:
            self.sent[i] += 1
        return i


POLICIES = {
    "rr": RoundRobin,
    "wrr": WeightedRoundRobin,
    "lc": LeastConnections,
    "p2c": PowerOfD,
    "lrt": LeastResponseTime,
    "ased": ASED,
}

LABELS = {"rr": "RR", "wrr": "WRR", "lc": "LC", "p2c": "P2C", "lrt": "LRT", "ased": "ASED"}

FAMILIES = {"rr": "static", "wrr": "static", "lc": "load-aware", "p2c": "load-aware",
            "lrt": "latency-aware", "ased": "proposed"}

MAIN_POLICIES = list(POLICIES)


def parse_spec(spec):
    """'ased:learn=0,d=12' -> ('ased', {'learn': 0, 'd': 12})"""
    name, _, rest = spec.partition(":")
    params = {}
    for kv in filter(None, rest.split(",")):
        k, v = kv.split("=")
        for cast in (int, float, str):
            try:
                params[k] = cast(v)
                break
            except ValueError:
                pass
    return name, params


def make_policy(spec, ctx, lb, rng):
    name, params = parse_spec(spec)
    return POLICIES[name](ctx, lb, rng, **params)


def label(spec):
    name, params = parse_spec(spec)
    base = LABELS.get(name, name)
    if not params:
        return base
    return base + "(" + ",".join(f"{k}={v}" for k, v in params.items()) + ")"
