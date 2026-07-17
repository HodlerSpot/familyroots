/* FutureRoots service worker — web push only.
 *
 * Kept deliberately tiny and dependency-free: no caching, no offline logic.
 * Its only jobs are (1) showing push notifications and (2) bringing the
 * family's tab forward when one is tapped.
 */

self.addEventListener("install", () => {
  // Activate immediately so push works right after enrollment, no reload needed.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  // Payload contract (see services/notify.py): {title, body, url, tag}.
  // Code defensively — show something warm even if a field is missing.
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    // Non-JSON payload; fall back to defaults below.
  }
  const title = data.title || "FutureRoots";
  const options = {
    body: data.body || "Something new is waiting for your family.",
    tag: data.tag || undefined,
    icon: "/logo-mark.png",
    data: { url: data.url || "/family" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/family";
  // Guard against a malicious/absolute url ever reaching openWindow/navigate:
  // only ever go to a same-origin destination, falling back to the family
  // feed otherwise. Belt-and-suspenders — the API also validates this.
  const resolved = new URL(url, self.location.origin);
  const target = resolved.origin === self.location.origin
    ? resolved.href
    : new URL("/family", self.location.origin).href;
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientList) => {
        // Prefer an already-open FutureRoots tab: focus it and navigate.
        for (const client of clientList) {
          if (new URL(client.url).origin === self.location.origin && "focus" in client) {
            return client.focus().then((focused) =>
              "navigate" in focused ? focused.navigate(target) : focused
            );
          }
        }
        return self.clients.openWindow(target);
      })
  );
});
