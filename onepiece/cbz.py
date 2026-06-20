"""Build CBZ (comic-archive) files for chapters.

A CBZ is just a ZIP of page images named so they sort in reading order. Two
inputs are supported:

  images_to_cbz  — zip page images straight from disk (used by the downloader,
                   which still has the freshly-downloaded pages). stdlib only.
  pdf_to_cbz     — rebuild a CBZ from an existing chapter PDF (used by the webapp
                   button, where the source pages are long gone). Needs PyMuPDF,
                   imported lazily so storage-only consumers don't pull it in.

Both write to a temp file and atomically rename, so a reader never sees a
half-written archive and a crashed build leaves no partial .cbz behind.
"""

import os
import zipfile


def _entry_name(index, ext):
    """Zero-padded page name so archives sort in reading order (001, 002, …)."""
    if not ext.startswith("."):
        ext = "." + ext
    return f"{index:03d}{ext.lower()}"


def images_to_cbz(image_paths, output_cbz):
    """Zip the given page images (already in reading order) into a CBZ.
    Returns the output path. Raises ValueError if there are no images."""
    if not image_paths:
        raise ValueError("no images to write into CBZ")

    tmp = output_cbz + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
        for i, path in enumerate(image_paths, start=1):
            ext = os.path.splitext(path)[1] or ".jpg"
            zf.write(path, _entry_name(i, ext))
    os.replace(tmp, output_cbz)
    print(f"CBZ saved: {output_cbz}")
    return output_cbz


def pdf_to_cbz(pdf_path, output_cbz):
    """Rebuild a CBZ from an existing chapter PDF by pulling each page's image
    out of the PDF. These PDFs are one full-page image per page, so the embedded
    stream is extracted directly (no re-encode); a page with no extractable image
    is rendered to PNG as a fallback. Returns the output path."""
    import fitz  # PyMuPDF — lazy so non-webapp consumers don't need it

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)

    tmp = output_cbz + ".tmp"
    doc = fitz.open(pdf_path)
    try:
        if doc.page_count == 0:
            raise ValueError(f"{pdf_path} has no pages")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
            for i in range(doc.page_count):
                page = doc.load_page(i)
                data, ext = _page_image(doc, page)
                zf.writestr(_entry_name(i + 1, ext), data)
    finally:
        doc.close()
    os.replace(tmp, output_cbz)
    print(f"CBZ saved: {output_cbz}")
    return output_cbz


def _page_image(doc, page):
    """Return (bytes, ext) for a page: the largest embedded image if present,
    otherwise a rendered PNG of the whole page."""
    images = page.get_images(full=True)
    if images:
        # xref is the first tuple element; pick the largest image on the page.
        best = max(images, key=lambda im: im[2] * im[3])  # width * height
        extracted = doc.extract_image(best[0])
        if extracted and extracted.get("image"):
            return extracted["image"], extracted.get("ext", "png")
    # Fallback: rasterize the page (covers vector pages / odd encodings).
    pix = page.get_pixmap(dpi=150)
    return pix.tobytes("png"), "png"
