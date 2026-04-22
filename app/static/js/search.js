// Header search with live autocomplete.
// Hitting Enter submits the form to /odds/?q=... (server-side filter).
// Debounced typing triggers /odds/search.json for a dropdown preview.

const input = document.getElementById("site-search");
const resultsEl = document.getElementById("search-results");
if (input && resultsEl) {
  let debounceTimer = null;
  let lastQuery = "";
  let activeIndex = -1;

  const fmtTime = (iso) => {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
      " · " + d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  };

  function closeResults() {
    resultsEl.hidden = true;
    resultsEl.innerHTML = "";
    activeIndex = -1;
  }

  function renderResults(items) {
    if (!items.length) {
      resultsEl.innerHTML = '<div class="search-empty">No matches. Press Enter to filter anyway.</div>';
      resultsEl.hidden = false;
      return;
    }
    resultsEl.innerHTML = items.map((it, i) => `
      <a href="/odds/?q=${encodeURIComponent(input.value)}"
         class="search-item sport-${it.sport_key}" data-idx="${i}">
        <span class="search-sport">${it.sport}</span>
        <span class="search-teams">${it.away_team} <span class="muted">@</span> ${it.home_team}</span>
        <span class="search-time">${fmtTime(it.commence_time)}</span>
      </a>
    `).join("");
    resultsEl.hidden = false;
    activeIndex = -1;
  }

  async function fetchResults(q) {
    if (q.length < 2) { closeResults(); return; }
    try {
      const resp = await fetch(`/odds/search.json?q=${encodeURIComponent(q)}`);
      if (!resp.ok) throw new Error();
      const items = await resp.json();
      if (q === lastQuery) renderResults(items);
    } catch {
      closeResults();
    }
  }

  input.addEventListener("input", () => {
    const q = input.value.trim();
    lastQuery = q;
    clearTimeout(debounceTimer);
    if (!q) { closeResults(); return; }
    debounceTimer = setTimeout(() => fetchResults(q), 180);
  });

  input.addEventListener("keydown", (e) => {
    const items = [...resultsEl.querySelectorAll(".search-item")];
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex = Math.min(items.length - 1, activeIndex + 1);
      items.forEach((el, i) => el.classList.toggle("active", i === activeIndex));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex = Math.max(-1, activeIndex - 1);
      items.forEach((el, i) => el.classList.toggle("active", i === activeIndex));
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      items[activeIndex].click();
    } else if (e.key === "Escape") {
      closeResults();
      input.blur();
    }
  });

  input.addEventListener("focus", () => {
    if (input.value.trim().length >= 2) fetchResults(input.value.trim());
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search-wrap")) closeResults();
  });
}
