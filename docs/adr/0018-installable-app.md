# ADR 0018: An installable app (PWA, part A), with no company data stored on the device

- Status: accepted
- Date: 2026-11-15
- Changes: the web app's delivery in [ADR 0002](0002-stack-and-layering.md) (adds a service worker)

## Context

The project owner wants SiteSense installable on phones and computers as a progressive web app,
rather than a desktop wrapper such as Electron: the people who most need an app are site engineers
on phones, Electron runs only on desktops, and it would add its own security surface (Node in the
renderer, code signing, shipping every Chromium fix). The work is in two parts:

- **Part A (this ADR, before v1.0):** installable, opens fast and opens with no signal, updates
  safely. No data works offline.
- **Part B (after v1.0):** offline daily reports: drafts and photos kept on the phone and sent when
  the connection returns. It needs server-side de-duplication and clear handling of what changed
  meanwhile (for example a stop-work flag, BR-11, that rejects queued progress), so it is a phase of
  its own.

## Decision

### Manifest and icons

`frontend/public/manifest.json` (served as JSON by nginx, which has no MIME type for
`.webmanifest`): name, `display: standalone`, start URL and scope `/`, theme and background
colours from the design, shortcuts to Daily reports and Materials, and icons drawn from the favicon
by `scripts/make_pwa_icons.py` (192 and 512 px, a maskable 512 px with the house in the safe zone,
and the 180 px Apple touch icon). `index.html` links them.

### The service worker, without a plugin

`src/pwa/sw.ts`, built into `/sw.js` by a small plugin in `vite.config.ts`: Vite's own TypeScript
transform strips the types, and the list of files to store goes in front, with a version that
hashes everything stored, so any release changes `sw.js` and browsers notice it. `vite-plugin-pwa`
(Workbox) was rejected: a large dependency tree for about 100 lines, and every one of its packages
would join the npm audit.

Rules (`strategyFor`, tested):

- **Nothing under `/api/` is ever stored or answered by the worker**, and nothing that is not a GET
  to this origin is touched. Projects, costs, reports, photos and the session always come from the
  server. A shared site phone keeps no company data, a client never sees a cached internal figure,
  and signing out needs no cache clearing, because nothing in the caches belongs to a person.
- **Pages:** network first, so a release shows at once; offline, the stored shell.
- **The shell** (the page, its script and stylesheet, icons, manifest): stored on install.
- **Fingerprinted `/assets/` files** (fonts): stored on first use, per release.
- Lookups ignore `Vary`: the server's `Vary: Origin` or `Accept-Encoding` made stored copies miss,
  because install requests and page requests carry different headers. Safe, since every stored file
  belongs to this release.
- Each release's caches replace the last one's when the new worker takes over.

### Updates and notices

A new worker installs in the background and **waits**. The app shows "A new version of SiteSense is
ready" with a Reload button (`src/pwa/AppNotices.tsx`), so a form being filled in is never reloaded
under someone. The first install never reloads the page. Open tabs check for a release every hour.
When the device is offline, a notice says SiteSense needs a connection to load or save anything.

The worker is registered in production builds only; the dev server never has one.

### Security headers

None change. The CSP's `default-src 'self'` and `script-src 'self'` already allow a same-origin
worker and manifest. nginx serves `/sw.js` with `Cache-Control: no-cache` (it is not under
`/assets/`), as a service worker script must be.

## Consequences

- Installable on Android, iOS (Add to Home Screen) and desktop browsers, over HTTPS (Caddy in
  production). Opening it is faster: the shell comes from the device.
- Offline, the app opens but cannot sign in or show data. With the server unreachable it shows the
  sign-in page, since the session cannot be renewed; a device that knows it is offline also shows
  the offline notice. Part B is where work continues offline.
- iOS keeps a home-screen app's storage only while it is used, and has no background sync; neither
  matters until part B.
- Vite's preview server (`npm run preview`) now proxies `/api` like the dev server, to try the built
  app with its worker locally.
