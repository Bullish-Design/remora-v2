# 68 — Resizable Sidebar

## Goal

Make the right sidebar (`#sidebar`) width-resizable via a drag handle so users can widen it for agent conversations or narrow it to maximize the graph view during demos.

## Current Layout

The top-level layout is a CSS flexbox (`body { display: flex }`):

```
┌──────────────────────────────┬────────────┐
│  #graph-container (flex: 1)  │  #sidebar  │
│                              │  (fixed w) │
│  ┌─ #filter-bar (abs)        │            │
│  │  ┌─ #graph (abs inset:0)  │            │
│  └──┘                        │            │
│  ┌─ #zoom-controls (abs)     │            │
│  └──┘                        │            │
└──────────────────────────────┴────────────┘
```

- `#graph-container`: `flex: 1; position: relative; min-height: 100vh`
- `#sidebar`: `width: clamp(320px, 30vw, 400px)` (narrower clamp at `@media max-width: 1180px`)
- No resize handle exists today

## File to Modify

**`src/remora/web/static/index.html`** — single file; all CSS is inline in `<style>`, all HTML in the `<body>`. No external CSS files.

## Sidebar Structure (elements that must adapt)

All inside `<aside id="sidebar">`:

| Element | Current sizing constraint | Adaptation needed |
|---|---|---|
| `#sidebar` | `width: clamp(320px, 30vw, 400px)`, `padding: 18px`, `overflow-y: auto` | Replace clamped width with a JS-controlled inline width; set `min-width` / `max-width` bounds; add `flex-shrink: 0` |
| `.summary-grid` | `grid-template-columns: repeat(2, minmax(0, 1fr))` | Already fluid — no change |
| `#quick-actions` | `grid-template-columns: repeat(2, minmax(0, 1fr))` | Already fluid — no change |
| `#node-details pre` | `max-height: 220px; white-space: pre-wrap` | Already fluid — no change |
| `#agent-stream` | `max-height: 300px; overflow: auto` | Already fluid — no change |
| `textarea#chat-input` | `width: 100%` | Already fluid — no change |
| `#events` | `max-height: 180px; white-space: pre-wrap` | Already fluid — no change |
| `#timeline-container` | `max-height: 220px` | Already fluid — no change |
| `.timeline-event` | `grid-template-columns: 80px 1fr` | Already fluid — no change |

**All inner panels use `width: 100%` or grid `1fr` — they will adapt automatically once the sidebar width changes.** The only real work is on the sidebar element itself and the drag handle.

## What Needs to Happen

### 1. CSS additions (in `<style>`)

- **Drag handle**: A narrow vertical element (`#sidebar-resize-handle`) positioned on the left edge of the sidebar (or between `#graph-container` and `#sidebar`). Styled as a 5-6px wide strip with `cursor: col-resize`.
- **`#sidebar`**: Replace `width: clamp(...)` with `min-width: 280px; max-width: 60vw; width: 380px` (sensible default). Add `flex-shrink: 0` so flex doesn't override the explicit width.
- **Remove the `@media` override** (lines 56-60) — it sets a different clamp that would fight with the user's resize.

### 2. HTML additions (in `<body>`)

- Insert a `<div id="sidebar-resize-handle"></div>` between `#graph-container` and `<aside id="sidebar">` (or as a pseudo-element / first-child of `#sidebar`).

### 3. JS additions (inline `<script>` or in `main.js`)

- `mousedown` on the handle starts tracking.
- `mousemove` on `document` computes new width: `window.innerWidth - e.clientX`.
- `mouseup` ends tracking.
- Clamp to `[280, 0.6 * window.innerWidth]`.
- Set `sidebar.style.width = newWidth + 'px'`.
- On resize end, trigger Sigma's `renderer.refresh()` since the graph container size changed (Sigma listens for container resizes but an explicit nudge ensures smooth redraw).
- Persist width to `localStorage` so it survives page reload (nice-to-have).

### 4. Graph container interaction

- `#graph-container` is `flex: 1` so it automatically shrinks/grows as the sidebar width changes — **no change needed**.
- The `syncLayoutExclusionZones()` function in `main.js` reads `#graph` and `#filter-bar` bounding rects on every layout pass, so filter bar positioning adapts automatically.
- Sigma's canvas auto-sizes to its container via ResizeObserver internally.

## Summary of Changes

| Area | Scope |
|---|---|
| `index.html` `<style>` | ~15 lines: handle styles, sidebar min/max-width, remove media query |
| `index.html` `<body>` | 1 line: add resize handle div |
| `main.js` or inline `<script>` | ~30 lines: mousedown/mousemove/mouseup drag logic, optional localStorage persist, renderer refresh on end |
