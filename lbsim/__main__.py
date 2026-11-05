import argparse
import functools
import http.server
import webbrowser

ORDER = ["validation", "design", "main", "sensitivity", "ablation", "failure"]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve_demo(folder, port, open_browser):
    handler = functools.partial(_QuietHandler, directory=folder)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://localhost:{port}/"
        print(f"demo running at {url}  (Ctrl+C to stop)", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("stopped")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m lbsim", description="Load-balancing study")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run experiments")
    r.add_argument("names", nargs="+", choices=ORDER + ["all"])
    r.add_argument("--seeds", type=int, help="number of seeds (default: experiment setting)")
    r.add_argument("--workers", type=int)
    r.add_argument("--out", default="results")

    a = sub.add_parser("analyze", help="tables, figures and demo data from results/")
    a.add_argument("--out", default="results")

    d = sub.add_parser("demo", help="serve the demo page locally and open it in the browser")
    d.add_argument("--port", type=int, default=8000)
    d.add_argument("--dir", default="demo")
    d.add_argument("--no-browser", action="store_true")

    s = sub.add_parser("simulate", help="run one scenario/policy and print metrics")
    s.add_argument("--scenario", default="heterogeneous")
    s.add_argument("--policy", default="ased")
    s.add_argument("--seed", type=int, default=0)

    args = ap.parse_args(argv)
    if args.cmd == "run":
        from .experiments import run_experiment
        names = ORDER if "all" in args.names else args.names
        for name in names:
            seeds = None
            if args.seeds:
                seeds = range(1000, 1000 + args.seeds) if name == "design" else range(args.seeds)
            run_experiment(name, args.out, seeds, args.workers)
    elif args.cmd == "analyze":
        from .analysis import analyze_all
        analyze_all(args.out)
    elif args.cmd == "demo":
        serve_demo(args.dir, args.port, not args.no_browser)
    elif args.cmd == "simulate":
        from .engine import simulate
        from .metrics import summarize
        from .scenarios import get_scenario
        sc = get_scenario(args.scenario)
        row = summarize(simulate(sc, args.policy, args.seed), sc)
        for k, v in row.items():
            print(f"{k:20s} {v:.4f}" if isinstance(v, float) else f"{k:20s} {v}")


if __name__ == "__main__":
    main()
