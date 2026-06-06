#!/usr/bin/env python3
"""Webapp service: browse, read, download chapters and request missing ones.

A read-mostly consumer of the shared storage. Serving PDFs via Starlette's
FileResponse gives range/streaming support, so the in-browser reader streams
rather than downloading the whole file first. Requesting a missing chapter just
drops a marker in the storage request queue, which the downloader fulfills.

Env:
  ONEPIECE_STORAGE   storage root (shared volume)
  WEBAPP_PORT        listen port (default 8080)
"""

import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from onepiece.storage import Storage

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

storage = Storage()
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="One Piece Library")


# --- framework-free helpers (unit-testable without FastAPI) ----------------
def chapters_payload(store):
    """Chapters present in storage, newest first, with display metadata."""
    out = []
    for ch in sorted(store.list_chapters(), reverse=True):
        meta = store.read_meta(ch) or {}
        out.append({
            "chapter": ch,
            "title": meta.get("title") or f"One Piece Chapter {ch}",
            "pages": meta.get("pages"),
            "downloaded_at": meta.get("downloaded_at"),
            "has_preview": os.path.exists(store.preview_path(ch)),
        })
    return out


def enqueue_request(store, chapter):
    """Queue a missing chapter for the downloader. Returns a status dict."""
    if chapter <= 0:
        return {"status": "invalid", "chapter": chapter}
    if store.has_chapter(chapter):
        return {"status": "present", "chapter": chapter}
    store.request_chapter(chapter)
    return {"status": "requested", "chapter": chapter}


# --- API -------------------------------------------------------------------
@app.get("/api/chapters")
def api_chapters():
    return chapters_payload(storage)


@app.get("/api/requests")
def api_requests():
    return {"pending": storage.pending_requests()}


@app.get("/api/stats")
def api_stats():
    """Library status for dashboards (e.g. Homepage's Custom API widget)."""
    chapters = storage.list_chapters()
    newest_meta = storage.read_meta(chapters[-1]) if chapters else {}
    return {
        "last_chapter": storage.get_last_chapter(),
        "file_count": len(chapters),
        "downloaded_at": (newest_meta or {}).get("downloaded_at"),
        "pending_requests": len(storage.pending_requests()),
        "last_check": storage.get_last_check(),
    }


@app.post("/api/request/{chapter}")
def api_request(chapter: int):
    result = enqueue_request(storage, chapter)
    if result["status"] == "invalid":
        raise HTTPException(status_code=400, detail="invalid chapter")
    return result


@app.delete("/api/request/{chapter}")
def api_cancel_request(chapter: int):
    """Revoke a queued request (e.g. a chapter that failed or doesn't exist)."""
    storage.clear_request(chapter)
    return {"status": "cancelled", "chapter": chapter}


# --- files -----------------------------------------------------------------
@app.get("/preview/{chapter}")
def preview(chapter: int):
    path = storage.preview_path(chapter)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="no preview")
    return FileResponse(path, media_type="image/png")


