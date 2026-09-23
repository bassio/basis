/* The Basis app-shell worker.
 *
 * Served at /service-worker.js with a `const BASIS = {…}` prelude injected above this
 * body by basis/plugins/mobile/pwa/service_worker.py, and registered with
 * `{scope: "/", updateViaCache: "none"}`. Classic script on purpose: module workers are
 * Chromium-only, and this file has no dependencies to import.
 *
 * The tiers it implements (see the plan's D5):
 *   - the shell (the app's own code + its start page) is precached at install;
 *   - the Pyodide runtime is *not* precached — it is content-addressed and immutable, so
 *     it is cached the first time it is fetched and never revalidated after;
 *   - navigations are network-first, so a page is never stale while the server is up,
 *     with the last good copy as the offline answer;
 *   - everything else is stale-while-revalidate;
 *   - /basis/api/** is never touched: a cached server action or projection would be a
 *     lie, and the offline mutation queue replays through it.
 */

const SHELL = "basis-shell-" + BASIS.version;
const PAGES = "basis-pages-" + BASIS.version;
const ASSETS = "basis-assets-" + BASIS.version;
const IMMUTABLE = "basis-immutable";

// Content-addressed (and therefore immutable) URLs, plus the runtime's own directory.
const RUNTIME = "/pyscript/";

// Requests that must always reach the server: the action/RPC endpoint, the projections,
// the HMR socket. A worker between the app and its backend would turn a network error
// into a stale success, which is the one failure mode an offline app cannot afford.
const BYPASS = /^\/basis\/api\/|^\/ws\//;

self.addEventListener("install", (event) => {
  // One bad URL must not fail the install: a missing shell entry degrades a route to
  // network-only, while a failed install leaves the app with no worker at all.
  event.waitUntil(
    caches.open(SHELL).then((cache) =>
      Promise.allSettled(
        BASIS.precache.map((url) => cache.add(new Request(url, {cache: "reload"})))
      )
    )
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL, PAGES, ASSETS, IMMUTABLE]);
      for (const name of await caches.keys()) {
        if (!keep.has(name)) await caches.delete(name);
      }
      // Take over the pages that are already open: they are running the same build the
      // server just told us about, so waiting for the next navigation only delays it.
      await self.clients.claim();
    })()
  );
});

self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type === "SKIP_WAITING") {
    self.skipWaiting();
    return;
  }
  if (data.type === "VERSION" && event.ports && event.ports[0]) {
    event.ports[0].postMessage({version: BASIS.version});
    return;
  }
  if (data.type === "WARM" && Array.isArray(data.urls)) {
    // Held open on purpose: a worker with no pending work is stopped, and an
    // interrupted warm leaves exactly the gap it exists to close.
    event.waitUntil(warm(data.urls));
  }
});

function cacheable(response) {
  if (!response || !response.ok || response.type !== "basic") return false;
  const directives = response.headers.get("cache-control") || "";
  // `no-cache` means "revalidate", which is this worker's job; `no-store` means the
  // server said not to keep it, and that outranks a caching policy.
  return !directives.includes("no-store");
}

async function trim(cache, limit) {
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - limit; i++) {
    await cache.delete(keys[i]);
  }
}

async function store(bucket, limit, request, response) {
  const cache = await caches.open(bucket);
  await cache.put(request, response);
  if (limit) await trim(cache, limit);
}

// Cache URLs the page's own boot already fetched — read from the client's Performance
// entries, because a worker cannot see requests made before it controlled the page. Each
// one is a re-read of bytes the browser still has, so this costs no network; an entry
// already cached is skipped, so a second call is a no-op rather than a re-download.
async function warm(urls) {
  const cache = await caches.open(IMMUTABLE);
  await Promise.allSettled(
    urls.map(async (url) => {
      if (await caches.match(url)) return;
      const response = await fetch(url);
      if (!cacheable(response)) return;
      // Read the body *before* putting it: `cache.put` publishes the name while the body
      // is still streaming, so anything reading the cache mid-warm (the next boot, a
      // diagnostic) sees a shell it cannot actually serve, and a stream that fails
      // half-way leaves one behind. Complete body first, then one visible entry.
      const body = await response.arrayBuffer();
      await cache.put(
        url,
        new Response(body, {
          status: response.status,
          statusText: response.statusText,
          headers: response.headers,
        })
      );
    })
  );
}

// A navigation: the server's answer when it has one, the last good copy when it does not,
// and the offline document as the floor.
async function navigation(event) {
  const request = event.request;
  try {
    const response = await fetch(request);
    if (cacheable(response)) await store(PAGES, BASIS.pagesLimit, request, response.clone());
    return response;
  } catch (error) {
    const cached =
      (await caches.match(request, {ignoreSearch: true})) ||
      (BASIS.offline ? await caches.match(BASIS.offline) : undefined);
    if (cached) return cached;
    return Response.error();
  }
}

// The runtime: immutable by construction (its URL carries the bundle's fingerprint), so a
// hit is final and a miss is worth keeping forever.
async function immutable(event) {
  const cached = await caches.match(event.request);
  if (cached) return cached;
  const response = await fetch(event.request);
  if (cacheable(response)) {
    await store(IMMUTABLE, 0, event.request, response.clone());
  }
  return response;
}

// Everything else: answer from the cache now, refresh it in the background. The refresh
// is handed to waitUntil because respondWith resolving early would otherwise let the
// worker be stopped before the new copy is written.
function staleWhileRevalidate(event, bucket, limit) {
  const request = event.request;
  const refresh = fetch(request)
    .then(async (response) => {
      if (cacheable(response)) await store(bucket, limit, request, response.clone());
      return response;
    })
    .catch(() => undefined);
  event.waitUntil(refresh);

  return caches.match(request).then((cached) => cached || refresh.then((r) => r || Response.error()));
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (BYPASS.test(url.pathname)) return;

  if (request.mode === "navigate") {
    event.respondWith(navigation(event));
    return;
  }
  if (url.pathname.startsWith(RUNTIME)) {
    event.respondWith(immutable(event));
    return;
  }
  event.respondWith(staleWhileRevalidate(event, ASSETS, BASIS.assetsLimit));
});
