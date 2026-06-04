#!/usr/bin/env python3
"""Downloader service: the producer in the pipeline.

Runs forever. Each pass it (1) fulfills any chapter requests dropped by the
webapp, then (2) checks for the next chapter(s), downloading PDF + preview +
metadata into the shared storage. The poll cadence adapts via the release
heuristic so we check hard only when a chapter is plausibly due.

The bot and calibre uploader watch the same storage and react to new PDFs;
this service never talks to them directly.

Env:
  ONEPIECE_STORAGE        storage root (default: storage)
  START_CHAPTER           baseline if last_chapter.txt is empty (optional)
  MAX_CATCHUP             max consecutive new chapters to grab per pass (default 3)
  RUN_ONCE               if set, do a single pass and exit (for testing/cron)
  CHECK_INTERVAL_*, WINDOW_START_DAYS, LONG_BREAK_DAYS  see release_schedule
"""

import os
import time
from datetime import datetime, timezone

from onepiece.storage import Storage
from onepiece.downloader import MangaDownloader
from onepiece.release_schedule import (
    ScheduleConfig,
    next_check_delay,
    expected_next_release,
)


def latest_release_time(storage):
    """When we fetched the newest chapter we have (timezone-aware), or None."""
    chapters = storage.list_chapters()
    if not chapters:
        return None
    meta = storage.read_meta(max(chapters))
    if meta and meta.get("downloaded_at"):
        try:
            return datetime.fromisoformat(meta["downloaded_at"])
        except ValueError:
            return None
    return None


def serve_requests(storage, downloader):
    """Fulfill webapp-requested chapters. Successful ones are cleared; failures
    are left in the queue to retry on a later pass."""
    for ch in storage.pending_requests():
        if storage.has_chapter(ch):
            storage.clear_request(ch)
            continue
        print(f"[request] downloading requested chapter {ch}")
        try:
            pdf, _ = downloader.download_chapter(ch)
        except Exception as e:
            print(f"[request] error on chapter {ch}: {e}")
            continue
        if pdf:
            downloader.save_last_chapter(ch)
            storage.clear_request(ch)
            print(f"[request] chapter {ch} done")
        else:
            print(f"[request] chapter {ch} not available yet; will retry")


def check_new(storage, downloader, max_catchup):
    """Grab the next chapter(s) above last_chapter, catching up multiple if a gap
    or multiple releases exist. Returns how many were fetched."""
    last = storage.get_last_chapter()
    if last is None:
        start = os.environ.get("START_CHAPTER")
        if not start:
            print("[check] no last_chapter and no START_CHAPTER set; "
                  "skipping new-chapter check")
            return 0
        last = int(start) - 1

    fetched = 0
    for _ in range(max_catchup):
        nxt = last + 1
        print(f"[check] looking for chapter {nxt}")
        try:
            pdf, _ = downloader.download_chapter(nxt)
        except Exception as e:
            print(f"[check] error fetching {nxt}: {e}")
            break
        if not pdf:
            print(f"[check] chapter {nxt} not available yet")
            break
        downloader.save_last_chapter(nxt)
        last = nxt
        fetched += 1
    if fetched:
        print(f"[check] fetched {fetched} new chapter(s)")
    return fetched


def run_pass(storage, downloader, max_catchup):
    serve_requests(storage, downloader)
    check_new(storage, downloader, max_catchup)


def main():
    storage = Storage()
    downloader = MangaDownloader(storage)
    cfg = ScheduleConfig.from_env()
    max_catchup = int(os.environ.get("MAX_CATCHUP", "3"))
    run_once = bool(os.environ.get("RUN_ONCE"))

    print(f"[downloader] starting; storage={storage.root} run_once={run_once}")
    print(f"[downloader] schedule {cfg}")

    while True:
        run_pass(storage, downloader, max_catchup)

        if run_once:
            print("[downloader] RUN_ONCE set; exiting")
            return

        now = datetime.now(timezone.utc)
        last_rel = latest_release_time(storage)
        delay = next_check_delay(now, last_rel, cfg)
        expected = expected_next_release(last_rel)
        print(f"[downloader] last_release={last_rel} expected_next~{expected} "
              f"sleeping {delay}s ({delay / 3600:.1f}h)")
        time.sleep(delay)


if __name__ == "__main__":
    main()
