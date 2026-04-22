// My Bets analytics charts.
const MUTED = "#8a93a6";
const GRID = "#222836";
const POSITIVE = "#4ade80";
const NEGATIVE = "#f87171";
const ACCENT = "#6ea8ff";

const AXIS = { ticks: { color: MUTED }, grid: { color: GRID } };
const BAR_OPTS = {
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: { x: AXIS, y: AXIS },
};

(async function () {
  const resp = await fetch("/my-bets/analytics.json");
  const data = await resp.json();

  // Cumulative P&L
  if (data.cumulative_pnl.length) {
    new Chart(document.getElementById("ch-cumulative"), {
      type: "line",
      data: {
        datasets: [{
          label: "Cumulative P&L",
          data: data.cumulative_pnl.map(p => ({ x: p.t, y: p.v })),
          borderColor: ACCENT,
          backgroundColor: "rgba(110, 168, 255, 0.15)",
          fill: true,
          tension: 0.2,
          pointRadius: 2,
        }],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { type: "time", ticks: { color: MUTED }, grid: { color: GRID } },
          y: { ticks: { color: MUTED, callback: v => "$" + v }, grid: { color: GRID } },
        },
      },
    });
  }

  const barChart = (canvasId, rows, valueKey, colorFn, fmt) => {
    if (!rows.length) return;
    new Chart(document.getElementById(canvasId), {
      type: "bar",
      data: {
        labels: rows.map(r => r.label),
        datasets: [{
          data: rows.map(r => r[valueKey]),
          backgroundColor: rows.map(r => colorFn(r[valueKey])),
        }],
      },
      options: {
        ...BAR_OPTS,
        scales: {
          x: AXIS,
          y: { ...AXIS, ticks: { ...AXIS.ticks, callback: fmt } },
        },
      },
    });
  };

  barChart("ch-sport", data.win_rate_by_sport, "rate",
    v => v >= 0.5 ? POSITIVE : NEGATIVE,
    v => (v * 100).toFixed(0) + "%");

  barChart("ch-type", data.win_rate_by_type, "rate",
    v => v >= 0.5 ? POSITIVE : NEGATIVE,
    v => (v * 100).toFixed(0) + "%");

  barChart("ch-book", data.roi_by_book, "roi",
    v => v >= 0 ? POSITIVE : NEGATIVE,
    v => v.toFixed(0) + "%");
})();
