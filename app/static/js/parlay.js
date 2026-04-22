// Parlay Simulator — client-side parlay math + Monte Carlo.

function americanToDecimal(odds) {
  if (!Number.isFinite(odds) || odds === 0 || (odds > -100 && odds < 100)) return NaN;
  return odds >= 100 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
}
function fmtMoney(x) { return (x < 0 ? "-$" : "$") + Math.abs(x).toFixed(2); }
function fmtPct(x, d = 2) { return (x * 100).toFixed(d) + "%"; }

const legsEl = document.getElementById("legs");
const MAX_LEGS = 10;
const MIN_LEGS = 2;

function makeLeg(idx, defaults = {}) {
  const wrap = document.createElement("div");
  wrap.className = "parlay-leg";
  wrap.innerHTML = `
    <div class="form-row">
      <label>Leg ${idx + 1} — selection</label>
      <input type="text" class="leg-name" placeholder="Team or bet name" value="${defaults.name ?? ""}">
    </div>
    <div class="form-row">
      <label>Odds (American)</label>
      <input type="number" class="leg-odds" value="${defaults.odds ?? -110}" step="1">
    </div>
    <div class="form-row">
      <label>Your true prob (%)</label>
      <input type="number" class="leg-prob" value="${defaults.prob ?? 50}" min="0.1" max="99.9" step="0.1">
    </div>
    <button type="button" class="btn-remove">Remove</button>
  `;
  wrap.querySelector(".btn-remove").addEventListener("click", () => {
    if (legsEl.children.length > MIN_LEGS) {
      wrap.remove();
      relabel();
    }
  });
  return wrap;
}

function relabel() {
  [...legsEl.children].forEach((leg, i) => {
    leg.querySelector("label").textContent = `Leg ${i + 1} — selection`;
  });
}

function addLeg(defaults) {
  if (legsEl.children.length >= MAX_LEGS) return;
  legsEl.appendChild(makeLeg(legsEl.children.length, defaults));
}

document.getElementById("add-leg").addEventListener("click", () => addLeg());

// Seed with two default legs.
addLeg({ name: "Chiefs ML", odds: -150, prob: 65 });
addLeg({ name: "Over 45.5", odds: -110, prob: 52 });

function readLegs() {
  const rows = [...legsEl.children];
  const legs = [];
  for (const row of rows) {
    const odds = parseFloat(row.querySelector(".leg-odds").value);
    const probPct = parseFloat(row.querySelector(".leg-prob").value);
    const dec = americanToDecimal(odds);
    if (!Number.isFinite(dec) || !Number.isFinite(probPct) || probPct <= 0 || probPct >= 100) {
      return { error: "Every leg needs valid odds and a probability between 0.1% and 99.9%." };
    }
    legs.push({ decimalOdds: dec, prob: probPct / 100 });
  }
  return { legs };
}

function runSimulation(legs, stake, n) {
  // Each sim: win only if every leg wins. Payout = stake * productDecimal.
  const payoutDecimal = legs.reduce((acc, l) => acc * l.decimalOdds, 1);
  const outcomes = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let win = true;
    for (const leg of legs) {
      if (Math.random() > leg.prob) { win = false; break; }
    }
    outcomes[i] = win ? stake * (payoutDecimal - 1) : -stake;
  }
  return { outcomes, payoutDecimal };
}

function percentile(sortedArr, p) {
  const idx = Math.floor((p / 100) * (sortedArr.length - 1));
  return sortedArr[idx];
}

let chart = null;

function plotHistogram(outcomes, stake) {
  const sorted = [...outcomes].sort((a, b) => a - b);
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  const bins = 30;
  const width = (max - min) / bins || 1;
  const labels = [];
  const counts = new Array(bins).fill(0);
  for (let i = 0; i < bins; i++) {
    labels.push(fmtMoney(min + width * i));
  }
  for (const v of outcomes) {
    let idx = Math.floor((v - min) / width);
    if (idx >= bins) idx = bins - 1;
    if (idx < 0) idx = 0;
    counts[idx]++;
  }

  const ctx = document.getElementById("mc-chart");
  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Simulated parlays",
        data: counts,
        backgroundColor: labels.map((_, i) =>
          (min + width * (i + 0.5)) >= 0 ? "rgba(74, 222, 128, 0.6)" : "rgba(248, 113, 113, 0.5)"
        ),
        borderWidth: 0,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#8a93a6", maxRotation: 60, minRotation: 45, autoSkip: true, maxTicksLimit: 8 }, grid: { display: false } },
        y: { ticks: { color: "#8a93a6" }, grid: { color: "#222836" } },
      },
    },
  });
}

document.getElementById("run-sim").addEventListener("click", () => {
  const { legs, error } = readLegs();
  if (error) { alert(error); return; }
  if (legs.length < MIN_LEGS) { alert("Need at least 2 legs."); return; }
  const stake = parseFloat(document.getElementById("stake").value);
  const n = Math.min(100000, Math.max(100, parseInt(document.getElementById("sims").value, 10) || 10000));
  if (!(stake > 0)) { alert("Stake must be positive."); return; }

  const payoutDecimal = legs.reduce((a, l) => a * l.decimalOdds, 1);
  const trueProb = legs.reduce((a, l) => a * l.prob, 1);
  const fairPayoutDecimal = 1 / trueProb;
  const evPerUnit = trueProb * (payoutDecimal - 1) - (1 - trueProb);
  const houseEdge = -evPerUnit;

  document.getElementById("m-book-payout").textContent = payoutDecimal.toFixed(3);
  document.getElementById("m-true-prob").textContent = fmtPct(trueProb, 3);
  document.getElementById("m-fair-payout").textContent = fairPayoutDecimal.toFixed(3);
  document.getElementById("m-house-edge").textContent = fmtPct(houseEdge);
  document.getElementById("summary-card").style.display = "";

  const { outcomes } = runSimulation(legs, stake, n);
  document.getElementById("mc-count").textContent = n.toLocaleString();
  document.getElementById("mc-card").style.display = "";

  const sorted = [...outcomes].sort((a, b) => a - b);
  const mean = outcomes.reduce((a, v) => a + v, 0) / outcomes.length;
  const profits = outcomes.filter(v => v > 0).length;
  const losses = outcomes.filter(v => v <= -stake).length;

  document.getElementById("m-mean").textContent = fmtMoney(mean);
  document.getElementById("m-median").textContent = fmtMoney(percentile(sorted, 50));
  document.getElementById("m-p10").textContent = fmtMoney(percentile(sorted, 10));
  document.getElementById("m-p90").textContent = fmtMoney(percentile(sorted, 90));
  document.getElementById("m-prob-profit").textContent = fmtPct(profits / outcomes.length);
  document.getElementById("m-prob-loss").textContent = fmtPct(losses / outcomes.length);

  plotHistogram(outcomes, stake);
});
