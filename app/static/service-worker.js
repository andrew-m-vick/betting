// Betting Analytics service worker.
//
// Strategy:
// - App shell (CSS, JS, icons) is precached on install so subsequent loads
//   are instant and the app opens offline.
// - HTML navigation requests use network-first with a cache fallback, so
//   odds are always fresh when online but an installed app still shows
//   the last-seen page when the network is down.
// - Other GETs (including API JSON) use network-first too, falling back
//   to any cached copy for the same URL.
//
// Bump CACHE_VERSION when shipping SW changes so old caches get purged.

const CACHE_VERSION = "v1";
const CACHE = `betting-analytics-${CACHE_VERSION}`;
const OFFLINE_URL = "/offline";

const PRECACHE_URLS = [
  OFFLINE_URL,
  "/static/css/app.css",
  "/static/js/search.js",
  "/static/favicon.svg",
  "/static/apple-touch-icon.svg",
  "/static/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  // Never intercept cross-origin (CDN KaTeX / Chart.js) — let the browser handle them.
  if (url.origin !== self.location.origin) return;

  const isHTML = req.mode === "navigate" ||
    (req.headers.get("accept") || "").includes("text/html");

  event.respondWith((async () => {
    try {
      const fresh = await fetch(req);
      // Cache successful navigations + asset responses for offline fallback.
      if (fresh && fresh.ok) {
        const copy = fresh.clone();
        caches.open(CACHE).then((cache) => cache.put(req, copy)).catch(() => {});
      }
      return fresh;
    } catch (err) {
      const cached = await caches.match(req);
      if (cached) return cached;
      if (isHTML) {
        const offline = await caches.match(OFFLINE_URL);
        if (offline) return offline;
      }
      throw err;
    }
  })());
});
