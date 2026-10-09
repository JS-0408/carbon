# 5-Minute Demonstration Script: Carbon-Aware AI Workload Scheduler

This script guides an evaluator or presenter through a live end-to-end walkthrough of the Carbon-Aware AI Workload Scheduler.

---

## Preparation (30 seconds)

1. Start the server (run in terminal):
   ```powershell
   .\scripts\demo.ps1
   # Or: uvicorn backend.app.main:app --reload --port 8000
   ```
2. Open your web browser to:
   [http://127.0.0.1:8000](http://127.0.0.1:8000)
3. The dashboard opens with `weekday_mix` pre-loaded in Dark Theme.

---

## Minute 1: The Core Value Proposition & Dashboard Overview
- **Narrative:**  
  *"Standard schedulers run AI workloads immediately, oblivious to whether the electric grid is dirty or clean. This dashboard shows a 12-job mixed queue scheduled against a diurnal carbon intensity curve."*
- **Actions:**
  1. Point to the **Data Source Banner** at the top: notice the label **Synthetic data (mock)**, proving transparency about data origins.
  2. Point to the **KPI Cards**:
     - **Carbon saved (forecasted):** ~6-7% predicted savings.
     - **Baseline vs Optimized:** Clear grams of $\text{CO}_2$ compared on identical signals.
     - **Deadlines met:** 100%.
     - **Average wait:** ~3.5 hours — highlight that saving carbon involves an honest delay trade-off.
  3. Look at the **Timeline Chart**:
     - Blue curve: forecasted grid emissions ($\text{gCO}_2/\text{kWh}$) showing daytime solar troughs and evening coal/gas peaks.
     - Solid bars: scheduled carbon-aware execution.
     - Dashed grey outlines: where a naive immediate scheduler would have run.

---

## Minute 2: Decision Support & Plain-Language Explanations
- **Narrative:**  
  *"Machine learning engineers won't trust a black-box scheduler. The system explains every single decision in plain language with alternative choices."*
- **Actions:**
  1. Click on job **`bat-02`** (or any delayed batch job) in the Job Queue table.
  2. Examine the **Decision Support Panel** on the right:
     - Notice the explanation text: *"Delayed 360 min to start at D1 09:30: forecast grid intensity 587 vs 652 gCO2/kWh if run now (-10%), saving about 147 g CO2. 30 min of slack remain."*
     - Look at the **Alternative Cards**:
       - **Run now:** Higher emissions, earlier finish.
       - **Chosen (optimal):** Lowest carbon footprint.
       - **Latest feasible:** Maximizes delay before violating the deadline.

---

## Minute 3: The SLA-Override Moment (Guaranteed Deadlines)
- **Narrative:**  
  *"What happens when a user submits an urgent job or one with an infeasible deadline? The scheduler must NEVER silently delay a job into missing its SLA."*
- **Actions:**
  1. Scroll to the **Submit a Job** card.
  2. Enter the following parameters:
     - Job name: `urgent-eval-001`
     - Workload type: `realtime_inference` (or `batch_inference` with a 2-hour duration and a deadline only 2 hours away).
     - Estimated duration: `120` min
     - Deadline: Set to `Now + 2 hours`
  3. Click **Preview Window**:
     - The preview explicitly highlights that no green delay window fits before the deadline.
  4. Click **Confirm and Submit**:
     - The job is accepted and immediately placed at the earliest free slot.
     - Look at the **Alerts Feed**: A critical alert is raised:  
       `sla_risk: urgent-eval-001: no feasible window before deadline. Starting at earliest slot.`
     - In the Job Queue, the state shows **FORCED / PLANNED**, proving the SLA is respected.

---

## Minute 4: The Provider Outage & Failover Moment
- **Narrative:**  
  *"In real-world operations, cloud grid APIs time out, return 500s, or drop connections. Schedulers must not crash or halt clusters."*
- **Actions:**
  1. Click the orange button in the top toolbar: **Simulate API outage**.
  2. Notice the instant system response:
     - The top banner flashes orange: **⚠ Fallback profile in use — Carbon data is unavailable**.
     - An alert is logged: `warning: fallback — Carbon data unavailable. Using historical-average profile.`
  3. Point out that the queue is **still fully planned and operational** using static regional historical diurnal profiles (satisfying Invariant INV4).
  4. Click **Restore API**:
     - The banner returns to normal, fresh forecast data is re-acquired, and pending jobs re-optimize.

---

## Minute 5: Execution, Advancing Time & Benchmark Proof
- **Narrative:**  
  *"Let's advance the simulated clock and inspect realized savings versus forecasted predictions."*
- **Actions:**
  1. Click **+6 h** in the toolbar:
     - Notice jobs transition from `PLANNED` $\to$ `RUNNING`.
     - The vertical green "now" line moves forward across the timeline.
  2. Click **+24 h**:
     - Jobs finish and move to `DONE`.
     - In the KPI cards, the **Realized Carbon Saved** card lights up with verified post-execution data evaluated against actual grid intensity.
  3. Scroll to the **Scenario Results** card at the bottom:
     - Review the bar chart and 20-seed summary table across `weekday_mix`, `tight_deadlines`, `api_outage`, `overrun_cloudy`, and `heavy_load`.
     - Point out that even under heavy overruns and cloud cover, deadline compliance remains 99% thanks to the adaptive padding improvements.

---

## Conclusion
The Carbon-Aware AI Workload Scheduler achieves measurable, validated carbon reductions while keeping every SLA guarantee, providing transparent explanations, and remaining resilient under severe grid and network faults.
