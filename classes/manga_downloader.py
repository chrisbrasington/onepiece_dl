"""Back-compat shim. The implementation moved to the shared ``onepiece`` package.

Existing imports keep working:
    from classes.manga_downloader import MangaDownloader

New code should import from the package directly:
    from onepiece.downloader import MangaDownloader
"""

from onepiece.downloader import MangaDownloader

__all__ = ["MangaDownloader"]
