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
    .bar {{ background:#15171d; border-bottom:1px solid #23262f; padding:8px 14px;
            display:flex; align-items:center; gap:10px; flex-shrink:0; min-width:0; }}
    .bar a {{ color:#ffd23f; text-decoration:none; font-size:13px; font-weight:600; white-space:nowrap; }}
    .bar a:hover {{ color:#fff; }}
    .bar a.disabled {{ color:#444; pointer-events:none; }}
    .bar .ch-title {{ color:#e8e6e1; font-size:13px; font-weight:600;
                      overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
                      flex:1; text-align:center; min-width:0; }}
    #viewer {{ flex:1; overflow:hidden; display:flex; align-items:center; justify-content:center;
               position:relative; background:#0e0f13; }}
    #page-canvas {{ display:block; }}
    .hit-zone {{ position:absolute; top:0; bottom:0; width:35%; cursor:pointer; z-index:10; }}
    #hz-prev {{ left:0; }}
    #hz-next {{ right:0; }}
    .page-info {{ position:absolute; bottom:12px; left:50%; transform:translateX(-50%);
                  background:rgba(0,0,0,.55); color:#999; font-size:11px;
                  padding:3px 9px; border-radius:8px; pointer-events:none; }}
    #end-screen {{ position:absolute; inset:0; background:rgba(0,0,0,.82);
                   display:none; align-items:center; justify-content:center;
                   flex-direction:column; gap:18px; z-index:20; }}
    #end-screen.show {{ display:flex; }}
    #end-screen .msg {{ color:#ccc; font-size:15px; }}
    #next-ch-btn {{ background:#ffd23f; color:#111; border:none; padding:12px 32px;
                    border-radius:6px; font-size:16px; font-weight:700; cursor:pointer;
                    text-decoration:none; display:none; }}
    #next-ch-btn:hover {{ background:#ffe070; }}
    #back-btn-end {{ color:#888; font-size:13px; text-decoration:none; }}
    #back-btn-end:hover {{ color:#ccc; }}
    #loading {{ position:absolute; inset:0; display:flex; align-items:center;
                justify-content:center; color:#555; font-size:14px; }}
  </style>
</head>
<body>
  <div class="bar">
    <a href="/">&larr; Library</a>
    <a id="prev-ch" class="disabled" href="#">&lsaquo; Prev</a>
    <span class="ch-title" id="ch-title"></span>
    <a id="next-ch" class="disabled" href="#">Next &rsaquo;</a>
    <a href="{dl_url}">&#8595;</a>
  </div>
  <div id="viewer">
    <div id="loading">Loading&hellip;</div>
    <canvas id="page-canvas" style="display:none"></canvas>
    <div class="hit-zone" id="hz-prev"></div>
    <div class="hit-zone" id="hz-next"></div>
    <div class="page-info" id="page-info"></div>
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

    let pdfDoc = null, currentPage = 1, totalPages = 0, rendering = false;

    function updateNav(chapters) {{
      const sorted = chapters.slice().sort((a, b) => a.chapter - b.chapter);
      const idx = sorted.findIndex(c => c.chapter === CHAPTER);
      const prevEl = document.getElementById('prev-ch');
      const nextEl = document.getElementById('next-ch');
      const nextBtn = document.getElementById('next-ch-btn');
      if (idx > 0) {{
        prevEl.href = `/read/${{sorted[idx - 1].chapter}}`;
        prevEl.classList.remove('disabled');
      }}
      if (idx >= 0 && idx < sorted.length - 1) {{
        const u = `/read/${{sorted[idx + 1].chapter}}`;
        nextEl.href = u;
        nextEl.classList.remove('disabled');
        nextBtn.href = u;
        nextBtn.style.display = 'inline-block';
      }}
    }}

    async function init() {{
      document.getElementById('ch-title').textContent = TITLE;
      try {{
        const data = await fetch('/api/chapters').then(r => r.json());
        updateNav(data);
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
      try {{
        const page = await pdfDoc.getPage(n);
        const vp0 = page.getViewport({{scale: 1}});
        const viewer = document.getElementById('viewer');
        const dpr = window.devicePixelRatio || 1;
        const scale = Math.min(viewer.clientHeight / vp0.height, viewer.clientWidth / vp0.width) * dpr;
        const vp = page.getViewport({{scale}});
        // Render to offscreen canvas first — no await between clear and fill on the visible canvas
        const tmp = document.createElement('canvas');
        tmp.width = Math.round(vp.width);
        tmp.height = Math.round(vp.height);
        await page.render({{canvasContext: tmp.getContext('2d'), viewport: vp}}).promise;
        // Atomic swap: synchronous, browser can't paint between these lines
        const canvas = document.getElementById('page-canvas');
        canvas.width = tmp.width;
        canvas.height = tmp.height;
        canvas.style.width = (tmp.width / dpr) + 'px';
        canvas.style.height = (tmp.height / dpr) + 'px';
        canvas.getContext('2d').drawImage(tmp, 0, 0);
        if (fade) {{
          canvas.style.opacity = '0';
          void canvas.offsetWidth;
          canvas.style.transition = 'opacity 0.2s';
          canvas.style.opacity = '1';
        }} else {{
          canvas.style.transition = 'none';
          canvas.style.opacity = '1';
        }}
        currentPage = n;
        document.getElementById('page-info').textContent = `${{n}} / ${{totalPages}}`;
        document.getElementById('end-screen').classList.remove('show');
      }} finally {{
        rendering = false;
      }}
    }}

    function goNext() {{
      if (currentPage < totalPages) {{ renderPage(currentPage + 1); }}
      else {{ document.getElementById('end-screen').classList.add('show'); }}
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
    }});

    if (window.visualViewport) {{
      let _zt = null;
      window.visualViewport.addEventListener('resize', () => {{
        clearTimeout(_zt);
        _zt = setTimeout(() => {{ if (pdfDoc) renderPage(currentPage, true); }}, 350);
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
