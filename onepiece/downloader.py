import os
import requests
from PIL import Image
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

from .storage import Storage

# Image hosts we accept pages from, and junk patterns we reject. Shared by all
# download paths.
ALLOWED_DOMAINS = [
    r"blogger\.googleusercontent\.com",
    r"cdn\.onepiecechapters\.com",
    r"([a-z0-9]+)\.wp\.com",  # any subdomain of wp.com
    r"cdn",
    r"wp-content",
    r"nangca\.com",
]

BLOCKED_PATTERNS = [
    r"\.avif$",
    r"wanted-poster\.png",
    r"One-Piece-Manga\.webp",
    r"fiver",
    r"ck-cdn\.com",
    r"\.webp$",
    r"imageshack\.com",
]


class MangaDownloader:
    BASE_URL = "https://www.read-onepiece-manga.com/manga/one-piece-chapter-{}/"
    TABLE_OF_CONTENTS_URL = 'https://w17.read-onepiece-manga.com/'
    IMAGE_EXTENSION = ".jpeg"

    # Matches downloaded page images ("1161_10.png", "onepiece_1.jpeg") and the
    # bot's "_compressed.jpg" temp files. Does NOT match the chapter PDFs or the
    # cover previews (no "_<digit>" before the ext).
    PAGE_IMAGE_RE = re.compile(r"_\d+(?:_compressed)?\.(?:jpe?g|png)$", re.IGNORECASE)

    def __init__(self, storage=None):
        self.storage = storage or Storage()
        # Back-compat aliases so existing callers that reference these keep working.
        self.OUTPUT_DIR = self.storage.work_dir
        self.LAST_CHAPTER_FILE = self.storage.last_chapter_file

    def delete_images(self):
        for file in os.listdir(self.storage.work_dir):
            if self.PAGE_IMAGE_RE.search(file):
                os.remove(os.path.join(self.storage.work_dir, file))

    def download_and_get_title(self, url, chapter=None):
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        title = self.get_title(soup, chapter)
        print(title)
        return title

    # -------------------------------
    # Helper: Domain filtering
    # -------------------------------
    def is_allowed(self, url, allowed_domains=ALLOWED_DOMAINS, blocked_patterns=BLOCKED_PATTERNS):
        host = urlparse(url).netloc.lower()

        # Explicitly block unwanted patterns
        if any(re.search(pattern, url) for pattern in blocked_patterns):
            return False

        # Allow only if host matches known patterns
        return any(re.search(pattern, host) for pattern in allowed_domains)

    def _download_pages(self, images, name_prefix):
        """Download a list of image URLs into the work dir as
        ``<name_prefix>_<n>.<ext>``. Returns the list of saved paths."""
        images_on_disk = []
        for i, image_url in enumerate(images):
            print(f"Downloading image {i+1}... {image_url}", end=' ')

            if not self.is_allowed(image_url):
                print("[Blocked]")
                continue

            try:
                response = requests.get(image_url)
                response.raise_for_status()
            except Exception as e:
                print(f"Failed to download image: {e}")
                continue

            ext = os.path.splitext(image_url)[1].split('?')[0]
            if ext.lower() not in ['.jpg', '.jpeg', '.png']:
                ext = self.IMAGE_EXTENSION  # fallback extension

            image_path = os.path.join(self.storage.work_dir, f"{name_prefix}_{i+1}{ext}")
            with open(image_path, "wb") as f:
                f.write(response.content)

            images_on_disk.append(image_path)
            print('ok')
        return images_on_disk

    def download_chapter(self, chapter, delete_images=True):
        url = self.get_url(chapter)
        print(f"Downloading chapter {chapter} from {url}...")
        if not url:
            print("No chapter URL found.")
            return None, []

        title = self.download_and_get_title(url, chapter)
        images = self.find_images(url)
        images_on_disk = self._download_pages(images, str(chapter))

        if not images_on_disk:
            print("No images downloaded.")
            return None, []

        output_pdf = self.storage.pdf_path(chapter)
        preview_path = self.storage.preview_path(chapter)
        self.images_to_pdf(images_on_disk, output_pdf, preview_image=preview_path)

        # Build a Discord-sized copy now, while the source pages still exist, so
        # the bot can post chapters whose full PDF exceeds Discord's upload limit.
        # The full PDF is never altered — calibre and the webapp always use it.
        discord_copy = self.ensure_discord_copy(output_pdf, images_on_disk)

        self.storage.write_meta(
            chapter,
            title=title,
            source_url=url,
            pages=len(images_on_disk),
            pdf=os.path.basename(output_pdf),
            discord_pdf=(os.path.basename(discord_copy) if discord_copy else None),
        )

        print(f"Chapter {chapter} downloaded as PDF: {output_pdf}")

        if delete_images:
            self.delete_images()

        return output_pdf, images_on_disk

    def ensure_discord_copy(self, full_pdf, image_paths, limit=None):
        """If full_pdf exceeds Discord's upload limit, build a compressed sibling
        in the discord_pdfs dir (same filename, rebuilt from the source pages) and
        return its path. Otherwise return None — the full PDF fits and should be
        posted as-is. The full PDF is left untouched. Call while page images exist."""
        if limit is None:
            limit = int(float(os.environ.get("DISCORD_PDF_LIMIT", 10 * 1024 * 1024)))
        if os.path.getsize(full_pdf) <= limit:
            return None
        dpath = self.storage.discord_copy_for(full_pdf)
        target = int(limit * 0.95)  # leave headroom under the hard limit
        print(f"[discord] full PDF over {limit} bytes; building compressed copy")
        self.compress_pdf_to_size(image_paths, dpath, target)
        return dpath

    def download_from_url(self, url, output_name="manual", delete_images=True):
        print(f"Downloading from direct URL: {url}")
        images = self.find_images(url)

        if not images:
            print("No images found.")
            return None, []

        images_on_disk = self._download_pages(images, output_name)

        if not images_on_disk:
            return None, []

        output_pdf = os.path.join(self.storage.pdf_dir, f"{output_name}.pdf")
        self.images_to_pdf(images_on_disk, output_pdf)
        self.ensure_discord_copy(output_pdf, images_on_disk)
        print(f"Download complete: {output_pdf}")

        if delete_images:
            self.delete_images()

        return output_pdf, images_on_disk

    def file_exists(self, file):
        return os.path.exists(file)

    def find_images(self, url):
        try:
            response = requests.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            image_links = []

            # Extract images from <img> tags
            for img in soup.find_all('img', src=True):
                img_src = img['src'].strip()
                if img_src.startswith("http") and img_src not in image_links:
                    image_links.append(img_src)

            # Extract images from <meta property="og:image">
            for meta in soup.find_all("meta", attrs={"property": "og:image"}):
                img_src = meta.get("content", "").strip()
                if img_src.startswith("http") and img_src not in image_links:
                    image_links.append(img_src)

            if len(image_links) <= 5:
                print("Not enough images found, rejecting")
                for i in image_links:
                    print("  " + i)
                image_links = []

            return image_links
        except requests.RequestException as e:
            print(f"Error downloading the page: {e}")
            return []

    def get_last_chapter(self):
        return self.storage.get_last_chapter()

    def get_title(self, soup, chapter=None):
        metas = soup.find_all("meta", attrs={"property": "og:description"})

        best_match = None

        for meta in metas:
            content = meta.get("content", "")
            if not content:
                continue

            # normalize
            content = content.replace('\xa0', ' ')
            content = content.strip()
            content = re.sub(r'\s+', ' ', content)

            # MUST start with chapter (this is the key fix)
            if not content.lower().startswith("one piece chapter"):
                continue

            # match full title
            match = re.search(
                r"(One Piece Chapter\s+\d+)(?:\s*[-–]\s*(.*))?",
                content,
                re.IGNORECASE
            )

            if match:
                base = match.group(1)
                subtitle = match.group(2)

                # Prefer one WITH subtitle
                if subtitle:
                    return f"{base} – {subtitle.strip()}"

                # fallback if no better one found
                best_match = base

        if best_match:
            return best_match

        if chapter:
            return f"One Piece Chapter {chapter}"

        return "One Piece Chapter"

    def get_url(self, chapter):
        return self.get_url_from_table_of_contents(chapter)

    def get_url_from_table_of_contents(self, chapter):
        response = requests.get(self.TABLE_OF_CONTENTS_URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        links = soup.find_all('a', href=True)
        chapter_str = f"one-piece-chapter-{chapter}"
        for link in links:
            href = link['href']
            if chapter_str in href:
                return href
        return None

    def images_to_pdf(self, image_paths, output_pdf, preview_image=None):
        """
        Convert images to a PDF. Optionally save the first page as a preview image.
        """
        # Open images in RGB so the preview looks correct
        images = [Image.open(p).convert("RGB") for p in image_paths]

        # Save PDF
        images[0].save(output_pdf, "PDF", resolution=100.0, save_all=True, append_images=images[1:])
        print(f"PDF saved: {output_pdf}")

        # Save first page as preview
        if preview_image and images:
            images[0].save(preview_image, "PNG")
            print(f"Preview image saved: {preview_image}")

    def compress_pdf_to_size(self, image_paths, output_pdf, max_bytes):
        """
        Rebuild a PDF from source images, shrinking until it fits under max_bytes.
        Decodes each source image once, resizes in parallel, and writes the PDF
        directly from in-memory images (no on-disk JPEG round-trip).
        Returns True if the result fits, False otherwise.
        """
        if not image_paths:
            return False

        import time
        from concurrent.futures import ThreadPoolExecutor

        def mb(n):
            return f"{n / (1024 * 1024):.2f}MB"

        # (max_width_px, jpeg_quality) — least aggressive first.
        passes = [
            (1600, 75),
            (1400, 65),
            (1200, 60),
            (1100, 50),
            (1000, 45),
            (900,  40),
            (800,  35),
        ]

        target_mb = mb(max_bytes)
        original_mb = mb(os.path.getsize(output_pdf)) if os.path.exists(output_pdf) else "?"
        print(f"[compress] start: pages={len(image_paths)} "
              f"original={original_mb} target<={target_mb}")

        t0 = time.monotonic()
        originals = [Image.open(p).convert("RGB") for p in image_paths]
        print(f"[compress] decoded {len(originals)} pages "
              f"in {time.monotonic() - t0:.1f}s")

        cached_pages = None
        cached_width = None

        for i, (max_width, quality) in enumerate(passes, start=1):
            print(f"[compress] pass {i}/{len(passes)} "
                  f"max_width={max_width} quality={quality}")

            if max_width != cached_width:
                def resize_one(img, mw=max_width):
                    if img.width <= mw:
                        return img
                    ratio = mw / img.width
                    new_size = (mw, max(1, int(img.height * ratio)))
                    return img.resize(new_size, Image.LANCZOS)

                t = time.monotonic()
                with ThreadPoolExecutor() as ex:
                    cached_pages = list(ex.map(resize_one, originals))
                cached_width = max_width
                print(f"[compress]   resized to {max_width}px wide "
                      f"in {time.monotonic() - t:.1f}s")
            else:
                print(f"[compress]   reusing {max_width}px resized pages")

            t = time.monotonic()
            cached_pages[0].save(
                output_pdf, "PDF",
                resolution=100.0,
                save_all=True,
                append_images=cached_pages[1:],
                quality=quality,
            )
            write_s = time.monotonic() - t
            size = os.path.getsize(output_pdf)
            print(f"[compress]   wrote PDF in {write_s:.1f}s → {mb(size)}")

            if size <= max_bytes:
                print(f"[compress] fits target ({mb(size)} <= {target_mb}) "
                      f"after pass {i}, total {time.monotonic() - t0:.1f}s")
                return True

        print(f"[compress] exhausted all {len(passes)} passes; "
              f"final size {mb(os.path.getsize(output_pdf))} still over "
              f"{target_mb} (total {time.monotonic() - t0:.1f}s)")
        return False

    def save_last_chapter(self, chapter):
        if chapter is None:
            print("Chapter is None, not saving.")
            return
        before = self.storage.get_last_chapter()
        self.storage.save_last_chapter(chapter)
        after = self.storage.get_last_chapter()
        if after != before:
            print(f"Saving last chapter as {after}...")
        else:
            print(f"Keeping chapter already saved as {before}...")
