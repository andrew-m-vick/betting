// Line Movement chart + summary table. Pulls JSON, filters by market tab.

const PALETTE = [
  "#6ea8ff", "#f59e0b", "#4ade80", "#f87171", "#a78bfa",
  "#2dd4bf", "#fb7185", "#facc15", "#60a5fa", "#c084fc",
];

let chart = null;
let fullData = null;
let activeMarket = "h2h";

function colorFor(key) {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

function labelFor(meta) {
  const sideLabel = meta.side === "home" ? window.__HOME_TEAM
                  : meta.side === "away" ? window.__AWAY_TEAM
                  : meta.side;
  return `${meta.book} — ${sideLabel}`;
}

function render() {
  const datasets = [];
  const emptyEl = document.getElementById("lm-empty");
  const canvas = document.getElementById("lm-chart");

  for (const [key, points] of Object.entries(fullData.series)) {
    const meta = fullData.meta[key];
    if (meta.market !== activeMarket) continue;
    datasets.push({
      label: labelFor(meta),
      data: points.map(p => ({ x: p.t, y: p.v })),
      borderColor: colorFor(key),
      backgroundColor: colorFor(key),
      tension: 0.2,
      pointRadius: 3,
    });
  }

  if (datasets.length === 0) {
    canvas.style.display = "none";
    emptyEl.style.display = "block";
    if (chart) { chart.destroy(); chart = null; }
    renderSummary([]);
    return;
  }
  canvas.style.display = "";
  emptyEl.style.display = "none";

  if (chart) chart.destroy();
  chart = new Chart(canvas, {
    type: "line",
    data: { datasets },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { labels: { color: "#e6e8ef" } },
      },
      scales: {
        x: {
          type: "time",
          time: { tooltipFormat: "MMM d, HH:mm" },
          ticks: { color: "#8a93a6" },
          grid: { color: "#222836" },
        },
        y: {
          title: { display: true, text: activeMarket === "totals" ? "Odds (American)" : "Odds (American)", color: "#8a93a6" },
          ticks: { color: "#8a93a6" },
          grid: { color: "#222836" },
        },
      },
    },
  });

  renderSummary(datasets);
}

function renderSummary(datasets) {
  const tbody = document.querySelector("#lm-summary tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  for (const ds of datasets) {
    const [book, sideLabel] = ds.label.split(" — ");
    const pts = ds.data;
    if (pts.length === 0) continue;
    const open = pts[0].y;
    const latest = pts[pts.length - 1].y;
    const diff = latest - open;
    const direction = diff === 0 ? "—" : (diff > 0 ? "sharpening toward bettor" : "moving against bettor");
    const cell = (n) => Number.isFinite(n) ? n.toFixed(0) : "—";
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${book}</td>
      <td>${sideLabel}</td>
      <td class="num">${cell(open)}</td>
      <td class="num">${cell(latest)}</td>
      <td class="num" style="color: ${diff > 0 ? 'var(--positive)' : diff < 0 ? 'var(--negative)' : 'var(--muted)'}">${diff > 0 ? '+' : ''}${cell(diff)}</td>
      <td style="color: var(--muted)">${direction}</td>
    `;
    tbody.appendChild(row);
  }
  if (tbody.children.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No movement yet for this market.</td></tr>';
  }
}

document.querySelectorAll(".market-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".market-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    activeMarket = btn.dataset.market;
    if (fullData) render();
  });
});

(async function load() {
  const resp = await fetch(`/odds/line-movement/${window.__GAME_ID}.json`);
  fullData = await resp.json();
  render();
})();
