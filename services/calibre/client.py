"""Minimal Calibre-Web HTTP client.

Calibre-Web has no clean upload API, so we drive the web UI:
  1. GET /login, scrape the csrf_token, POST credentials to get a session cookie.
  2. POST the PDF to /upload (multipart) with the csrf_token.
  3. Best-effort: set series/author/tags on the new book via the edit endpoint.
  4. Best-effort: list existing books via the OPDS feed to avoid re-uploading.

Endpoint and form-field details vary by Calibre-Web version, so the brittle bits
are env-overridable and failures degrade gracefully (upload is the must-have;
metadata and OPDS dedup are nice-to-haves). Prereqs on the Calibre-Web side:
"Enable Uploads" must be on and `pdf` added to the allowed upload formats.
"""

import os
import re
import shutil
import tempfile
from urllib.parse import quote, urljoin, urlparse

import warnings

import requests
from bs4 import BeautifulSoup

try:  # we intentionally parse OPDS (XML) with html.parser to avoid an lxml dep
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    pass

# Pull a chapter number out of an OPDS entry. Calibre-Web titles our books
# "one piece - 1176" (from the filename) and carries a "One Piece [1176]" series
# index in the entry content — match either, series index first (most reliable).
SERIES_INDEX_RE = re.compile(r"one piece\s*\[(\d+)\]", re.IGNORECASE)
TITLE_PATTERNS = [
    re.compile(r"chapter\s+(\d+)", re.IGNORECASE),       # "One Piece Chapter 1176"
    re.compile(r"one piece\s*[-–]\s*(\d+)", re.IGNORECASE),  # "one piece - 1176"
]


def chapter_number_from(text):
    """Extract a chapter number from an OPDS entry's text, or None."""
    m = SERIES_INDEX_RE.search(text or "")
    if m:
        return int(m.group(1))
    for pat in TITLE_PATTERNS:
        m = pat.search(text or "")
        if m:
            return int(m.group(1))
    return None


def safe_filename(title):
    """Calibre-Web uses the uploaded filename (sans extension) as the initial
    title, so name the temp file after the chapter title."""
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or "One Piece")[:180]


