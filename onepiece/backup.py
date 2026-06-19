"""Optional backup sync for chapter PDFs.

After the downloader fetches new chapters it can mirror the PDFs to a backup
directory (e.g. a NAS share). The destination comes from the ``BACKUP_PATH``
environment variable; if it's unset or empty, syncing is skipped entirely.

Kept stdlib-only (it shells out to rsync) so it doesn't drag extra deps into
storage-only consumers.
"""

import os
import shutil
import subprocess


def backup_path():
    """The configured backup directory, or None if syncing is disabled."""
    path = (os.environ.get("BACKUP_PATH") or "").strip()
    return path or None


def sync_to_backup(storage, dest=None):
    """Mirror the chapter PDFs to the backup directory with rsync.

    Returns True if a sync ran (and succeeded), False if skipped or failed.
    Never raises — a backup problem must not take the downloader down.

    Uses ``rsync -a`` without ``--delete``: new and changed PDFs are copied,
    nothing in the backup is ever removed. The trailing slash on the source
    copies the directory's *contents* into dest, not a nested ``pdfs`` folder.
    """
    dest = dest or backup_path()
    if not dest:
        print("[backup] BACKUP_PATH not set; skipping backup sync")
        return False

    if not shutil.which("rsync"):
        print("[backup] rsync not found on PATH; skipping backup sync")
        return False

    src = storage.pdf_dir.rstrip("/") + "/"
    try:
        os.makedirs(dest, exist_ok=True)
    except OSError as e:
        print(f"[backup] cannot create backup dir {dest!r}: {e}")
        return False

    print(f"[backup] syncing {src} -> {dest}")
    try:
        result = subprocess.run(
            ["rsync", "-a", src, dest],
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("BACKUP_TIMEOUT", "1800")),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[backup] rsync failed to run: {e}")
        return False

    if result.returncode != 0:
        print(f"[backup] rsync exited {result.returncode}: "
              f"{result.stderr.strip()}")
        return False

    print("[backup] backup sync complete")
    return True
