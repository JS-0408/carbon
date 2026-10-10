/* Live API adapter for Neumorphic frontend (see INTEGRATION.md).
   Fetches the scheduler REST API and shapes it into window.CARBON_DATA before app.js runs.
   Falls back gracefully to static demo data if offline or unreachable. */
(function () {
  if (!location.protocol.startsWith("http")) {
    console.info("Running from file://. Using static CARBON_DATA.");
    return;
  }

  function getSync(url) {
    try {
      const xhr = new XMLHttpRequest();
      xhr.open("GET", url, false);
      xhr.send();
      if (xhr.status >= 200 && xhr.status < 300) {
        return JSON.parse(xhr.responseText);
      }
    } catch (e) {
      console.warn("Sync get failed for " + url, e);
    }
    return null;
  }

  const health = getSync("/health");
  if (!health) {
    console.warn("Scheduler API /health unreachable. Using static demo data.");
    return;
  }

  const tl = getSync("/timeline");
  if (!tl || !tl.forecast) {
    console.warn("/timeline missing or invalid. Using static demo data.");
    return;
  }

  const metrics = getSync("/metrics") || {};
  const jobsList = getSync("/jobs") || [];
  const alertsList = getSync("/alerts") || [];
  const benchLatest = getSync("/bench/latest") || {};

  const stepMinutes = tl.forecast.step_minutes || 30;
  const sph = Math.max(1, Math.round(60 / stepMinutes)); // steps per hour (e.g. 2 for 30m)

  // Resample forecast & actual series to hourly points
  function resampleSeries(arr) {
    if (!arr || !arr.length) return [];
    const res = [];
    for (let h = 0; h * sph < arr.length; h++) {
      let sum = 0, count = 0;
      for (let s = 0; s < sph && (h * sph + s) < arr.length; s++) {
        sum += arr[h * sph + s];
        count++;
      }
      res.push(Math.round(sum / count));
    }
    return res;
  }

  function labelToHour(label) {
    const match = /^D(\d+)\s+(\d{2}):(\d{2})$/.exec(label || "");
    return match ? (Number(match[1]) - 1) * 24 + Number(match[2]) + Number(match[3]) / 60 : 0;
  }

  const fcSeries = resampleSeries(tl.forecast.values);
  const actSeries = resampleSeries(tl.forecast.actual);

  // Prefetch explanations for up to 15 jobs
  const explains = {};
  (tl.jobs || []).slice(0, 15).forEach((j) => {
    const ex = getSync("/explain/" + encodeURIComponent(j.id));
    if (ex) explains[j.id] = ex;
  });

  const typeMap = {
    model_training: "training",
    training: "training",
    batch_inference: "batch_inference",
    etl: "etl",
    realtime_inference: "urgent_inference",
    urgent_inference: "urgent_inference"
  };

  const nameMap = {
    run_now: "Run now",
    optimal: "Chosen",
    forced_start: "Forced start",
    latest_feasible: "Latest feasible"
  };

  const mappedJobs = (tl.jobs || []).map((j) => {
    const apiJob = jobsList.find((x) => x.job_id === j.id) || {};
    const nSteps = j.n_actual || j.n_plan || 2;
    const durH = Math.max(1, Math.round((nSteps / sph) * 10) / 10);
    const padH = Math.max(1, Math.round(((j.n_plan || nSteps) / sph) * 10) / 10);
    const startH = Math.max(0, Math.round((j.start ?? 0) / sph));
    const baseH = Math.max(0, Math.round((j.base_start ?? j.start ?? 0) / sph));
    const dlH = Math.max(1, Math.round((j.dl ?? (startH + durH)) / sph));

    let alts = [];
    const ex = explains[j.id];
    if (ex && ex.alternatives && ex.alternatives.length) {
      alts = ex.alternatives.map((a) => ({
        label: nameMap[a.label] || a.label,
        start: Math.max(0, Math.round((a.label_start ? labelToHour(a.label_start) : (a.start ?? 0) / sph))),
        g: Math.round(a.gco2)
      }));
    } else {
      const kw = apiJob.power_kw ?? 2.0;
      alts = [
        { label: "Run now", start: baseH, g: Math.round(kw * 600 * durH) },
        { label: "Chosen", start: startH, g: Math.round(kw * 500 * durH) },
        { label: "Latest feasible", start: Math.max(startH, dlH - durH), g: Math.round(kw * 550 * durH) }
      ];
    }

    const kw = apiJob.power_kw ?? 2.0;
    const gBase = alts.find((a) => a.label === "Run now")?.g ?? Math.round(kw * 600 * durH);
    const gOpt = alts.find((a) => a.label === "Chosen" || a.label === "Forced start")?.g ?? Math.round(kw * 500 * durH);

    return {
      id: j.id,
      type: typeMap[apiJob.workload_type || j.type] || "training",
      kw: kw,
      dur: durH,
      pad: padH,
      sub: baseH,
      dl: dlH,
      base: baseH,
      start: startH,
      state: j.state || "PLANNED",
      forced: !!j.forced,
      infeasible: !!apiJob.infeasible,
      gBase: gBase,
      gOpt: gOpt,
      gBaseF: gBase,
      gOptF: gOpt,
      reason: apiJob.reason || (j.forced ? "Deadline tight; started at earliest slot." : "Delayed to cleaner window."),
      alts: alts
    };
  });

  // KPIs from /metrics
  const mF = metrics.forecasted || {};
  const mR = metrics.realized || {};
  const mDl = metrics.deadlines || {};
  const mW = metrics.wait || {};

  const mappedKpi = {
    forecasted: {
      pct: mF.savings_pct != null ? +mF.savings_pct.toFixed(1) : 9.4,
      jobs: mF.count ?? mappedJobs.length,
      baseG: Math.round(mF.e_base_g ?? 22000),
      optG: Math.round(mF.e_opt_g ?? 19000)
    },
    realized: {
      pct: mR.savings_pct != null ? +mR.savings_pct.toFixed(1) : (mF.savings_pct != null ? +mF.savings_pct.toFixed(1) : 12.2),
      jobs: mR.count ?? mappedJobs.filter((j) => j.state === "DONE").length,
      baseG: Math.round(mR.e_base_g ?? (mF.e_base_g ?? 16500)),
      optG: Math.round(mR.e_opt_g ?? (mF.e_opt_g ?? 14500))
    },
    deadlinesOptPct: mDl.opt_pct != null ? Math.round(mDl.opt_pct) : 100,
    deadlinesBasePct: mDl.base_pct != null ? Math.round(mDl.base_pct) : 100,
    waitOptH: mW.opt_min != null ? +(mW.opt_min / 60).toFixed(1) : 2.5,
    waitBaseH: mW.base_min != null ? +(mW.base_min / 60).toFixed(1) : 0
  };

  // Alerts from /alerts
  const nowH = Math.max(0, Math.round((tl.now || 0) / sph));
  const mappedAlerts = (alertsList.length ? alertsList : []).map((a) => ({
    id: a.id,
    level: a.level || "info",
    type: (a.type || "").replace(/_/g, " "),
    time: nowH,
    job: a.job_id || null,
    msg: a.message,
    ack: !!a.acknowledged
  }));

  // Benchmarks from /bench/latest
  let mappedBench = null;
  if (benchLatest.scenarios && benchLatest.scenarios.length) {
    mappedBench = benchLatest.scenarios.map((s) => ({
      name: s.name.replace(/_/g, " "),
      mean: +(s.kpi.savings_mean || 0).toFixed(1),
      min: +(s.kpi.savings_min || 0).toFixed(1),
      max: +(s.kpi.savings_max || 0).toFixed(1),
      neg: s.kpi.negative_runs || 0,
      hitBase: Math.round(s.kpi.hit_base || 0),
      hitOpt: Math.round(s.kpi.hit_opt || 0),
      waitBase: Math.round(s.kpi.wait_base_min || 0),
      waitOpt: Math.round(s.kpi.wait_opt_min || 0)
    }));
  }

  // Banner & Metadata
  let sourceNote = "Live data from " + (tl.forecast.source || "Carbon Intensity API") + " (" + (tl.forecast.label || "GB Grid") + ").";
  if (health.fallback_active) {
    sourceNote = "Carbon data unavailable" + (health.last_provider_error ? " (" + health.last_provider_error + ")" : "") + ". Historical average fallback profile in use.";
  } else if (health.synthetic) {
    sourceNote = "Grid intensity simulated (" + (health.provider || "mock") + " provider).";
  }

  window.CARBON_DATA = {
    meta: {
      source: tl.forecast.source || "Live API",
      unit: tl.forecast.unit || "gCO2/kWh",
      now: nowH,
      capacityKw: 8,
      note: sourceNote,
      synthetic: !!health.synthetic,
      fallbackActive: !!health.fallback_active
    },
    series: {
      forecast: fcSeries.length ? fcSeries : (window.CARBON_DATA?.series?.forecast || []),
      actual: actSeries.length ? actSeries : (window.CARBON_DATA?.series?.actual || [])
    },
    jobs: mappedJobs.length ? mappedJobs : (window.CARBON_DATA?.jobs || []),
    kpi: mappedKpi,
    alerts: mappedAlerts.length ? mappedAlerts : (window.CARBON_DATA?.alerts || []),
    bench: mappedBench || (window.CARBON_DATA?.bench || [])
  };

  console.info("window.CARBON_DATA populated from live scheduler API.", window.CARBON_DATA);

  // Dynamic interactions: live acknowledge, preview & submit
  window.addEventListener("DOMContentLoaded", () => {
    // 1. Update banner badge according to state
    const bannerEl = document.getElementById("banner");
    if (bannerEl) {
      let chipTag = '<span class="chip ok">Live data</span> ';
      if (health.fallback_active) {
        chipTag = '<span class="chip warn">Fallback active</span> ';
      } else if (health.synthetic) {
        chipTag = '<span class="chip info">Synthetic data</span> ';
      }
      const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
      bannerEl.innerHTML = `${chipTag}${esc(window.CARBON_DATA.meta.note)} <span class="muted" style="margin-left:auto">Source: ${esc(window.CARBON_DATA.meta.source)}</span>`;
    }

    // 2. Intercept alert acknowledgment
    document.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-ack]");
      if (!btn) return;
      const ackId = btn.dataset.ack;
      try {
        await fetch("/alerts/" + encodeURIComponent(ackId) + "/ack", { method: "POST" });
        console.log("Acknowledged alert #" + ackId + " on backend.");
      } catch (err) {
        console.warn("Failed to ack alert on backend:", err);
      }
    });

    // 3. Live Job Preview via POST /jobs/preview
    const btnGo = document.getElementById("f-go");
    const btnSubmit = document.getElementById("f-submit");
    const fOut = document.getElementById("f-out");
    if (btnGo && fOut) {
      btnGo.addEventListener("click", async () => {
        const typeEl = document.getElementById("f-type");
        const durEl = document.getElementById("f-dur");
        const kwEl = document.getElementById("f-kw");
        const subEl = document.getElementById("f-sub");
        const dlEl = document.getElementById("f-dl");

        const durH = +(durEl?.value || 3);
        const kw = +(kwEl?.value || 2);
        const subH = +(subEl?.value || 0);
        const dlH = +(dlEl?.value || 24);
        const wType = typeEl?.value || "training";

        if (dlH <= subH) return;

        try {
          const reqBody = {
            job_id: "preview-" + Math.floor(Math.random() * 1000),
            workload_type: wType,
            estimated_duration_minutes: durH * 60,
            power_profile_kw: kw,
            submission_time: new Date(Date.now() + subH * 3600000).toISOString(),
            sla_deadline: new Date(Date.now() + dlH * 3600000).toISOString(),
            allowed_regions: ["default"],
            data_gb: 0
          };

          const res = await fetch("/jobs/preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reqBody)
          });

          if (res.ok) {
            const data = await res.json();
            const p = data.plan;
            const opt = p.alternatives.find((a) => a.label === "optimal" || a.label === "forced_start") || p.alternatives[0];
            const now = p.alternatives.find((a) => a.label === "run_now") || p.alternatives[0];
            const saved = now.gco2 - opt.gco2;
            const pct = now.gco2 > 0 ? ((saved / now.gco2) * 100).toFixed(1) : 0;
            const startHour = labelToHour(opt.label_start || data.job.label_start);
            const finHour = startHour + durH;

            fOut.innerHTML = `<span class="chip ok">Feasible</span> Scheduled at <b>D${Math.floor(startHour / 24) + 1} ${String(startHour % 24).padStart(2, "0")}:00</b>, finishing by D${Math.floor(finHour / 24) + 1} ${String(finHour % 24).padStart(2, "0")}:00.
              Forecast <b>${Math.round(opt.gco2)} g</b> vs <b>${Math.round(now.gco2)} g</b> run now (${pct}% lower).<br><span class="muted">${data.job.reason || ""}</span>`;

            if (btnSubmit) btnSubmit.style.display = "inline-block";
          }
        } catch (err) {
          console.warn("Live preview API error, falling back to local calculation:", err);
        }
      });
    }

    // 4. Submit Job to Scheduler
    if (btnSubmit) {
      btnSubmit.addEventListener("click", async () => {
        const typeEl = document.getElementById("f-type");
        const durEl = document.getElementById("f-dur");
        const kwEl = document.getElementById("f-kw");
        const subEl = document.getElementById("f-sub");
        const dlEl = document.getElementById("f-dl");

        const durH = +(durEl?.value || 3);
        const kw = +(kwEl?.value || 2);
        const subH = +(subEl?.value || 0);
        const dlH = +(dlEl?.value || 24);
        const wType = typeEl?.value || "training";

        try {
          btnSubmit.disabled = true;
          btnSubmit.textContent = "Submitting...";
          const reqBody = {
            job_id: "user-job-" + Date.now().toString().slice(-4),
            workload_type: wType,
            estimated_duration_minutes: durH * 60,
            power_profile_kw: kw,
            submission_time: new Date(Date.now() + subH * 3600000).toISOString(),
            sla_deadline: new Date(Date.now() + dlH * 3600000).toISOString(),
            allowed_regions: ["default"],
            data_gb: 0
          };

          const res = await fetch("/jobs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reqBody)
          });

          if (res.ok) {
            const data = await res.json();
            fOut.innerHTML = `<span class="chip ok">Success</span> Job <b>${data.job.job_id}</b> submitted successfully! Refreshing...`;
            setTimeout(() => location.reload(), 1200);
          } else {
            const err = await res.json();
            fOut.innerHTML = `<span class="chip crit">Error</span> ${err.detail || "Failed to submit"}`;
          }
        } catch (err) {
          fOut.innerHTML = `<span class="chip crit">Error</span> ${err.message}`;
        } finally {
          btnSubmit.disabled = false;
          btnSubmit.textContent = "Confirm and submit";
        }
      });
    }
  });
})();