class CalibreWebClient:
    def __init__(self, base_url=None, username=None, password=None):
        self.base_url = (base_url or os.environ["CALIBRE_URL"]).rstrip("/")
        self.username = username or os.environ.get("CALIBRE_USERNAME", "")
        self.password = password or os.environ.get("CALIBRE_PASSWORD", "")
        # File field name on the upload form; override per Calibre-Web version.
        self.upload_field = os.environ.get("CALIBRE_UPLOAD_FIELD", "btn-upload")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "onepiece-calibre-uploader"
        self._logged_in = False

    # -- helpers ------------------------------------------------------------
    def _url(self, path):
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _csrf(self, html):
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("input", attrs={"name": "csrf_token"})
        if tag and tag.get("value"):
            return tag["value"]
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        return meta.get("content") if meta else None

    # -- auth ---------------------------------------------------------------
    def login(self):
        login_url = self._url("/login")
        resp = self.session.get(login_url, timeout=30)
        resp.raise_for_status()
        csrf = self._csrf(resp.text)

        data = {
            "username": self.username,
            "password": self.password,
            "next": "/",
            "remember_me": "on",
        }
        if csrf:
            data["csrf_token"] = csrf

        resp = self.session.post(
            login_url, data=data, timeout=30,
            headers={"Referer": login_url}, allow_redirects=True,
        )
        # Logged in if we didn't land back on the login page.
        self._logged_in = resp.ok and "/login" not in urlparse(resp.url).path
        if self._logged_in:
            print(f"[calibre] logged in to {self.base_url} as {self.username}")
        else:
            print(f"[calibre] login appears to have failed (final url {resp.url})")
        return self._logged_in

    def _ensure_logged_in(self):
        """Re-login if the session has gone stale (it can run idle for days).
        Probes a login-required page and re-authenticates if bounced to /login."""
        try:
            resp = self.session.get(self._url("/me"), timeout=30, allow_redirects=True)
        except requests.RequestException:
            return self.login()
        # Not authed if we were redirected to the login page (or it's unauthorized).
        if resp.status_code in (401, 403) or "/login" in urlparse(resp.url).path:
            print("[calibre] session expired; re-logging in")
            return self.login()
        return True

    def _looks_like_auth_failure(self, resp):
        return resp.status_code in (401, 403) or "/login" in urlparse(resp.url).path

    # -- inventory ----------------------------------------------------------
    def _next_feed_link(self, soup, current_url):
        """The rel="next" pagination link in an OPDS feed, absolute, or None."""
        for link in soup.find_all("link"):
            rel = link.get("rel")
            rel = " ".join(rel) if isinstance(rel, list) else (rel or "")
            if "next" in rel.lower() and link.get("href"):
                return urljoin(current_url, link["href"])
        return None

    def _collect_chapters_from_feed(self, path, auth, max_pages=60):
        """Walk an OPDS feed (following rel="next" pagination) and collect every
        chapter number found in entry titles. Returns a set on success (possibly
        empty = feed worked but no matching books), or None if the endpoint isn't
        a usable feed."""
        url = self._url(path)
        found = set()
        pages = 0
        seen = set()
        while url and pages < max_pages and url not in seen:
            seen.add(url)
            try:
                resp = self.session.get(url, auth=auth, timeout=30)
            except requests.RequestException as e:
                print(f"[calibre] OPDS {path} page {pages + 1} error: {e}")
                return None
            if not resp.ok or ("<feed" not in resp.text and "<entry" not in resp.text):
                return None  # not an OPDS feed at this endpoint
            soup = BeautifulSoup(resp.text, "html.parser")
            for entry in soup.find_all("entry"):
                num = chapter_number_from(entry.get_text(" "))
                if num is not None:
                    found.add(num)
            url = self._next_feed_link(soup, url)
            pages += 1
        print(f"[calibre] OPDS {path}: {len(found)} chapters across {pages} page(s)")
        return found

    def existing_chapter_numbers(self):
        """Chapter numbers already in the library (via OPDS), or None if OPDS
        couldn't be read (caller then relies on local reconcile state). An empty
        set is a valid answer: the library has no matching chapters."""
        auth = (self.username, self.password) if self.username else None
        series = os.environ.get("CALIBRE_SERIES", "One Piece")
        # Prefer a series-scoped search (fewer pages), then fall back to the full
        # catalog. Each is paginated. First usable feed wins.
        candidates = [
            f"/opds/search/{quote(series)}",
            "/opds/books",
            "/opds/new",
        ]
        for path in candidates:
            result = self._collect_chapters_from_feed(path, auth)
            if result is not None:
                return result
        print("[calibre] could not enumerate existing books via OPDS; "
              "relying on local reconcile state")
        return None

    # -- upload + metadata --------------------------------------------------
    def _fetch_csrf(self, path="/"):
        """Get a CSRF token from a GET-able page. /upload is POST-only, so its
        token must come from a normal page — the upload form is in the layout,
        so the home page carries one."""
        try:
            return self._csrf(self.session.get(self._url(path), timeout=30).text)
        except requests.RequestException:
            return None

    def _csrf_headers(self, csrf):
        headers = {"Referer": self.base_url + "/"}
        if csrf:
            headers["X-CSRFToken"] = csrf
        return headers

    def _extract_book_id(self, resp):
        # Newer Calibre-Web returns JSON {"location": "/book/<id>"}; older
        # versions redirect. Try both.
        try:
            data = resp.json()
            loc = data.get("location") or data.get("url") or ""
            m = re.search(r"/(?:book|admin/book)/(\d+)", loc)
            if m:
                return int(m.group(1))
        except ValueError:
            pass
        m = re.search(r"/(?:book|admin/book)/(\d+)", resp.url)
        if m:
            return int(m.group(1))
        m = re.search(r"/(?:book|admin/book)/(\d+)", resp.text)
        return int(m.group(1)) if m else None

    def _post_upload(self, named_path):
        csrf = self._fetch_csrf("/")  # fresh token each attempt
        with open(named_path, "rb") as fh:
            files = {self.upload_field: (os.path.basename(named_path), fh, "application/pdf")}
            data = {"csrf_token": csrf} if csrf else {}
            return self.session.post(
                self._url("/upload"), files=files, data=data, timeout=300,
                headers=self._csrf_headers(csrf),
            )

    def upload(self, pdf_path, title):
        """Upload a PDF under a clean title. Returns the new book id, or None.
        Re-logs-in if the (possibly days-idle) session has expired."""
        if not self._ensure_logged_in():
            return None

        tmpdir = tempfile.mkdtemp()
        try:
            named = os.path.join(tmpdir, safe_filename(title) + ".pdf")
            shutil.copyfile(pdf_path, named)
            resp = self._post_upload(named)
            # Backstop: if the session lapsed between the probe and the POST, the
            # upload comes back as an auth failure — re-login and retry once.
            if self._looks_like_auth_failure(resp):
                print("[calibre] upload was unauthenticated; re-logging in and retrying")
                if self.login():
                    resp = self._post_upload(named)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        if not resp.ok:
            body = " ".join((resp.text or "")[:300].split())
            print(f"[calibre] upload failed ({resp.status_code}) for {title}: {body}")
            return None
        book_id = self._extract_book_id(resp)
        print(f"[calibre] uploaded '{title}' (book_id={book_id})")
        return book_id

    def set_metadata(self, book_id, title, chapter):
        """Best-effort: set series/index/author/tags on an uploaded book."""
        if not book_id:
            return False
        edit_url = self._url(f"/admin/book/{book_id}")
        try:
            csrf = self._csrf(self.session.get(edit_url, timeout=30).text)
            data = {
                # The edit form's field is "title" (UI label "Book Title").
                # Also send "book_title" in case a fork uses that name — unknown
                # form fields are ignored.
                "title": title,
                "book_title": title,
                "authors": os.environ.get("CALIBRE_AUTHOR", "Eiichiro Oda"),
                "series": os.environ.get("CALIBRE_SERIES", "One Piece"),
                "series_index": str(chapter),
                "tags": os.environ.get("CALIBRE_TAGS", "One Piece, Manga"),
            }
            if csrf:
                data["csrf_token"] = csrf
            resp = self.session.post(
                edit_url, data=data, timeout=60, headers=self._csrf_headers(csrf)
            )
            ok = resp.ok
            print(f"[calibre] metadata for book {book_id}: "
                  f"{'set' if ok else 'failed (' + str(resp.status_code) + ')'}")
            return ok
        except requests.RequestException as e:
            print(f"[calibre] metadata error for book {book_id}: {e}")
            return False
