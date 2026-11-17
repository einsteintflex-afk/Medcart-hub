// Minimal service worker: makes the app installable and loads the shell offline.
// It NEVER caches /api responses (they contain health data) and never serves stale pages when online.
const SHELL = "medcart-shell-v1";
self.addEventListener("install", e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(["/", "/icon.svg"])).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== SHELL).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/") || url.origin !== location.origin) return; // network only
  if (e.request.mode === "navigate") e.respondWith(fetch(e.request).catch(() => caches.match("/")));
});
