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
from urllib.parse import urljoin, urlparse

import warnings

import requests
from bs4 import BeautifulSoup

try:  # we intentionally parse OPDS (XML) with html.parser to avoid an lxml dep
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    pass

CHAPTER_RE = re.compile(r"chapter\s+(\d+)", re.IGNORECASE)


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

    # -- inventory ----------------------------------------------------------
    def existing_chapter_numbers(self):
        """Set of chapter numbers already in the library (via OPDS), or None if
        we couldn't read it (caller then relies on local reconcile state)."""
        auth = (self.username, self.password) if self.username else None
        # Try a few common OPDS list endpoints; stop at the first that parses.
        for path in ("/opds/new", "/opds/books", "/opds/letter/all", "/opds"):
            try:
                resp = self.session.get(self._url(path), auth=auth, timeout=30)
            except requests.RequestException as e:
                print(f"[calibre] OPDS {path} error: {e}")
                continue
            if not resp.ok or "<feed" not in resp.text and "<entry" not in resp.text:
                continue
            found = set()
            # html.parser handles the OPDS XML well enough to pull <title> tags,
            # and avoids a hard dependency on lxml.
            soup = BeautifulSoup(resp.text, "html.parser")
            titles = [t.get_text() for t in soup.find_all("title")]
            for title in titles:
                m = CHAPTER_RE.search(title or "")
                if m:
                    found.add(int(m.group(1)))
            if found:
                print(f"[calibre] OPDS {path}: found {len(found)} existing chapters")
                return found
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

    def upload(self, pdf_path, title):
        """Upload a PDF under a clean title. Returns the new book id, or None."""
        if not self._logged_in and not self.login():
            return None

        upload_url = self._url("/upload")
        csrf = self._fetch_csrf("/")

        tmpdir = tempfile.mkdtemp()
        try:
            named = os.path.join(tmpdir, safe_filename(title) + ".pdf")
            shutil.copyfile(pdf_path, named)
            with open(named, "rb") as fh:
                files = {self.upload_field: (os.path.basename(named), fh, "application/pdf")}
                data = {"csrf_token": csrf} if csrf else {}
                resp = self.session.post(
                    upload_url, files=files, data=data, timeout=300,
                    headers=self._csrf_headers(csrf),
                )
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
