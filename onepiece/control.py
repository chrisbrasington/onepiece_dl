#!/usr/bin/env python3
"""Command-line control for the pipeline.

Runs inside the downloader container (it has the download deps) and is wrapped by
the host ./opctl script:

  ./opctl request 1180             download chapter 1180 now; bot + calibre react
  ./opctl request 1180 --no-post   download it but mark it so the bot skips it
  ./opctl request 1180 --force     re-download even if already on disk

A requested download goes straight into the shared storage, so the webapp shows
it immediately and the calibre uploader (and bot, unless --no-post) pick it up on
their next pass.
"""

import argparse
import sys
from datetime import date, datetime

from .storage import Storage, Reconciler
from .downloader import MangaDownloader


def cmd_request(args):
    storage = Storage()

    # For --no-post, mark BEFORE downloading so the bot can't catch the file in
    # the gap between it appearing and being marked (the bot reloads state each poll).
    if args.no_post:
        Reconciler(storage, "bot").mark(args.chapter)
        print(f"marked chapter {args.chapter} so the bot will skip it")

    if storage.has_chapter(args.chapter) and not args.force:
        print(f"chapter {args.chapter} already present (use --force to re-download)")
        return 0

    downloader = MangaDownloader(storage)
    pdf, _ = downloader.download_chapter(args.chapter)
    if not pdf:
        print(f"chapter {args.chapter} could not be downloaded (not released yet?)")
        return 1

    # Monotonic — only advances the pointer, so backfilling an older chapter
    # leaves "latest" alone while requesting a newer one moves it forward.
    downloader.save_last_chapter(args.chapter)
    reactors = "calibre" if args.no_post else "calibre and the bot"
    print(f"downloaded chapter {args.chapter}; {reactors} will pick it up shortly")
    return 0


def cmd_schedule(args):
    storage = Storage()

    if args.clear:
        storage.clear_expected_release()
        print("cleared manual schedule; reverting to the release heuristic")
        return 0

    if not args.date:
        cur = storage.get_expected_release()
        print(f"expected next release: {cur.isoformat() if cur else '(none set; using heuristic)'}")
        return 0

    try:
        d = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError:
        print(f"invalid date '{args.date}'; use YYYY-MM-DD, e.g. 2026-06-07")
        return 1

    today = date.today()
    if d < today:
        print(f"{d.isoformat()} is in the past; refusing. Give a future date (YYYY-MM-DD).")
        return 1

    storage.set_expected_release(d)
    out = f"expected next release set to {d.isoformat()}"
    days = (d - today).days
    if days > 31:
        out += f"  (warning: {days} days out — that's over a month ahead)"
    print(out)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="opctl",
        description="Control the running One Piece pipeline from the host.",
        epilog=(
            "examples:\n"
            "  opctl request 1180             download chapter 1180 now\n"
            "  opctl request 1180 --no-post   download it, but the bot won't post it\n"
            "  opctl request 1180 --force     re-download even if already on disk\n"
            "  opctl schedule 2026-06-07      expect the next chapter on Jun 7\n"
            "  opctl schedule                 show the current expected date\n"
            "  opctl schedule --clear         revert to the automatic heuristic\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    req = sub.add_parser(
        "request",
        help="download a chapter now (calibre + bot react)",
        description="Download a chapter immediately. It lands in the shared "
                    "storage, so the webapp shows it right away and calibre (and "
                    "the bot, unless --no-post) pick it up on their next pass.",
    )
    req.add_argument("chapter", type=int, help="chapter number, e.g. 1180")
    req.add_argument("--no-post", action="store_true",
                     help="download but mark it so the bot doesn't post it (calibre still uploads)")
    req.add_argument("--force", action="store_true",
                     help="re-download even if already on disk")
    req.set_defaults(func=cmd_request)

    sch = sub.add_parser(
        "schedule",
        help="set/show/clear the expected next release date",
        description="Set the date the next chapter is expected, as YYYY-MM-DD "
                    "(e.g. 2026-06-07). The downloader idles until about a day "
                    "before, then polls hourly until it lands, and reacts to the "
                    "change within ~a minute. Past dates are rejected; a date more "
                    "than a month out warns. It clears automatically once a new "
                    "chapter is fetched. With no date it shows the current value; "
                    "--clear reverts to the automatic heuristic.",
    )
    sch.add_argument("date", nargs="?",
                     help="expected release date in YYYY-MM-DD form, e.g. 2026-06-07")
    sch.add_argument("--clear", action="store_true",
                     help="clear the manual date and use the heuristic")
    sch.set_defaults(func=cmd_schedule)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
