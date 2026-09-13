// Minimal service worker — just enough to make the app installable.
// It doesn't cache anything special, so it always loads fresh predictions.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", () => self.clients.claim());
self.addEventListener("fetch", () => {}); // pass-through, no offline caching

