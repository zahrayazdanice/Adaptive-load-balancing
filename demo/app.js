(() => {
  "use strict";
  const D = window.LB_DATA;
  const NS = "http://www.w3.org/2000/svg";
  const $ = (id) => document.getElementById(id);

  const RULES = {
    rr: "Round robin: every server in turn. Ignores load and server speed.",
    wrr: "Weighted round robin: turns in proportion to each server's configured capacity.",
    lc: "Least connections: the server with the fewest requests in flight.",
    p2c: "Power of two choices: pick two servers at random and use the less busy one.",
    lrt: "Least response time: recent latency multiplied by (requests in flight + 1), lowest wins.",
    ased: "Proposed in this project: learned service time × estimated queue ÷ workers, " +
      "with a penalty for servers that recently returned errors.",
  };
  const SHORT = {
    baseline: "Baseline", heterogeneous: "Heterogeneous", bursty: "Bursty traffic",
    flash_crowd: "Flash crowd", server_crash: "Server crash", gray_failure: "Gray failure",
  };
  const STORY = {
    baseline: "12 identical servers, steady random traffic at 80% of capacity.",
    heterogeneous: "Three server generations (slow, medium, fast) with the same total capacity, at 80% load.",
    bursty: "Traffic arrives in bursts, and request sizes are heavy-tailed: the largest are 1000 times the smallest.",
    flash_crowd: "Traffic jumps by 75% for 10 seconds (60 to 70 s), briefly more than the cluster can serve.",
    server_crash: "Two of the 12 servers crash at 50 s and come back cold at 90 s.",
    gray_failure: "Three servers silently slow down to 30% speed between 50 s and 90 s.",
  };
  const METRICS = {
    p99: { name: "P99 response time", unit: " ms", scale: 1000, digits: 0, button: "P99" },
    mean: { name: "Mean response time", unit: " ms", scale: 1000, digits: 1, button: "Mean" },
    error_rate: { name: "Failed requests", unit: "%", scale: 100, digits: 2, button: "Errors" },
  };
  const VIEWS = { p95: "Latency", err: "Errors" };

  const pol = Object.fromEntries(D.policies.map((p) => [p.id, p]));
  const scen = Object.fromEntries(D.scenarios.map((s) => [s.id, s]));
  const theme = new URLSearchParams(location.search).get("theme");
  if (theme === "dark" || theme === "light") document.documentElement.dataset.theme = theme;
  const start = location.hash.slice(1);
  const state = { scenario: scen[start] ? start : "server_crash", metric: "p99", view: "p95" };

  const isDark = () => {
    const t = document.documentElement.dataset.theme;
    return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  };
  const color = (id) => (isDark() ? pol[id].dark : pol[id].color);
  const fmt = (v, d) => v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const names = (ids) => ids.length < 2 ? ids.join("")
    : ids.slice(0, -1).join(", ") + " and " + ids[ids.length - 1];

  function svgEl(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function svgText(parent, x, y, s, attrs) {
    const t = svgEl("text", Object.assign({ x, y }, attrs), parent);
    t.textContent = s;
    return t;
  }
  function swatch(id) {
    const s = document.createElement("i");
    s.className = "sw";
    s.style.background = color(id);
    return s;
  }
  function node(tag, text, cls) {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  }

  const tip = $("tip");
  function showTip(evt, children) {
    tip.replaceChildren(...children);
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let x = evt.clientX + 14, y = evt.clientY + 14;
    if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - 14;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  }
  const hideTip = () => { tip.hidden = true; };
  function tipRow(id, value) {
    const row = node("div", undefined, "row");
    row.append(swatch(id), node("span", pol[id].label), node("span", value));
    return row;
  }

  function buttons(box, items, current, pick) {
    box.replaceChildren();
    for (const [id, label] of items) {
      const b = node("button", label);
      b.type = "button";
      b.setAttribute("aria-pressed", String(id === current));
      b.addEventListener("click", () => pick(id));
      box.appendChild(b);
    }
  }

  function renderControls() {
    buttons($("scenarios"), D.scenarios.map((s) => [s.id, SHORT[s.id] || s.label]), state.scenario, (id) => {
      state.scenario = id;
      location.replace("#" + id);
      render();
    });
    buttons($("metrics"), Object.entries(METRICS).map(([k, m]) => [k, m.button]), state.metric, (k) => {
      state.metric = k;
      renderControls();
      renderBars();
    });
    buttons($("views"), Object.entries(VIEWS), state.view, (k) => {
      state.view = k;
      renderControls();
      renderLine();
    });
    $("about").textContent = STORY[state.scenario] || scen[state.scenario].about;
  }

  function barPath(x0, x1, y, h, r) {
    r = Math.min(r, (x1 - x0) / 2, h / 2);
    return `M${x0},${y}H${x1 - r}A${r},${r} 0 0 1 ${x1},${y + r}V${y + h - r}` +
      `A${r},${r} 0 0 1 ${x1 - r},${y + h}H${x0}Z`;
  }

  function renderBars() {
    const m = METRICS[state.metric];
    const S = D.summary[state.scenario];
    const rows = D.policies.map((p) => {
      const [v, ci] = S[p.id][state.metric];
      return { id: p.id, v: v * m.scale, ci: (ci || 0) * m.scale };
    }).sort((a, b) => a.v - b.v);

    $("bars-title").textContent = m.name;
    const tied = rows.filter((r) => r.v === rows[0].v).map((r) => pol[r.id].label);
    const whiskers = ` Whiskers: 95% confidence interval over ${D.seeds} runs.`;
    let hint;
    if (rows.every((r) => r.v === 0)) {
      hint = "No algorithm lost a request in this scenario.";
    } else if (tied.length > 1) {
      hint = `Lower is better. Best here: ${names(tied)} (${fmt(rows[0].v, m.digits)}${m.unit}).` + whiskers;
    } else {
      hint = `Lower is better. Best here: ${tied[0]} (${fmt(rows[0].v, m.digits)}${m.unit}), ` +
        `then ${pol[rows[1].id].label} (${fmt(rows[1].v, m.digits)}${m.unit}).` + whiskers;
    }
    $("bars-hint").textContent = hint;

    const box = $("bars");
    const W = Math.max(280, box.clientWidth);
    const rowH = 34, barH = 18, L = 52, R = 84, top = 2;
    const H = top * 2 + rows.length * rowH;
    const vmax = Math.max(...rows.map((r) => r.v + r.ci)) || 1;
    const sx = (v) => L + (W - L - R) * (v / vmax);
    const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `${m.name} by algorithm, best first` });
    rows.forEach((r, k) => {
      const yc = top + k * rowH + rowH / 2;
      const g = svgEl("g", {}, svg);
      svgEl("rect", { x: 0, y: yc - rowH / 2, width: W, height: rowH, rx: 6, class: "hit" }, g);
      svgText(g, L - 10, yc + 4.5, pol[r.id].label, { "text-anchor": "end", class: "t-ink",
        "font-size": 13, "font-weight": r.id === "ased" ? 700 : 500 });
      if (r.v > 0) svgEl("path", { d: barPath(L, sx(r.v), yc - barH / 2, barH, 4), fill: color(r.id) }, g);
      if (r.ci > 0) {
        svgEl("line", { x1: sx(Math.max(0, r.v - r.ci)), x2: sx(r.v + r.ci), y1: yc, y2: yc,
          class: "whisker" }, g);
      }
      svgText(g, sx(r.v + r.ci) + 6, yc + 4.5, fmt(r.v, m.digits) + m.unit, { class: "t-ink2", "font-size": 12.5 });
      const show = (e) => showTip(e, [
        node("b", pol[r.id].label),
        node("div", `${m.name}: ${fmt(r.v, m.digits)}${m.unit}`),
        node("div", `95% CI: ± ${fmt(r.ci, m.digits)}${m.unit} (${D.seeds} runs)`),
        node("div", `Rank ${k + 1} of ${rows.length}`),
      ]);
      g.addEventListener("pointermove", show);
      g.addEventListener("pointerdown", show);
      g.addEventListener("pointerleave", hideTip);
    });
    svgEl("line", { x1: L, x2: L, y1: 0, y2: H, class: "axis" }, svg);
    box.replaceChildren(svg);
  }

  function dashArray(id, w) {
    return pol[id].dash.length ? pol[id].dash.map((x) => x * w).join(" ") : "";
  }

  function renderLegend() {
    const box = $("legend");
    box.replaceChildren();
    for (const p of D.policies) {
      const item = node("span");
      const s = svgEl("svg", { width: 24, height: 10, "aria-hidden": "true" });
      svgEl("line", { x1: 1, x2: 23, y1: 5, y2: 5, stroke: color(p.id), "stroke-width": 2.4,
        "stroke-dasharray": dashArray(p.id, 2.4) }, s);
      item.append(s, p.label);
      box.appendChild(item);
    }
  }

  function niceTicks(max) {
    const raw = max / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= raw);
    const out = [];
    for (let v = 0; v <= Math.ceil(max / step) * step + 1e-9; v += step) out.push(+v.toFixed(6));
    return out;
  }

  function renderLine() {
    const S = D.series[state.scenario];
    const sc = scen[state.scenario];
    const key = state.view;
    const t0 = D.warmup, t1 = D.duration;
    const ids = D.policies.map((p) => p.id);
    const box = $("line");
    const W = Math.max(280, box.clientWidth);
    const H = W < 520 ? 240 : 300;
    const L = 46, R = 10, T = 28, B = 26;

    let lo = Infinity, hi = 0;
    for (const id of ids) {
      for (let t = t0; t < t1; t++) {
        const v = S[id][key][t];
        if (v == null) continue;
        lo = Math.min(lo, v);
        hi = Math.max(hi, v);
      }
    }
    let ticks, sy, dlo, dhi;
    if (key === "p95") {
      const cand = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000];
      dlo = Math.max(...cand.filter((c) => c <= Math.max(10, lo * 0.9)));
      dhi = Math.min(...cand.filter((c) => c >= hi * 1.05));
      ticks = cand.filter((c) => c >= dlo && c <= dhi);
      const a = Math.log(dlo), b = Math.log(dhi);
      sy = (v) => T + (H - T - B) * (1 - (Math.log(Math.min(dhi, Math.max(dlo, v))) - a) / (b - a));
    } else {
      ticks = niceTicks(Math.max(1, hi));
      dlo = 0;
      dhi = ticks[ticks.length - 1];
      sy = (v) => T + (H - T - B) * (1 - v / dhi);
    }
    const sx = (t) => L + (W - L - R) * (t - t0) / (t1 - t0);
    const unit = key === "p95" ? " ms" : "%";

    const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": key === "p95" ? "P95 response time per second, one run" : "Error rate per second, one run" });
    for (const [a, b, label] of sc.shade) {
      svgEl("rect", { x: sx(a), y: T, width: sx(b) - sx(a), height: H - T - B, class: "shade" }, svg);
      svgText(svg, sx(a) + 4, T - 7, label, { class: "t-ink2", "font-size": 12 });
    }
    for (const v of ticks) {
      svgEl("line", { x1: L, x2: W - R, y1: sy(v), y2: sy(v), class: v === dlo && key !== "p95" ? "axis" : "grid" }, svg);
      svgText(svg, L - 6, sy(v) + 4, fmt(v, v % 1 ? 1 : 0), { "text-anchor": "end", class: "t-muted", "font-size": 11.5 });
    }
    svgText(svg, L - 6, T - 13, key === "p95" ? "ms" : "%", { "text-anchor": "end", class: "t-muted", "font-size": 11.5 });
    for (let t = t0; t <= t1; t += 20) {
      svgText(svg, sx(t), H - 6, t === t1 ? `${t} s` : String(t), { "text-anchor": t === t1 ? "end" : "middle",
        class: "t-muted", "font-size": 11.5 });
    }

    const order = ids.filter((id) => id !== "ased").concat(["ased"]);
    for (const id of order) {
      let d = "", pen = false;
      for (let t = t0; t < t1; t++) {
        const v = S[id][key][t];
        if (v == null) { pen = false; continue; }
        d += (pen ? "L" : "M") + sx(t + 0.5).toFixed(1) + "," + sy(v).toFixed(1);
        pen = true;
      }
      const w = id === "ased" ? 2.4 : 1.6;
      const dash = dashArray(id, w);
      svgEl("path", { d, fill: "none", stroke: color(id), "stroke-width": w, "stroke-linejoin": "round",
        "stroke-linecap": dash ? "butt" : "round", "stroke-dasharray": dash }, svg);
    }

    const cross = svgEl("line", { y1: T, y2: H - B, class: "cross", visibility: "hidden" }, svg);
    const dots = ids.map((id) => svgEl("circle", { r: 3.5, fill: color(id), class: "dot", visibility: "hidden" }, svg));
    const hit = svgEl("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" }, svg);
    const move = (e) => {
      const r = svg.getBoundingClientRect();
      const t = t0 + (e.clientX - r.left - L) / (W - L - R) * (t1 - t0);
      const i = Math.min(t1 - 1, Math.max(t0, Math.floor(t)));
      const x = sx(i + 0.5);
      cross.setAttribute("x1", x);
      cross.setAttribute("x2", x);
      cross.setAttribute("visibility", "visible");
      ids.forEach((id, k) => {
        const v = S[id][key][i];
        dots[k].setAttribute("visibility", v == null ? "hidden" : "visible");
        if (v != null) {
          dots[k].setAttribute("cx", x);
          dots[k].setAttribute("cy", sy(v));
        }
      });
      const band = sc.shade.find(([a, b]) => i >= a && i < b);
      const rows = ids.filter((id) => S[id][key][i] != null).sort((a, b) => S[a][key][i] - S[b][key][i]);
      showTip(e, [node("b", `${i} to ${i + 1} s` + (band ? `, ${band[2]}` : "")),
        ...rows.map((id) => tipRow(id, fmt(S[id][key][i], key === "p95" ? 0 : 1) + unit))]);
    };
    const leave = () => {
      cross.setAttribute("visibility", "hidden");
      dots.forEach((c) => c.setAttribute("visibility", "hidden"));
      hideTip();
    };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", leave);
    box.replaceChildren(svg);

    const what = key === "p95"
      ? "P95 response time of the requests that arrived in each second (log scale)."
      : "Share of the requests arriving in each second that failed or were rejected.";
    $("line-hint").textContent = `One run (seed 0). ${what}` +
      (sc.shade.length ? ` Shaded: ${sc.shade.map((s) => s[2]).join(", ")}.` : "");
  }

  function renderTable() {
    const S = D.summary[state.scenario];
    const cols = [
      ["mean", "Mean (ms)", 1000, 1, "min"],
      ["p95", "P95 (ms)", 1000, 0, "min"],
      ["p99", "P99 (ms)", 1000, 0, "min"],
      ["error_rate", "Errors (%)", 100, 2, "min"],
      ["throughput", "Throughput (req/s)", 1, 0, "max"],
    ];
    const best = {};
    for (const [k, , , , dir] of cols) {
      const vals = D.policies.map((p) => S[p.id][k][0]);
      const b = dir === "min" ? Math.min(...vals) : Math.max(...vals);
      best[k] = vals.every((v) => v === vals[0]) ? null : b;
    }
    const table = $("table");
    table.replaceChildren();
    const head = table.createTHead().insertRow();
    for (const h of ["Algorithm"].concat(cols.map((c) => c[1]))) head.appendChild(node("th", h));
    const body = table.createTBody();
    for (const p of D.policies) {
      const tr = body.insertRow();
      const name = node("span", undefined, "name");
      name.append(swatch(p.id), p.label);
      tr.insertCell().appendChild(name);
      for (const [k, , scale, digits] of cols) {
        const v = S[p.id][k][0];
        const td = tr.insertCell();
        td.textContent = fmt(v * scale, digits);
        if (best[k] !== null && v === best[k]) td.className = "best";
      }
    }
    $("table-hint").textContent = `Each number is the mean of ${D.seeds} runs with different random seeds; ` +
      "in each run all six algorithms receive exactly the same requests. Bold: best in the column.";
  }

  function renderAlgos() {
    const dl = $("algos");
    dl.replaceChildren();
    for (const p of D.policies) {
      const dt = node("dt");
      dt.append(swatch(p.id), p.label);
      dl.append(dt, node("dd", RULES[p.id]));
    }
  }

  function render() {
    renderControls();
    renderBars();
    renderLegend();
    renderLine();
    renderTable();
    renderAlgos();
  }

  $("foot").textContent = `Results generated on ${D.generated} by the lbsim simulator: ${D.seeds} runs of ` +
    `${D.duration} s per scenario, the first ${D.warmup} s of each run discarded as warm-up. ` +
    "Regenerate with: python -m lbsim run all, then python -m lbsim analyze.";
  render();

  let timer;
  addEventListener("resize", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { renderBars(); renderLine(); }, 120);
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
})();
