#!/usr/bin/env python3
"""Calibre-Web uploader service.

A consumer like the bot: it reconciles against the shared storage and uploads
each chapter PDF to Calibre-Web. On startup it backfills everything Calibre-Web
is missing, then watches for new chapters.

Env:
  CALIBRE_URL              base url, e.g. http://valhalla:8083  (required)
  CALIBRE_USERNAME/PASSWORD  Calibre-Web login
  CALIBRE_POLL_INTERVAL    seconds between watch passes (default 300)
  CALIBRE_UPLOAD_FIELD, CALIBRE_AUTHOR/SERIES/TAGS  see client.py
  RUN_ONCE                 single pass then exit
"""

import os
import sys
import time

from onepiece.storage import Storage, Reconciler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client import CalibreWebClient

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def backfill(storage, reconciler, client):
    """Mark chapters Calibre-Web already has as done, so we only upload the rest."""
    existing = client.existing_chapter_numbers()
    if existing is None:
        return  # OPDS unreadable; rely on persisted reconcile state
    for chapter in storage.list_chapters():
        if chapter in existing and not reconciler.is_done(chapter):
            reconciler.mark(chapter)
    print(f"[calibre] backfill: {len(existing & set(storage.list_chapters()))} "
          f"chapter(s) already in library")


def upload_pending(storage, reconciler, client):
    pending = reconciler.pending()
    if not pending:
        return 0
    uploaded = 0
    for chapter in pending:
        meta = storage.read_meta(chapter) or {}
        title = meta.get("title") or f"One Piece Chapter {chapter}"
        pdf = storage.pdf_path(chapter)  # full quality for the library
        if not os.path.exists(pdf):
            print(f"[calibre] chapter {chapter} has no PDF on disk; skipping")
            continue
        try:
            book_id = client.upload(pdf, title)
        except Exception as e:
            print(f"[calibre] upload error for chapter {chapter}: {e}")
            continue
        if book_id is None and not _treat_unknown_id_as_success():
            print(f"[calibre] no book id for chapter {chapter}; will retry")
            continue
        client.set_metadata(book_id, title, chapter)
        reconciler.mark(chapter)
        uploaded += 1
    if uploaded:
        print(f"[calibre] uploaded {uploaded} chapter(s)")
    return uploaded


def _treat_unknown_id_as_success():
    # Some Calibre-Web versions don't return a parseable book id even on success.
    # Setting CALIBRE_ASSUME_UPLOAD_OK avoids endless retries in that case.
    return bool(os.environ.get("CALIBRE_ASSUME_UPLOAD_OK"))


def main():
    storage = Storage()
    reconciler = Reconciler(storage, "calibre")
    client = CalibreWebClient()
    interval = float(os.environ.get("CALIBRE_POLL_INTERVAL", "300"))
    run_once = bool(os.environ.get("RUN_ONCE"))

    print(f"[calibre] starting; storage={storage.root} target={client.base_url}")

    # Wait for Calibre-Web to be reachable / login to succeed.
    while not client.login():
        if run_once:
            print("[calibre] login failed and RUN_ONCE set; exiting")
            return
        print("[calibre] retrying login in 30s...")
        time.sleep(30)

    backfill(storage, reconciler, client)

    while True:
        upload_pending(storage, reconciler, client)
        if run_once:
            print("[calibre] RUN_ONCE set; exiting")
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