@app.get("/pdf/{chapter}")
def pdf(chapter: int, dl: int = 0):
    path = storage.pdf_path(chapter)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="no pdf")
    disposition = "attachment" if dl else "inline"
    filename = os.path.basename(path)
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@app.get("/read/{chapter}", response_class=HTMLResponse)
def read(chapter: int):
    if not os.path.exists(storage.pdf_path(chapter)):
        raise HTTPException(status_code=404, detail="no pdf")
    meta = storage.read_meta(chapter) or {}
    title = meta.get("title") or f"One Piece Chapter {chapter}"
    chapter_js = json.dumps(chapter)
    title_js = json.dumps(title)
    pdf_url = f"/pdf/{chapter}"
    pdf_url_js = json.dumps(pdf_url)
    dl_url = f"{pdf_url}?dl=1"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:#0e0f13; height:100vh; display:flex; flex-direction:column; overflow:hidden;
           font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; color:#e8e6e1; }}
    .bar {{ background:#15171d; border-bottom:1px solid #23262f; padding:6px 10px;
            display:flex; align-items:center; gap:2px; flex-shrink:0; min-width:0; }}
    .bar a {{ color:#ffd23f; text-decoration:none; font-size:15px; font-weight:700;
              white-space:nowrap; padding:10px 12px; border-radius:8px; min-height:44px;
              display:inline-flex; align-items:center; }}
    .bar a:hover {{ color:#fff; background:rgba(255,255,255,.1); }}
    .bar a.disabled {{ color:#333; pointer-events:none; background:none; }}
    .bar .ch-title {{ color:#e8e6e1; font-size:13px; font-weight:600;
                      overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
                      flex:1; text-align:center; min-width:0; }}
    #fs-btn {{ background:none; border:none; color:#ffd23f; cursor:pointer;
               padding:10px 12px; border-radius:8px; min-height:44px; min-width:44px;
               display:inline-flex; align-items:center; justify-content:center;
               flex-shrink:0; }}
    #fs-btn:hover {{ color:#fff; background:rgba(255,255,255,.1); }}
    @media (max-width:600px) {{
      .bar a {{ font-size:18px; padding:12px 14px; min-height:52px; }}
      #fs-btn {{ padding:12px 14px; min-height:52px; min-width:52px; }}
      .bar .ch-title {{ font-size:12px; }}
    }}
    #viewer {{ flex:1; overflow:hidden; display:flex; align-items:center; justify-content:center;
               position:relative; background:#0e0f13; }}
    #page-canvas {{ display:block; }}
    #page-canvas-over {{ display:none; position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); pointer-events:none; }}
    .hit-zone {{ position:absolute; top:0; bottom:0; width:35%; cursor:pointer; z-index:10; }}
    #hz-prev {{ left:0; }}
    #hz-next {{ right:0; }}
    .page-info {{ position:absolute; bottom:12px; left:50%; transform:translateX(-50%);
                  background:rgba(0,0,0,.55); color:#999; font-size:11px;
                  padding:3px 9px; border-radius:8px; pointer-events:none; }}
    #end-screen {{ position:absolute; inset:0; background:rgba(0,0,0,.82);
                   display:none; align-items:center; justify-content:center;
                   flex-direction:column; gap:18px; z-index:20;
                   pointer-events:none; }}
    #end-screen.show {{ display:flex; }}
    #end-screen > * {{ pointer-events:auto; }}
    #end-screen .msg {{ color:#ccc; font-size:15px; }}
    #next-ch-btn {{ background:#ffd23f; color:#111; border:none; padding:12px 32px;
                    border-radius:6px; font-size:16px; font-weight:700; cursor:pointer;
                    text-decoration:none; display:none; }}
    #next-ch-btn:hover {{ background:#ffe070; }}
    #back-btn-end {{ color:#888; font-size:13px; text-decoration:none; }}
    #back-btn-end:hover {{ color:#ccc; }}
    #loading {{ position:absolute; inset:0; display:flex; align-items:center;
                justify-content:center; color:#555; font-size:14px; }}
    /*#dbg {{ position:absolute; top:8px; right:8px; background:rgba(0,0,0,.75);
            color:#ffd23f; font-size:10px; font-family:monospace; padding:6px 8px;
            border-radius:6px; pointer-events:none; z-index:30; white-space:pre;
            line-height:1.5; }}*/
    :fullscreen .bar {{ display: none; }}
    :-webkit-full-screen .bar {{ display: none; }}
  </style>
