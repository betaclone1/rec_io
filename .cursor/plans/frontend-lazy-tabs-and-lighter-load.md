# Frontend: lazy tabs and lighter initial load

**Goal:** Reduce initial load and unnecessary work by loading tab content on demand instead of preloading and running all tabs (e.g. Trade Monitor) as soon as the page loads. Mobile should be at least as light as desktop; ideally lighter.
**Scope:** In: desktop `index.html` (tab iframes, optional preload/asset trim); mobile `index.html` and nav (verify lazy-load, trim preloads). Out: system-loader (not used by current index), backend changes.
**Status:** done (completed 2026-03-15)

## Context

- **Desktop:** All 9 tab iframes have `src` set in the initial HTML, so every tab loads and runs at once. Trade Monitor and other heavy tabs do work even when the user is on Dashboard. Tabs already receive `tab-visibility`; the bigger win is not loading them until the user opens them.
- **Mobile:** Already lazy-loads: iframes start with empty `src`, only the dashboard frame gets `src` on startup, and other tabs get `src` on first switch. Keep this pattern and ensure mobile stays light (e.g. trim preloads, no new eager loads).
- **Assets:** Many image preloads on both; optional trim so only shell-critical assets preload.

## Steps

### Desktop

1. **Lazy-load tab iframes**  
   In `frontend/index.html`, only the default tab (Dashboard) gets a `src` on first paint. Other iframes start without `src` (or with `about:blank`). When the user clicks a nav item for a tab that has never been loaded, set that iframe’s `src` to the tab URL, then show it. Once set, keep the iframe in the DOM so revisiting that tab is instant.

2. **Preserve visibility and nav behavior**  
   Keep existing tab-switch logic (show/hide frames, set active nav item). When lazily loading a frame, after setting `src` wait for load (or use a short delay) then call the same visibility broadcast so the new tab gets `tab-visibility: true`. Ensure `broadcastTabVisibility` runs when a newly loaded frame becomes active.

3. **Optional: trim image preloads (desktop)**  
   Reduce `<link rel="preload">` in `index.html` to only shell-critical (e.g. logo, dashboard icon, maybe 2–3 others). Document or comment which preloads remain.

### Mobile

4. **Verify and keep mobile lazy-load**  
   Mobile already lazy-loads tabs (only dashboard frame gets `src` on startup; others on first switch). Confirm this behavior is intact and that no new code eagerly loads all frames. Fix any regressions.

5. **Trim mobile preloads**  
   `frontend/mobile/index.html` has 7 icon preloads. Reduce to only what’s needed for the initial shell (e.g. dashboard + tab bar icons that are above the fold). Mobile should be lighter than desktop where possible.

### Both

6. **Document the pattern**  
   Add a short note: “Tabs are loaded on first view (desktop and mobile). Do not add logic that assumes all iframes are loaded on DOMContentLoaded.”

## Completion criteria

- [x] **Desktop:** Only the default tab (Dashboard) loads on initial page load; other tabs load when first selected. Revisiting a tab is instant.
- [x] **Desktop:** Visibility messaging still works so tabs (e.g. Trade Monitor) can pause when hidden and resume when shown.
- [x] **Mobile:** Lazy-load remains in place (only dashboard on startup; other tabs on first open). No new eager loading of all frames.
- [x] **Mobile:** Preloads trimmed so mobile is at least as light as desktop; ideally fewer initial requests than desktop.
- [ ] No regression on either: login → app → navigate each tab and back works. (Manual verification.)
- [x] (Optional) Desktop: fewer preloads for non-critical icons.

## Blockers / decisions

- **Default tab:** Confirm Dashboard remains the default (first `active` frame). Desktop: `dashboardFrame` with `class="content-frame active"`. Mobile: dashboard frame gets `src` in DOMContentLoaded.
- **Deep link / refresh:** If the app ever supports opening a specific tab from the URL, lazy-load must still assign `src` for that tab on init. Out of scope unless already required.
