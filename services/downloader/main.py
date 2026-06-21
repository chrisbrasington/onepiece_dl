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

from onepiece.storage import Storage, Reconciler
from onepiece.downloader import MangaDownloader
from onepiece.backup import sync_to_backup
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
    are left in the queue to retry on a later pass.

    By default a queued (webapp) request does NOT trigger a Discord post — it's
    treated as a backfill. Set WEBAPP_REQUEST_POST=1 to let the bot post them.

    Returns how many chapters were freshly downloaded."""
    post_requested = bool(os.environ.get("WEBAPP_REQUEST_POST"))
    fetched = 0
    for ch in storage.pending_requests():
        if storage.has_chapter(ch):
            storage.clear_request(ch)
            continue
        if not post_requested:
            # Mark the bot done BEFORE the PDF appears so its poll can't catch it
            # first. Calibre is left unmarked, so it still uploads the chapter.
            Reconciler(storage, "bot").mark(ch)
        print(f"[request] downloading requested chapter {ch}")
        try:
            pdf, _ = downloader.download_chapter(ch)
        except Exception as e:
            print(f"[request] error on chapter {ch}: {e}")
            continue
        if pdf:
            downloader.save_last_chapter(ch)
            storage.clear_request(ch)
            fetched += 1
            print(f"[request] chapter {ch} done")
        else:
            print(f"[request] chapter {ch} not available yet; will retry")
    return fetched


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
        # A real release happened — drop any manual schedule override so we revert
        # to the heuristic for the next one.
        storage.clear_expected_release()
    return fetched


def expected_release_dt(storage):
    """The manual schedule override as an aware UTC datetime, or None."""
    return storage.get_expected_release_dt()


def wait_with_reactivity(storage, delay, chunk=60.0):
    """Sleep up to `delay` seconds, but wake early if the schedule override or the
    pending-request set changes, so the downloader reacts promptly to opctl/webapp.
    Compares the full instant so a time-only edit (same date) still wakes us."""
    baseline_sched = storage.get_expected_release_dt()
    baseline_reqs = storage.pending_requests()
    waited = 0.0
    while waited < delay:
        time.sleep(min(chunk, delay - waited))
        waited += chunk
        if storage.get_expected_release_dt() != baseline_sched:
            print("[downloader] schedule changed; re-checking now")
            return
        if storage.pending_requests() != baseline_reqs:
            print("[downloader] request queue changed; re-checking now")
            return


def run_pass(storage, downloader, max_catchup):
    fetched = serve_requests(storage, downloader)
    fetched += check_new(storage, downloader, max_catchup)
    # Mirror new PDFs to the backup dir (NAS, etc.). No-op when BACKUP_PATH is
    # unset; never fatal if the backup target is unavailable.
    if fetched:
        sync_to_backup(storage)
    # Heartbeat: record that we polled, so consumers (e.g. the Homepage widget)
    # can show when the downloader last looked for chapters.
    storage.save_last_check()


def main():
    storage = Storage()
    downloader = MangaDownloader(storage)
    cfg = ScheduleConfig.from_env()
    max_catchup = int(os.environ.get("MAX_CATCHUP", "3"))
    run_once = bool(os.environ.get("RUN_ONCE"))
    react_interval = float(os.environ.get("REACT_INTERVAL", "60"))

    print(f"[downloader] starting; storage={storage.root} run_once={run_once}")
    print(f"[downloader] schedule {cfg}")

    while True:
        run_pass(storage, downloader, max_catchup)

        if run_once:
            print("[downloader] RUN_ONCE set; exiting")
            return

        now = datetime.now(timezone.utc)
        last_rel = latest_release_time(storage)
        expected_dt = expected_release_dt(storage)
        delay = next_check_delay(now, last_rel, cfg, expected_release=expected_dt)
        if expected_dt:
            exp_display = f"{expected_dt.isoformat()} (manual)"
        else:
            exp_display = expected_next_release(last_rel)
        print(f"[downloader] last_release={last_rel} expected_next~{exp_display} "
              f"sleeping {delay}s ({delay / 3600:.1f}h)")
        wait_with_reactivity(storage, delay, react_interval)


if __name__ == "__main__":
    main()
