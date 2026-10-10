/* Renders window.CARBON_DATA (js/data.js). No build step, no dependencies.
   To go live, replace the D object with data mapped from the API (see INTEGRATION.md). */
(function () {
  const D = window.CARBON_DATA;
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (n) => Number(n).toLocaleString();
  const lab = (h) => `D${Math.floor(h / 24) + 1} ${String(h % 24).padStart(2, "0")}:00`;
  const TYPE = { urgent_inference: "Urgent inference", batch_inference: "Batch inference", training: "Training", etl: "ETL" };
  const STATE = { DONE: "ok", RUNNING: "info", PLANNED: "info" };
  let selected = D.jobs[0].id;

  /* ---------- theme ---------- */
  const root = document.documentElement;
  const setTheme = (t) => { root.dataset.theme = t; try { localStorage.setItem("theme", t); } catch (e) {} };
  try {
    const saved = localStorage.getItem("theme");
    if (saved) setTheme(saved); else if (matchMedia("(prefers-color-scheme: dark)").matches) setTheme("dark");
  } catch (e) {}
  $("#theme").checked = root.dataset.theme === "dark";
  $("#theme").onchange = (e) => setTheme(e.target.checked ? "dark" : "light");

  /* ---------- navigation ---------- */
  function show(view) {
    document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== "view-" + view));
    document.querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-selected", b.dataset.view === view));
    if (location.hash !== "#" + view) history.replaceState(null, "", "#" + view);
  }
  document.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => show(b.dataset.view)));

  /* ---------- banner ---------- */
  $("#banner").innerHTML = `<span class="chip info">Demo data</span> ${esc(D.meta.note)} Source: ${esc(D.meta.source)}.`;

  /* ---------- KPIs ---------- */
  function ring(pct) {
    const r = 36, c = 2 * Math.PI * r, v = Math.max(0, Math.min(pct, 30)) / 30 * c;
    return `<svg class="ring" viewBox="0 0 88 88" role="img" aria-label="${pct}% carbon saved">
      <circle class="trk" cx="44" cy="44" r="${r}"/><circle class="val" cx="44" cy="44" r="${r}" stroke-dasharray="${v} ${c}"/>
      <text x="44" y="50" text-anchor="middle">${pct}%</text></svg>`;
  }
  function kpis() {
    const k = D.kpi, r = k.realized, f = k.forecasted, risk = D.jobs.filter((j) => j.forced).length;
    const tile = (inner) => `<div class="card kpi">${inner}</div>`;
    const txt = (l, v, h) => `<div><div class="label">${l}</div><div class="value">${v}</div><div class="hint">${h}</div></div>`;
    $("#kpis").innerHTML =
      tile(ring(r.pct) + txt("Carbon saved", "", `Realized ${r.pct}% · forecast ${f.pct}%`)) +
      tile(txt("Baseline vs scheduled", `${fmt(r.baseG)} → ${fmt(r.optG)} g`, `Realized, ${r.jobs} finished jobs, same data both sides`)) +
      tile(txt("Deadlines met", `${k.deadlinesOptPct}%`, `${k.deadlinesBasePct}% if run immediately · ${risk} job at risk`)) +
      tile(txt("Average wait", `${k.waitOptH} h`, `${k.waitBaseH} h if run immediately. This is the cost of delaying.`));
  }

  /* ---------- timeline ---------- */
  function timeline() {
    const X1 = 48, W = 1000, L = 84, R = 16, T = 14, CH = 130, LANE = 28;
    const jobs = D.jobs, H = T + CH + 30 + jobs.length * LANE + 8;
    const x = (h) => L + ((W - L - R) * h) / X1;
    const fc = D.series.forecast.slice(0, X1), act = D.series.actual.slice(0, X1);
    const lo = Math.min(...fc, ...act) - 10, hi = Math.max(...fc, ...act) + 10;
    const y = (v) => T + CH - ((v - lo) / (hi - lo)) * CH;
    const path = (a) => a.map((v, i) => `${i ? "L" : "M"}${x(i + 0.5).toFixed(1)} ${y(v).toFixed(1)}`).join("");
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Job schedule over forecast grid intensity">`;
    for (let q = 0; q <= 3; q++) {
      const v = lo + ((hi - lo) * q) / 3;
      s += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${Math.round(v)}</text>`;
    }
    for (let d = 0; d < 2; d++) s += `<line class="grid" x1="${x(d * 24)}" x2="${x(d * 24)}" y1="${T}" y2="${H - 6}"/><text x="${x(d * 24) + 5}" y="${T + 11}">Day ${d + 1}</text>`;
    s += `<path class="area" d="${path(fc)} L${x(X1)} ${T + CH} L${x(0)} ${T + CH}Z"/><path class="line" d="${path(fc)}"/><path class="act" d="${path(act)}"/>`;
    s += `<text x="${L}" y="${T + CH + 16}">gCO2/kWh. Solid: forecast. Dashed amber: actual so far.</text>`;
    const y0 = T + CH + 28;
    jobs.forEach((j, i) => {
      const yy = y0 + i * LANE, w = (h) => Math.max(3, x(h) - x(0));
      s += `<text x="${L - 8}" y="${yy + 14}" text-anchor="end" style="fill:var(--text)">${esc(j.id)}</text>`;
      s += `<rect class="base" x="${x(j.base)}" y="${yy}" width="${w(j.dur)}" height="8" rx="3"><title>Run immediately: ${lab(j.base)}</title></rect>`;
      s += `<rect class="run${j.forced ? " crit" : ""}" x="${x(j.start)}" y="${yy + 10}" width="${w(j.dur)}" height="12" rx="5"><title>${esc(j.id)} scheduled ${lab(j.start)}</title></rect>`;
      if (j.dl <= X1) s += `<path class="dl" d="M${x(j.dl)} ${yy + 2} l5 9 l-5 9 l-5 -9z"><title>Deadline ${lab(j.dl)}</title></path>`;
    });
    s += `<line class="now" x1="${x(D.meta.now)}" x2="${x(D.meta.now)}" y1="${T}" y2="${H - 6}"/><text x="${x(D.meta.now) + 5}" y="${T + 24}" style="fill:var(--text);font-weight:700">now</text></svg>`;
    $("#timeline").innerHTML = s;
    $("#tl-meta").textContent = `Now: ${lab(D.meta.now)}`;
    $("#tl-legend").innerHTML =
      `<span><i style="background:var(--accent-soft)"></i>Scheduled start</span>
       <span><i style="border:1.5px dashed var(--muted)"></i>Run immediately</span>
       <span>&#9670; Deadline</span><span><i style="border:2px solid var(--crit);background:var(--accent-soft)"></i>Forced start, deadline at risk</span>`;
  }

  /* ---------- jobs ---------- */
  function jobs() {
    $("#job-count").textContent = `${D.jobs.length} jobs`;
    $("#job-list").innerHTML = D.jobs.map((j) => `
      <button class="job" data-id="${esc(j.id)}" aria-pressed="${j.id === selected}">
        <b>${esc(j.id)}</b>
        <span><span class="chip ${STATE[j.state]}">${j.state.toLowerCase()}</span>${j.forced ? ' <span class="chip crit">forced</span>' : ""}</span>
        <span class="sub">${TYPE[j.type]} · ${j.kw} kW · starts ${lab(j.start)} · deadline ${lab(j.dl)}</span>
      </button>`).join("");
    document.querySelectorAll(".job").forEach((b) => (b.onclick = () => { selected = b.dataset.id; jobs(); }));
    const j = D.jobs.find((x) => x.id === selected);
    const best = Math.min(...j.alts.map((a) => a.g)), now = j.alts[0], pick = j.alts[1];
    const saved = now.g - pick.g;
    $("#detail").innerHTML = `
      <div class="head"><h2>Why ${esc(j.id)} runs when it does</h2><span class="chip ${STATE[j.state]}">${j.state.toLowerCase()}</span></div>
      <p>${esc(j.reason)}</p>
      <div class="alts">${j.alts.map((a) => `
        <div class="tile ${a.g === best ? "best" : ""}"><small>${a.label}</small><b>${fmt(a.g)} g</b><small>starts ${lab(a.start)}</small></div>`).join("")}</div>
      <p class="muted">${saved > 0 ? `Forecast saving versus running now: ${fmt(saved)} g CO2. ` : ""}Planned with ${j.pad} h (${j.dur} h estimate plus a 25% safety margin).</p>`;
  }

  /* ---------- submit preview (same rule as the scheduler: lowest carbon start that meets the deadline) ---------- */
  $("#f-go").onclick = () => {
    const dur = +$("#f-dur").value, kw = +$("#f-kw").value, sub = +$("#f-sub").value, dl = +$("#f-dl").value;
    const out = $("#f-out"), F = D.series.forecast;
    if (!(dur > 0 && kw > 0 && sub >= 0 && dl > sub)) { out.textContent = "Check the numbers: the deadline must be after the submit time."; return; }
    const pad = Math.ceil(dur * 1.25), last = Math.min(dl - pad, F.length - pad);
    const cost = (s) => kw * F.slice(s, s + pad).reduce((a, b) => a + b, 0);
    if (last < sub) { out.innerHTML = `<span class="chip crit">Critical</span> This deadline is too tight. The job needs ${pad} h with the safety margin and only ${dl - sub} h are available. It would start immediately and raise an alert.`; return; }
    let best = sub; for (let s = sub; s <= last; s++) if (cost(s) < cost(best)) best = s;
    const now = cost(sub), pick = cost(best), pct = ((now - pick) / now * 100).toFixed(1);
    out.innerHTML = `<span class="chip ok">Feasible</span> Start at <b>${lab(best)}</b>, finishing by ${lab(best + dur)} with ${dl - best - pad} h of slack.
      Forecast ${fmt(Math.round(pick))} g versus ${fmt(Math.round(now))} g if started now (${pct}% lower).`;
  };

  /* ---------- alerts ---------- */
  const LEVEL = { critical: ["crit", "Critical"], warning: ["warn", "Warning"], info: ["info", "Info"] };
  function alerts() {
    const open = D.alerts.filter((a) => !a.ack).length;
    $("#alert-n").textContent = open ? `(${open})` : "";
    $("#alert-meta").textContent = `${open} unacknowledged`;
    $("#alerts").innerHTML = D.alerts.map((a) => `
      <div class="well alert ${a.ack ? "done" : ""}">
        <div class="row"><span class="chip ${LEVEL[a.level][0]}">${LEVEL[a.level][1]}</span><b>${esc(a.type)}</b><span class="muted">${lab(a.time)}</span></div>
        <p>${esc(a.msg)}</p>
        <div><button class="btn" data-ack="${a.id}" ${a.ack ? "disabled" : ""}>${a.ack ? "Acknowledged" : "Acknowledge"}</button></div>
      </div>`).join("");
    document.querySelectorAll("[data-ack]").forEach((b) => (b.onclick = () => { D.alerts.find((a) => a.id == b.dataset.ack).ack = true; alerts(); }));
  }

  /* ---------- results ---------- */
  function results() {
    const B = D.bench, W = 1000, Hh = 280, ml = 56, mb = 56, mt = 20, n = B.length;
    const lo = Math.min(0, ...B.map((b) => b.min)) - 2, hi = Math.max(...B.map((b) => b.max)) + 4;
    const y = (v) => mt + (Hh - mt - mb) * (1 - (v - lo) / (hi - lo)), bw = (W - ml - 16) / n;
    let s = `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Carbon saved by scenario, mean with min to max range">`;
    for (let v = Math.ceil(lo / 10) * 10; v <= hi; v += 10) s += `<line class="grid" x1="${ml}" x2="${W - 8}" y1="${y(v)}" y2="${y(v)}"/><text x="${ml - 8}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`;
    s += `<line class="zero" x1="${ml}" x2="${W - 8}" y1="${y(0)}" y2="${y(0)}"/>`;
    B.forEach((b, i) => {
      const cx = ml + bw * i + bw / 2, w = Math.min(64, bw * 0.5);
      s += `<rect class="bar" x="${cx - w / 2}" y="${Math.min(y(b.mean), y(0))}" width="${w}" height="${Math.abs(y(b.mean) - y(0))}" rx="8"><title>${b.name}: mean ${b.mean}%, range ${b.min}% to ${b.max}%</title></rect>
        <line class="whisk" x1="${cx}" x2="${cx}" y1="${y(b.min)}" y2="${y(b.max)}"/><line class="whisk" x1="${cx - 8}" x2="${cx + 8}" y1="${y(b.max)}" y2="${y(b.max)}"/><line class="whisk" x1="${cx - 8}" x2="${cx + 8}" y1="${y(b.min)}" y2="${y(b.min)}"/>
        <text class="lbl" x="${cx}" y="${y(b.max) - 8}" text-anchor="middle">${b.mean}%</text><text x="${cx}" y="${Hh - mb + 20}" text-anchor="middle">${esc(b.name)}</text>`;
    });
    $("#bench-chart").innerHTML = s + "</svg>";
    $("#bench-table").innerHTML = `<tr><th>Scenario</th><th>Saved, mean (range)</th><th>Runs below zero</th><th>Deadlines met</th><th>Average wait (min)</th></tr>` +
      B.map((b) => `<tr><td><b>${esc(b.name)}</b></td><td class="mono">${b.mean}% (${b.min} to ${b.max})</td><td>${b.neg} of 20</td><td>${b.hitBase}% → ${b.hitOpt}%</td><td>${b.waitBase} → ${b.waitOpt}</td></tr>`).join("");
  }

  kpis(); timeline(); jobs(); alerts(); results();
  const start = location.hash.slice(1);
  show(["overview", "jobs", "alerts", "results"].includes(start) ? start : "overview");
})();
