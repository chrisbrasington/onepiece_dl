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


@app.post("/api/request/{chapter}")
def api_request(chapter: int):
    result = enqueue_request(storage, chapter)
    if result["status"] == "invalid":
        raise HTTPException(status_code=400, detail="invalid chapter")
    return result


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
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  html,body{{margin:0;height:100%;background:#0e0f13;color:#e8e6e1;
    font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
  .bar{{display:flex;gap:1rem;align-items:center;padding:.6rem 1rem;
    background:#15171d;border-bottom:1px solid #23262f}}
  .bar a{{color:#ffd23f;text-decoration:none;font-weight:600}}
  .bar .t{{color:#e8e6e1;font-weight:600}}
  iframe{{border:0;width:100%;height:calc(100% - 49px)}}
</style></head>
<body>
  <div class="bar"><a href="/">&larr; Library</a>
    <span class="t">{title}</span>
    <a href="/pdf/{chapter}?dl=1" style="margin-left:auto">Download</a></div>
  <iframe src="/pdf/{chapter}#zoom=page-width" title="{title}"></iframe>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("WEBAPP_PORT", "8080")))
