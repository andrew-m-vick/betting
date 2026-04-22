// EV Calculator — pure client-side math.
// Mirrors app/services/math_utils.py so a future refactor can point here
// for parity if the Python is changed.

function americanToDecimal(odds) {
  if (!Number.isFinite(odds) || odds === 0 || (odds > -100 && odds < 100)) return NaN;
  return odds >= 100 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
}
function americanToImplied(odds) {
  if (!Number.isFinite(odds) || odds === 0 || (odds > -100 && odds < 100)) return NaN;
  return odds >= 100 ? 100 / (odds + 100) : Math.abs(odds) / (Math.abs(odds) + 100);
}
function fmtPct(x, digits = 2) { return (x * 100).toFixed(digits) + "%"; }
function fmtMoney(x) {
  const sign = x < 0 ? "-" : "";
  return sign + "$" + Math.abs(x).toFixed(2);
}

const els = {
  trueProb: document.getElementById("true-prob"),
  americanOdds: document.getElementById("american-odds"),
  bankroll: document.getElementById("bankroll"),
  gamePicker: document.getElementById("game-picker"),
  verdict: document.getElementById("verdict"),
  mImplied: document.getElementById("m-implied"),
  mEdge: document.getElementById("m-edge"),
  mEvUnit: document.getElementById("m-ev-unit"),
  mEvPct: document.getElementById("m-ev-pct"),
  mKellyFull: document.getElementById("m-kelly-full"),
  mKellyQuarter: document.getElementById("m-kelly-quarter"),
};

function recompute() {
  const truePct = parseFloat(els.trueProb.value);
  const americanOdds = parseFloat(els.americanOdds.value);
  const bankroll = parseFloat(els.bankroll.value) || 0;

  const p = truePct / 100;
  const dec = americanToDecimal(americanOdds);
  const implied = americanToImplied(americanOdds);

  if (!Number.isFinite(p) || p <= 0 || p >= 1 || !Number.isFinite(dec)) {
    els.verdict.textContent = "Enter a probability between 0.1% and 99.9% and valid American odds.";
    els.verdict.style.background = "var(--surface-2)";
    els.verdict.style.color = "var(--muted)";
    for (const k of ["mImplied","mEdge","mEvUnit","mEvPct","mKellyFull","mKellyQuarter"]) els[k].textContent = "—";
    return;
  }

  const b = dec - 1;
  const q = 1 - p;
  const evUnit = p * b - q;
  const rawKelly = (b * p - q) / b;
  const kelly = Math.max(0, rawKelly);

  els.mImplied.textContent = fmtPct(implied);
  els.mEdge.textContent = fmtPct(p - implied);
  els.mEvUnit.textContent = fmtMoney(evUnit);
  els.mEvPct.textContent = (evUnit * 100).toFixed(2) + "%";

  const fullKellyStake = bankroll * kelly;
  const quarterKellyStake = bankroll * kelly / 4;
  els.mKellyFull.textContent = kelly > 0
    ? `${fmtPct(kelly)} · ${fmtMoney(fullKellyStake)}`
    : "—";
  els.mKellyQuarter.textContent = kelly > 0
    ? `${fmtPct(kelly / 4)} · ${fmtMoney(quarterKellyStake)}`
    : "—";

  if (evUnit > 0) {
    els.verdict.textContent = `+EV bet: you expect to profit ${fmtMoney(evUnit)} per $1 staked.`;
    els.verdict.style.background = "var(--positive-bg)";
    els.verdict.style.color = "var(--positive)";
  } else {
    els.verdict.textContent = `-EV bet: you expect to lose ${fmtMoney(Math.abs(evUnit))} per $1 staked. Don't take it.`;
    els.verdict.style.background = "var(--negative-bg)";
    els.verdict.style.color = "var(--negative)";
  }
}

async function loadGames() {
  try {
    const resp = await fetch("/odds/upcoming.json");
    if (!resp.ok) throw new Error(resp.statusText);
    const games = await resp.json();
    els.gamePicker.innerHTML = '<option value="">— pick a game —</option>';
    for (const g of games) {
      for (const book of g.books) {
        if (book.home_odds != null) {
          const opt = document.createElement("option");
          opt.value = book.home_odds;
          opt.textContent = `${g.sport} · ${g.home_team} (home) @ ${book.book}: ${book.home_odds}`;
          els.gamePicker.appendChild(opt);
        }
        if (book.away_odds != null) {
          const opt = document.createElement("option");
          opt.value = book.away_odds;
          opt.textContent = `${g.sport} · ${g.away_team} (away) @ ${book.book}: ${book.away_odds}`;
          els.gamePicker.appendChild(opt);
        }
      }
    }
    if (els.gamePicker.options.length === 1) {
      els.gamePicker.innerHTML = '<option value="">no upcoming games</option>';
    }
  } catch {
    els.gamePicker.innerHTML = '<option value="">failed to load</option>';
  }
}

els.gamePicker.addEventListener("change", () => {
  if (els.gamePicker.value) {
    els.americanOdds.value = els.gamePicker.value;
    recompute();
  }
});
["input", "change"].forEach(ev => {
  els.trueProb.addEventListener(ev, recompute);
  els.americanOdds.addEventListener(ev, recompute);
  els.bankroll.addEventListener(ev, recompute);
});

loadGames();
recompute();