</head>
<body>
  <div class="bar">
    <a href="/">&larr; Library</a>
    <a id="prev-ch" class="disabled" href="#">&lsaquo; Prev</a>
    <span class="ch-title" id="ch-title"></span>
    <a id="next-ch" class="disabled" href="#">Next &rsaquo;</a>
    <a id="dl-btn" href="{dl_url}">&#8595;</a>
    <button id="fs-btn" title="Fullscreen"></button>
  </div>
  <div id="viewer">
    <div id="loading">Loading&hellip;</div>
    <canvas id="page-canvas" style="display:none"></canvas>
    <canvas id="page-canvas-over"></canvas>
    <div class="hit-zone" id="hz-prev"></div>
    <div class="hit-zone" id="hz-next"></div>
    <div class="page-info" id="page-info"></div>
    <!--<div id="dbg">waiting...</div>-->
    <div id="end-screen">
      <div class="msg" id="end-msg">End of chapter</div>
      <a id="next-ch-btn" href="#">Continue to next chapter &rarr;</a>
      <a id="back-btn-end" href="/">&larr; Back to library</a>
    </div>
  </div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
  <script>
    const CHAPTER = {chapter_js};
    const TITLE = {title_js};
    const PDF_URL = {pdf_url_js};

    pdfjsLib.GlobalWorkerOptions.workerSrc =
      'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

    let pdfDoc = null, currentPage = 1, totalPages = 0, rendering = false, overTimer = null;
    let preCache = null, preCacheSeq = 0;
    let pageRotation = parseInt(sessionStorage.getItem('page_rotation') || '0');
    let zoomLevel = 1, panX = 0, panY = 0;
    const MAX_ZOOM = 3;
    let currentChapter = CHAPTER;
    let nextChapter = null;

    function clampPan() {{
      const c = document.getElementById('page-canvas');
      const v = document.getElementById('viewer');
      const maxPx = Math.max(0, (c.offsetWidth * zoomLevel - v.clientWidth) / 2);
      const maxPy = Math.max(0, (c.offsetHeight * zoomLevel - v.clientHeight) / 2);
      panX = Math.max(-maxPx, Math.min(maxPx, panX));
      panY = Math.max(-maxPy, Math.min(maxPy, panY));
    }}
    function applyZoom() {{
      const c = document.getElementById('page-canvas');
      clampPan();
      c.style.transform = zoomLevel === 1
        ? ''
        : `scale(${{zoomLevel}}) translate(${{panX / zoomLevel}}px, ${{panY / zoomLevel}}px)`;
    }}
    function resetZoom() {{
      zoomLevel = 1; panX = 0; panY = 0;
      document.getElementById('page-canvas').style.transform = '';
    }}

    function updateNav(chapters, ch) {{
      const sorted = chapters.slice().sort((a, b) => a.chapter - b.chapter);
      const idx = sorted.findIndex(c => c.chapter === ch);
      const prevEl = document.getElementById('prev-ch');
      const nextEl = document.getElementById('next-ch');
      const nextBtn = document.getElementById('next-ch-btn');
      prevEl.classList.add('disabled');
      prevEl.onclick = null;
      nextEl.classList.add('disabled');
      nextEl.onclick = null;
      nextBtn.style.display = 'none';
      nextBtn.onclick = null;
      nextChapter = null;
      if (idx > 0) {{
        const prev = sorted[idx - 1].chapter;
        prevEl.href = `/read/${{prev}}`;
        prevEl.classList.remove('disabled');
        prevEl.onclick = (e) => {{ e.preventDefault(); loadChapter(prev); }};
      }}
      if (idx >= 0 && idx < sorted.length - 1) {{
        nextChapter = sorted[idx + 1].chapter;
        const u = `/read/${{nextChapter}}`;
        nextEl.href = u;
        nextEl.classList.remove('disabled');
        nextEl.onclick = (e) => {{ e.preventDefault(); loadChapter(nextChapter); }};
        nextBtn.href = u;
        nextBtn.style.display = 'inline-block';
        nextBtn.onclick = (e) => {{ e.preventDefault(); loadChapter(nextChapter); }};
      }}
    }}

    async function loadChapter(ch) {{
      currentChapter = ch;
      if (pdfDoc) {{ pdfDoc.destroy(); pdfDoc = null; }}
      currentPage = 1; totalPages = 0; preCache = null; preCacheSeq = 0; rendering = false;
      clearTimeout(overTimer);
      resetZoom();
      document.getElementById('end-screen').classList.remove('show');
      document.getElementById('page-canvas').style.display = 'none';
      document.getElementById('page-canvas-over').style.display = 'none';
      const loadingEl = document.getElementById('loading');
      loadingEl.textContent = 'Loading…';
      loadingEl.style.display = 'flex';
      history.pushState(null, '', `/read/${{ch}}`);
      try {{
        const data = await fetch('/api/chapters').then(r => r.json());
        const meta = data.find(c => c.chapter === ch);
        const title = (meta && meta.title) || `One Piece Chapter ${{ch}}`;
        document.getElementById('ch-title').textContent = title;
        document.title = title;
        document.getElementById('dl-btn').href = `/pdf/${{ch}}?dl=1`;
        updateNav(data, ch);
        pdfDoc = await pdfjsLib.getDocument(`/pdf/${{ch}}`).promise;
        totalPages = pdfDoc.numPages;
        loadingEl.style.display = 'none';
        document.getElementById('page-canvas').style.display = 'block';
        await renderPage(1);
      }} catch(e) {{
        loadingEl.textContent = 'Failed to load chapter.';
      }}
    }}

    async function init() {{
      document.getElementById('ch-title').textContent = TITLE;
      try {{
        const data = await fetch('/api/chapters').then(r => r.json());
        updateNav(data, CHAPTER);
      }} catch(e) {{}}
      try {{
        pdfDoc = await pdfjsLib.getDocument(PDF_URL).promise;
        totalPages = pdfDoc.numPages;
        document.getElementById('loading').style.display = 'none';
        document.getElementById('page-canvas').style.display = 'block';
        const startPage = Math.min(Math.max(parseInt(new URLSearchParams(window.location.search).get('page')) || 1, 1), totalPages);
        await renderPage(startPage);
      }} catch(e) {{
        document.getElementById('loading').textContent = 'Failed to load PDF.';
      }}
    }}

    async function renderPage(n, fade) {{
      if (rendering || !pdfDoc) return;
      rendering = true;
      ++preCacheSeq;
      clearTimeout(overTimer);
      const over = document.getElementById('page-canvas-over');
      over.style.display = 'none';
      try {{
        const canvas = document.getElementById('page-canvas');
        // Fast path: use pre-rendered cache (eliminates the blank-canvas flash)
        if (!fade && preCache && preCache.page === n && preCache.rotation === pageRotation) {{
          if (n !== currentPage) resetZoom();
          const cached = preCache;
          preCache = null;
          canvas.width = cached.canvas.width;
          canvas.height = cached.canvas.height;
          canvas.style.width = Math.round(cached.canvas.width / cached.dpr) + 'px';
          canvas.style.height = Math.round(cached.canvas.height / cached.dpr) + 'px';
          canvas.getContext('2d').drawImage(cached.canvas, 0, 0);
          cached.canvas.width = 0; cached.canvas.height = 0;
          currentPage = n;
          document.getElementById('page-info').textContent = `${{n}} / ${{totalPages}}`;
          document.getElementById('end-screen').classList.remove('show');
          preRenderNext(n + 1);
          return;
        }}
        if (n !== currentPage) resetZoom();
        const page = await pdfDoc.getPage(n);
        const vp0 = page.getViewport({{scale: 1, rotation: pageRotation}});
        const viewer = document.getElementById('viewer');
        // Cap DPR at 2 — multiplying zoom into DPR makes canvases enormous on tablets
        // and causes OOM crashes in Firefox Mobile when pinch-zooming.
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const fitScale = Math.min(viewer.clientHeight / vp0.height, viewer.clientWidth / vp0.width);
        const scale = fitScale * dpr;
        const vp = page.getViewport({{scale, rotation: pageRotation}});
        const cssW = Math.round(vp.width / dpr) + 'px';
        const cssH = Math.round(vp.height / dpr) + 'px';
        if (fade) {{
          // Render directly into overlay canvas (no tmp copy = half the memory)
          const w = Math.round(vp.width);
          const h = Math.round(vp.height);
          over.width = w;
          over.height = h;
          over.style.width = cssW;
          over.style.height = cssH;
          over.style.transition = 'none';
          over.style.opacity = '0';
          over.style.display = 'none';
          await page.render({{canvasContext: over.getContext('2d'), viewport: vp}}).promise;
          page.cleanup();
          over.style.display = 'block';
          void over.offsetWidth;
          over.style.transition = 'opacity 0.25s';
          over.style.opacity = '1';
          overTimer = setTimeout(() => {{
            canvas.width = w;
            canvas.height = h;
            canvas.style.width = cssW;
            canvas.style.height = cssH;
            canvas.getContext('2d').drawImage(over, 0, 0);
            over.style.transition = 'none';
            over.style.opacity = '0';
            over.style.display = 'none';
            over.width = 0; over.height = 0;
          }}, 280);
        }} else {{
          canvas.width = Math.round(vp.width);
          canvas.height = Math.round(vp.height);
          canvas.style.width = cssW;
          canvas.style.height = cssH;
          await page.render({{canvasContext: canvas.getContext('2d'), viewport: vp}}).promise;
          page.cleanup();
        }}
        currentPage = n;
        document.getElementById('page-info').textContent = `${{n}} / ${{totalPages}}`;
        document.getElementById('end-screen').classList.remove('show');
        preRenderNext(n + 1);
      }} finally {{
        rendering = false;
      }}
    }}

    async function preRenderNext(n) {{
      if (!pdfDoc || n < 1 || n > totalPages) return;
      if (preCache && preCache.page === n) return;
      preCache = null;
      const seq = ++preCacheSeq;
      try {{
        const page = await pdfDoc.getPage(n);
        const vp0 = page.getViewport({{scale: 1, rotation: pageRotation}});
        const viewer = document.getElementById('viewer');
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const fitScale = Math.min(viewer.clientHeight / vp0.height, viewer.clientWidth / vp0.width);
        const vp = page.getViewport({{scale: fitScale * dpr, rotation: pageRotation}});
        const tmp = document.createElement('canvas');
        tmp.width = Math.round(vp.width);
        tmp.height = Math.round(vp.height);
        await page.render({{canvasContext: tmp.getContext('2d'), viewport: vp}}).promise;
        page.cleanup();
        if (seq !== preCacheSeq) {{ tmp.width = 0; tmp.height = 0; return; }}
        preCache = {{page: n, canvas: tmp, dpr, rotation: pageRotation}};
      }} catch(e) {{}}
    }}

    function goNext() {{
      const endScreen = document.getElementById('end-screen');
      if (endScreen.classList.contains('show')) {{
        if (nextChapter !== null) loadChapter(nextChapter);
      }} else if (currentPage < totalPages) {{
        renderPage(currentPage + 1);
      }} else {{
        endScreen.classList.add('show');
      }}
    }}
    function goPrev() {{
      if (document.getElementById('end-screen').classList.contains('show')) {{
        document.getElementById('end-screen').classList.remove('show');
      }} else if (currentPage > 1) {{
        renderPage(currentPage - 1);
      }}
    }}

    document.getElementById('hz-next').addEventListener('click', goNext);
    document.getElementById('hz-prev').addEventListener('click', goPrev);
    document.addEventListener('keydown', e => {{
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') goNext();
      if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') goPrev();
      if (e.key === 'f' || e.key === 'F') document.getElementById('fs-btn').click();
      if (e.key === 'r') {{
        pageRotation = (pageRotation + 270) % 360;
        sessionStorage.setItem('page_rotation', pageRotation);
        preCache = null;
        renderPage(currentPage);
      }}
      if (e.key === 'R') {{
        pageRotation = (pageRotation + 90) % 360;
        sessionStorage.setItem('page_rotation', pageRotation);
        preCache = null;
        renderPage(currentPage);
      }}
      if (e.key === '+' || e.key === '=') {{ zoomLevel = Math.min(MAX_ZOOM, parseFloat((zoomLevel + 0.5).toFixed(1))); applyZoom(); }}
      if (e.key === '-' || e.key === '_') {{ zoomLevel = Math.max(1, parseFloat((zoomLevel - 0.5).toFixed(1))); applyZoom(); }}
      if (e.key === '0') resetZoom();
    }});

    // Fullscreen toggle
    const fsBtn = document.getElementById('fs-btn');
    const FS_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M1 6V1h5M10 1h5v5M15 10v5h-5M6 15H1v-5"/></svg>';
    const EX_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 1v5H1M15 6h-5V1M10 15v-5h5M1 10h5v5"/></svg>';
    function updateFsBtn() {{
      const inFs = !!document.fullscreenElement;
      fsBtn.innerHTML = inFs ? EX_ICON : FS_ICON;
      fsBtn.title = inFs ? 'Exit fullscreen' : 'Fullscreen';
    }}
    updateFsBtn();
    fsBtn.addEventListener('click', () => {{
      if (document.fullscreenElement) {{ document.exitFullscreen(); }}
      else {{ document.documentElement.requestFullscreen().catch(() => {{}}); }}
    }});
    document.addEventListener('fullscreenchange', updateFsBtn);

    // Zoom + pan
    (function() {{
      const viewer = document.getElementById('viewer');
      // Pinch to zoom
      let _pd = null;
      viewer.addEventListener('touchstart', e => {{ if (e.touches.length === 2) _pd = null; }}, {{passive: true}});
      viewer.addEventListener('touchmove', e => {{
        if (e.touches.length !== 2) return;
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (_pd !== null) {{ zoomLevel = Math.max(1, Math.min(MAX_ZOOM, zoomLevel * dist / _pd)); applyZoom(); }}
        _pd = dist;
        e.preventDefault();
      }}, {{passive: false}});
      viewer.addEventListener('touchend', e => {{ if (e.touches.length < 2) _pd = null; }}, {{passive: true}});
      // Drag to pan when zoomed
      let _drag = null, _sc = false;
      viewer.addEventListener('click', e => {{ if (_sc) {{ e.stopPropagation(); _sc = false; }} }}, true);
      viewer.addEventListener('pointerdown', e => {{
        if (e.isPrimary && zoomLevel > 1)
          _drag = {{x: e.clientX, y: e.clientY, px0: panX, py0: panY, moved: false}};
      }});
      viewer.addEventListener('pointermove', e => {{
        if (!_drag || !e.isPrimary) return;
        const dx = e.clientX - _drag.x, dy = e.clientY - _drag.y;
        if (Math.abs(dx) > 4 || Math.abs(dy) > 4) _drag.moved = true;
        if (_drag.moved) {{ panX = _drag.px0 + dx; panY = _drag.py0 + dy; applyZoom(); }}
      }});
      viewer.addEventListener('pointerup', () => {{ if (_drag && _drag.moved) _sc = true; _drag = null; }});
      viewer.addEventListener('pointercancel', () => {{ _drag = null; }});
    }})();

    if (window.visualViewport) {{
      let _zt = null;
      window.visualViewport.addEventListener('resize', () => {{
        preCache = null;
        clearTimeout(_zt);
        _zt = setTimeout(() => {{
          // Skip re-render when user is pinch-zooming — that would create a
          // massive canvas proportional to zoom level and crash low-memory devices.
          // Only re-render on genuine viewport changes (rotation, browser chrome).
          if (pdfDoc && window.visualViewport.scale <= 1.05) {{
            renderPage(currentPage, true);
          }}
        }}, 350);
      }});
    }}

    init();
  </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("WEBAPP_PORT", "8080")))
