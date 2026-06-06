# Webapp PDF Rendering Notes

## Architecture

The reader (`/read/{chapter}`) renders PDFs via pdf.js 3.11.174, self-hosted in `static/`. Pages are drawn to a `<canvas>` element sized to fit the viewport. Navigation is tap-zone or keyboard driven. No scrolling — one page at a time.

### Key rendering variables

| Variable | Purpose |
|---|---|
| `rendering` | Mutex — prevents concurrent `renderPage` calls |
| `preCache` | Off-screen canvas holding the next page, pre-decoded |
| `preCacheInFlight` | Prevents a second `preRenderNext` from starting while one is already running |
| `pageRotation` | 0/90/180/270, persisted in `sessionStorage` |
| `zoomLevel / panX / panY` | CSS-transform zoom/pan state; reset on page change |

### Render flow

```
renderPage(n)
  │
  ├─ preCache hit? ──yes──► drawImage(cached canvas) → preRenderNext(n+1) → return
  │
  └─ no ──► preRenderNext(n+1)   ← starts in parallel with this render
             │
             ▼
            pdfDoc.getPage(n) → render to tmp canvas → drawImage to main canvas
```

`preRenderNext` is called **before** the first `await` in the slow path so the next page decodes in parallel with the current one. In the fast path it is called **after** consuming `preCache` (see bug below).

The visible canvas is never cleared to black mid-decode: the slow path renders into a temporary off-screen canvas, then swaps it to the visible canvas in one synchronous step.

---

## Bug: preRenderNext clearing preCache before fast-path check

### What happened

An attempt to start `preRenderNext(n+1)` earlier — at the very top of `renderPage(n)`, before any other work — introduced a regression that silently broke the preCache fast path entirely.

`preRenderNext` runs synchronously until its first `await`. One of its first synchronous steps is:

```js
preCache = null;
```

This clears whatever was in the cache before suspending. When called at the top of `renderPage(n)`, it cleared the preCache for page `n` before the fast-path check had a chance to read it. Every navigation fell through to the slow path — black pages, full decode delay, no benefit from prefetching.

### The fix

`preRenderNext(n+1)` is now called in two distinct places, never at the top:

1. **Fast path** — called *after* `preCache` is consumed and set to `null`:
   ```js
   preCache = null;          // consume
   // ... draw to canvas ...
   preRenderNext(n + 1);     // safe: preCache is already null
   return;
   ```

2. **Slow path** — called *before* the first `await` so it overlaps with the current decode:
   ```js
   preRenderNext(n + 1);     // start next-page decode in background
   const page = await pdfDoc.getPage(n);   // current decode begins
   ```

---

## Cromite / Chromium GPU canvas performance

### Root cause

Chrome/Chromium enables GPU-accelerated 2D canvas by default. For pdf.js this is counterproductive. pdf.js issues hundreds of tiny canvas operations per page — strokes, fills, clip paths, text glyphs. Each operation on a GPU-accelerated canvas queues a GPU command with CPU-side overhead. That overhead accumulates faster than the GPU pays it back on lower-end hardware.

Firefox uses a different Skia configuration (or software rasterisation path in some cases) that handles high-volume small-draw-call workloads significantly faster. This is why the same app feels fast in Firefox and sluggish in Cromite on the same tablet.

This has been documented in Chromium's tracker since at least 2014 ("2D canvas hardware acceleration doubles render time in pdf.js") and is not fully resolved.

A secondary symptom: Chrome uses a heuristic that automatically downgrades a canvas from GPU to CPU-only after detecting readbacks. Because this happens mid-session with no signal to the app, subsequent renders run CPU-only but without the optimisations a deliberately software-backed canvas would have.

### Mitigations applied in code

- **`{alpha: false}`** on every `getContext('2d')` call. PDF pages are opaque; skipping alpha compositing is a free win.
- **`preCacheInFlight` guard** in `preRenderNext` prevents a second decode from racing the first, keeping GPU/CPU load predictable.
- **Temp canvas in slow path** keeps the visible canvas displaying the previous page for the full duration of the decode; no black flash regardless of cache state.

### Remaining option: force software canvas

If the GPU heuristic is the bottleneck, adding `willReadFrequently: true` to every `getContext('2d')` call forces a software-backed canvas from the start, bypassing the automatic downgrade. This is worth trying if hardware-acceleration tests confirm the diagnosis:

1. Open `chrome://flags` in Cromite.
2. Search `accelerated-2d-canvas` and disable it.
3. Relaunch — if rendering becomes fast, the diagnosis is confirmed.
4. Apply in code: change every `{alpha: false}` to `{alpha: false, willReadFrequently: true}`.

Note: `willReadFrequently: true` trades GPU write speed for predictable CPU rendering. For pdf.js on a low-end tablet this is often a net win; on a capable GPU it may be a regression.

### Why pdf.js is self-hosted

pdf.js was previously loaded from `cdnjs.cloudflare.com`. Cromite's built-in content blocker silently dropped that CDN request, leaving the reader stuck on "Loading…" with no error. The files (`pdf.min.js`, `pdf.worker.min.js`) are now bundled in `static/` and served locally.
