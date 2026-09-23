/* The PWA client: the service worker's registration, its update lifecycle, and the
 * install prompt — the browser conversations Python cannot hold.
 *
 * Loaded by `$pwa`'s `on_client_ready` through the framework's lazy JS loader and served
 * from this package, so it is a plain ES module with no dependencies. It is the only
 * place that talks to `navigator.serviceWorker`, and it keeps that conversation out of
 * Python: every lifecycle event becomes one `basis:pwa` CustomEvent on `document`, which
 * the store mirrors into reactive state. Nothing here renders, and nothing here is state
 * beyond the registration the browser owns.
 *
 * Registered *after* mount, deliberately: this module is loaded by the client's own boot
 * (Pyodide + the app), which is also why the shell's precache carries this URL — an
 * offline cold start must still be able to register before it serves anything.
 */

const EVENT = "basis:pwa";

/* `updateViaCache: "none"` is load-bearing: the browser otherwise revalidates a worker
 * script at most once a day, which can hide a new shell for that long. The root scope is
 * what the worker was served for (`Service-Worker-Allowed: /`). */
const REGISTRATION_OPTIONS = {scope: "/", updateViaCache: "none"};

/*: The declaration as the store sent it: the worker's URL and whether the app wants one.
 * `offline: false` still gets the install prompt — a manifest and an installable app do
 * not require a worker. */
let declaration = {url: "", offline: true};

let registration = null;
let installEvent = null;
let reloadRequested = false;

function emit(detail) {
  document.dispatchEvent(new CustomEvent(EVENT, {detail}));
}

/* The waiting worker's shell version — "which build am I being offered". One
 * MessageChannel round trip, bounded: a worker that never answers must not leave an
 * update prompt spinning forever. */
function workerVersion(worker) {
  return new Promise((resolve) => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => resolve(null), 2000);
    channel.port1.onmessage = (event) => {
      clearTimeout(timer);
      resolve((event.data && event.data.version) || null);
    };
    worker.postMessage({type: "VERSION"}, [channel.port2]);
  });
}

function watchForUpdate(reg) {
  reg.addEventListener("updatefound", () => {
    const installing = reg.installing;
    if (!installing) return;
    installing.addEventListener("statechange", async () => {
      if (installing.state !== "installed") return;
      /* No controller means this is a first install, not an update: the document was
       * rendered by the server a moment ago, so there is nothing newer to offer. */
      if (!navigator.serviceWorker.controller) return;
      emit({kind: "update-ready", version: await workerVersion(installing)});
    });
  });
}

function watchControl() {
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    /* applyUpdate() asked for this takeover: the document is now the *old* build while
     * the worker serving it is the new one, so reload once to make them agree. The first
     * control (clients.claim() on a first visit) is not that case — the server rendered
     * this document — and reloading there would loop. */
    if (reloadRequested) {
      reloadRequested = false;
      window.location.reload();
      return;
    }
    emit({kind: "controlled"});
    warmRuntime();
  });
}

/* The runtime was fetched *before* this worker controlled the page — registering it is
 * part of the client boot — so those bytes are in the HTTP cache but not in CacheStorage,
 * and an offline reload would fail to start the interpreter at all. Asking the worker to
 * cache exactly what the boot used is what makes "offline after one visit" true, and it
 * costs no extra network: it re-reads entries that are already there.
 *
 * The Performance API is the only way to know that set — the worker never saw those
 * requests — and the alternative, having the server name the bundle's files, would
 * download the editors and terminals (megabytes) that this app never loaded. */
function warmRuntime() {
  if (!navigator.onLine || !declaration.runtime) return;
  const worker = navigator.serviceWorker.controller;
  if (!worker) return;
  const prefix = new URL(declaration.runtime, location.origin).href;
  const urls = performance
    .getEntriesByType("resource")
    .map((entry) => entry.name)
    .filter((url) => url.startsWith(prefix));
  if (urls.length) worker.postMessage({type: "WARM", urls});
}


function watchInstall() {
  window.addEventListener("beforeinstallprompt", (event) => {
    /* The browser would show its own mini-infobar; an app rendering its own affordance
     * (bound to $pwa.can_install) needs the event instead. */
    event.preventDefault();
    installEvent = event;
    emit({kind: "installable"});
  });
  window.addEventListener("appinstalled", () => {
    installEvent = null;
    emit({kind: "installed"});
  });
}

/* Register the app shell and start reporting its state. Returns the registration, or
 * null when there is nothing to register (no worker wanted, no API, or a failure the
 * store already heard about). */
export async function register(config = {}) {
  declaration = {...declaration, ...config};
  /* Installability is independent of the worker: `offline: false` is an app that wants
   * the prompt without the cache. */
  watchInstall();
  if (!navigator.serviceWorker) {
    emit({
      kind: "unsupported",
      message:
        "navigator.serviceWorker is unavailable — a service worker needs HTTPS or localhost",
    });
    return null;
  }
  if (!declaration.offline) return null;
  try {
    registration = await navigator.serviceWorker.register(
      declaration.url,
      REGISTRATION_OPTIONS
    );
  } catch (error) {
    emit({kind: "error", message: String((error && error.message) || error)});
    return null;
  }
  watchForUpdate(registration);
  watchControl();
  /* A worker that already controls this page (any visit after the first): there is
   * nothing to wait for, and the page is being served by it right now. Check for a new
   * build while we are here: a navigation's own update check is throttled to once a day
   * in some browsers, which would hide a deploy for that long. Rejects when offline. */
  if (navigator.serviceWorker.controller) {
    emit({kind: "controlled"});
    warmRuntime();
    registration.update().catch(() => undefined);
  }
  return registration;
}

/* Ask a waiting worker to take over. False when there is nothing waiting — which is the
 * honest answer for a click on a button whose gate ($pwa.ready) has already passed. */
export function applyUpdate() {
  const waiting = registration && registration.waiting;
  if (!waiting) return false;
  reloadRequested = true;
  waiting.postMessage({type: "SKIP_WAITING"});
  return true;
}

/* Show the browser's install prompt. False when the browser has not offered one (iOS
 * never does; neither does a browser that considers the app already installed). */
export function install() {
  if (!installEvent) return false;
  const prompted = installEvent;
  /* A prompt is one-shot, and the browser will not offer again in this page's lifetime
   * whatever the user chooses — so the affordance is spent either way. */
  installEvent = null;
  emit({kind: "install-prompted"});
  prompted.prompt();
  return true;
}
