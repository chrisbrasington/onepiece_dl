"""Shared storage layout for the One Piece pipeline.

Everything the services share lives under one root directory (a Docker volume in
production, ./storage locally). The downloader is the only writer; the bot,
calibre uploader, and webapp are readers that reconcile against what's present.

Layout under the root:
    pdfs/      one piece - <chapter>.pdf      (final chapter PDFs)
    previews/  <chapter>.png                  (first-page cover thumbnails)
    meta/      <chapter>.json                 (chapter metadata sidecars)
    requests/  <chapter>.request              (webapp -> downloader queue)
    work/      <chapter>_<n>.<ext>            (transient page images)
    last_chapter.txt                          (highest chapter fetched)
    .processed_<name>.json                    (per-consumer reconcile state)

Kept dependency-free (stdlib only) so storage-only consumers don't pull in
Pillow/requests.
"""

import json
import os
import re
from datetime import date, datetime, timezone

DEFAULT_ROOT = "storage"

# Chapter PDFs are named "one piece - <chapter>.pdf".
_PDF_RE = re.compile(r"one piece - (\d+)\.pdf$", re.IGNORECASE)
_REQUEST_RE = re.compile(r"(\d+)\.request$")


class Storage:
    def __init__(self, root=None):
        # Resolve the env at construction (not import) so it's honored regardless
        # of import order.
        self.root = root or os.environ.get("ONEPIECE_STORAGE") or DEFAULT_ROOT
        self.pdf_dir = os.path.join(self.root, "pdfs")
        self.discord_dir = os.path.join(self.root, "discord_pdfs")
        self.preview_dir = os.path.join(self.root, "previews")
        self.meta_dir = os.path.join(self.root, "meta")
        self.requests_dir = os.path.join(self.root, "requests")
        self.work_dir = os.path.join(self.root, "work")
        self.last_chapter_file = os.path.join(self.root, "last_chapter.txt")
        for d in (self.pdf_dir, self.discord_dir, self.preview_dir, self.meta_dir,
                  self.requests_dir, self.work_dir):
            os.makedirs(d, exist_ok=True)

    # ----- paths -----------------------------------------------------------
    def pdf_path(self, chapter):
        return os.path.join(self.pdf_dir, f"one piece - {chapter}.pdf")

    def discord_pdf_path(self, chapter):
        """Optional size-reduced copy for Discord's upload limit. Only created by
        the downloader when the full PDF is too large; otherwise consumers fall
        back to pdf_path()."""
        return self.discord_copy_for(self.pdf_path(chapter))

    def discord_copy_for(self, full_pdf_path):
        """Where the Discord-compressed copy of a given full PDF lives — same
        filename, in the discord_pdfs dir. Used for both chapter and manual PDFs."""
        return os.path.join(self.discord_dir, os.path.basename(full_pdf_path))

    def preview_path(self, chapter):
        return os.path.join(self.preview_dir, f"{chapter}.png")

    def meta_path(self, chapter):
        return os.path.join(self.meta_dir, f"{chapter}.json")

    # ----- chapter inventory ----------------------------------------------
    def has_chapter(self, chapter):
        return os.path.exists(self.pdf_path(chapter))

    def list_chapters(self):
        """Chapters with a PDF present, ascending."""
        found = []
        for name in os.listdir(self.pdf_dir):
            m = _PDF_RE.match(name)
            if m:
                found.append(int(m.group(1)))
        return sorted(found)

    # ----- metadata sidecars ----------------------------------------------
    def read_meta(self, chapter):
        path = self.meta_path(chapter)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        return None

    def write_meta(self, chapter, **fields):
        data = {"chapter": int(chapter)}
        data.update(fields)
        data.setdefault("downloaded_at", datetime.now(timezone.utc).isoformat())
        with open(self.meta_path(chapter), "w") as f:
            json.dump(data, f, indent=2)
        return data

    # ----- last-chapter state ---------------------------------------------
    def get_last_chapter(self):
        if os.path.exists(self.last_chapter_file):
            try:
                return int(open(self.last_chapter_file).read().strip())
            except (ValueError, OSError):
                return None
        return None

    def save_last_chapter(self, chapter):
        if chapter is None:
            return
        last = self.get_last_chapter()
        if last is None or int(chapter) > int(last):
            with open(self.last_chapter_file, "w") as f:
                f.write(str(int(chapter)))

    # ----- expected next release (manual schedule override) ---------------
    @property
    def _expected_file(self):
        return os.path.join(self.root, "expected_next.txt")

    def get_expected_release(self):
        """Manually-set expected next release date (a datetime.date), or None.
        Overrides the heuristic so the downloader polls around a known date."""
        if os.path.exists(self._expected_file):
            try:
                return date.fromisoformat(open(self._expected_file).read().strip())
            except (ValueError, OSError):
                return None
        return None

    def set_expected_release(self, d):
        with open(self._expected_file, "w") as f:
            f.write(d.isoformat())

    def clear_expected_release(self):
        if os.path.exists(self._expected_file):
            os.remove(self._expected_file)

    # ----- request queue (webapp -> downloader) ---------------------------
    def request_chapter(self, chapter):
        path = os.path.join(self.requests_dir, f"{int(chapter)}.request")
        open(path, "a").close()
        return path

    def pending_requests(self):
        reqs = []
        for name in os.listdir(self.requests_dir):
            m = _REQUEST_RE.match(name)
            if m:
                reqs.append(int(m.group(1)))
        return sorted(reqs)

    def clear_request(self, chapter):
        path = os.path.join(self.requests_dir, f"{int(chapter)}.request")
        if os.path.exists(path):
            os.remove(path)


class Reconciler:
    """Tracks which chapters a consumer has already handled, persisted so it
    survives restarts. Used identically by the bot (posted) and calibre
    uploader (uploaded): on startup, ``pending()`` returns the backlog; after
    handling a chapter, call ``mark()``.
    """

    def __init__(self, storage, name):
        self.storage = storage
        self.name = name
        self.state_path = os.path.join(storage.root, f".processed_{name}.json")
        self.processed = self._load()

    def _load(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path) as f:
                    return set(json.load(f))
            except (ValueError, OSError):
                return set()
        return set()

    def _save(self):
        with open(self.state_path, "w") as f:
            json.dump(sorted(self.processed), f)

    def reload(self):
        """Re-read the processed set from disk. Lets a long-running consumer (the
        bot) pick up marks written by another process (the opctl helper) between
        polls, instead of only at startup."""
        self.processed = self._load()
        return self.processed

    def pending(self):
        """Chapters present in storage that this consumer hasn't handled yet."""
        return [c for c in self.storage.list_chapters() if c not in self.processed]

    def is_done(self, chapter):
        return int(chapter) in self.processed

    def mark(self, chapter):
        self.processed.add(int(chapter))
        self._save()

    def mark_all_present(self):
        """Treat everything currently in storage as already handled (used to
        avoid re-posting/re-uploading the existing backlog on first run)."""
        for c in self.storage.list_chapters():
            self.processed.add(c)
        self._save()
