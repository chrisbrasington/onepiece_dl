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
# Heavy/per-container deps (MangaDownloader needs Pillow; CalibreWebClient runs in
# the calibre container) are imported lazily inside the commands that use them, so
# this module loads in any container.


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

    from .downloader import MangaDownloader
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


def cmd_reprocess(args):
    storage = Storage()
    targets = [n for n, on in (("bot", args.bot), ("calibre", args.calibre)) if on]
    if not targets:
        targets = ["bot", "calibre"]

    if not storage.has_chapter(args.chapter):
        print(f"chapter {args.chapter} isn't on disk; nothing to re-process "
              f"(use 'request {args.chapter}' to fetch it first)")
        return 1

    unmarked = []
    for name in targets:
        r = Reconciler(storage, name)
        if r.is_done(args.chapter):
            r.unmark(args.chapter)
            unmarked.append(name)
            print(f"un-marked chapter {args.chapter} for {name}; "
                  f"it will re-process on the next pass")
        else:
            print(f"chapter {args.chapter} isn't marked for {name} yet — it's "
                  f"already pending, so {name} will handle it on its next pass")

    if "calibre" in unmarked:
        print("note: Calibre-Web does not de-dupe — delete the old book there "
              "first, or you'll get a duplicate.")
    if "bot" in unmarked:
        print("note: the bot will post a NEW message — delete the old one with "
              "/delete if you want.")
    return 0


def cmd_retitle(args):
    """Re-apply title/series/author/tags to books already in Calibre-Web, in place
    (no re-upload, no duplicates). Fixes books uploaded before the metadata fix."""
    from .calibre import CalibreWebClient

    storage = Storage()
    client = CalibreWebClient()
    if not client.login():
        print("calibre login failed; check CALIBRE_URL/USERNAME/PASSWORD")
        return 1

    books = client.list_existing_books()
    if books is None:
        print("could not read the calibre library via OPDS")
        return 1

    fixed = skipped = noid = 0
    for b in books:
        ch, bid, cur = b["chapter"], b["book_id"], b["title"]
        if bid is None:
            noid += 1
            continue
        meta = storage.read_meta(ch) or {}
        desired = meta.get("title") or f"One Piece Chapter {ch}"
        if cur.strip() == desired.strip():
            skipped += 1
            continue
        if client.set_metadata(bid, desired, ch):
            print(f"  retitled book {bid}: '{cur}' -> '{desired}'")
            fixed += 1
    print(f"retitle done: {fixed} updated, {skipped} already correct, "
          f"{noid} without a book id")
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
            "  opctl reprocess 1183           re-post + re-upload a corrected chapter\n"
            "  opctl reprocess 1183 --calibre re-upload to Calibre-Web only\n"
            "  opctl retitle                  fix titles/metadata of books already in Calibre-Web\n"
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
                    "(e.g. 2026-06-07). The downloader idles until the set time "
                    "(keeping a light daily check on the way), then polls hourly "
                    "until it lands, and reacts to the change within ~a minute. "
                    "For a specific hour/timezone, use the webapp. "
                    "Past dates are rejected; a date more "
                    "than a month out warns. It clears automatically once a new "
                    "chapter is fetched. With no date it shows the current value; "
                    "--clear reverts to the automatic heuristic.",
    )
    sch.add_argument("date", nargs="?",
                     help="expected release date in YYYY-MM-DD form, e.g. 2026-06-07")
    sch.add_argument("--clear", action="store_true",
                     help="clear the manual date and use the heuristic")
    sch.set_defaults(func=cmd_schedule)

    rep = sub.add_parser(
        "reprocess",
        help="re-trigger the bot and/or calibre for an already-handled chapter",
        description="Un-mark a chapter so a consumer handles it again on its next "
                    "pass — e.g. after re-downloading a corrected PDF with "
                    "'request <n> --force'. With no flag, does both. WARNINGS: the "
                    "bot posts a NEW message (delete the old one with /delete); "
                    "Calibre-Web does not de-dupe, so delete the old book there "
                    "first or you'll get a duplicate.",
    )
    rep.add_argument("chapter", type=int, help="chapter number, e.g. 1183")
    rep.add_argument("--bot", action="store_true", help="re-post via the bot")
    rep.add_argument("--calibre", action="store_true", help="re-upload to Calibre-Web")
    rep.set_defaults(func=cmd_reprocess)

    ret = sub.add_parser(
        "retitle",
        help="fix title/metadata of books already in Calibre-Web (in place)",
        description="Walk the Calibre-Web library (via OPDS) and re-apply the "
                    "title/series/author/tags to each One Piece book in place — no "
                    "re-upload, no duplicates. Fixes books uploaded before the "
                    "metadata field was corrected. Titles come from each chapter's "
                    "stored metadata, falling back to 'One Piece Chapter N'.",
    )
    ret.set_defaults(func=cmd_retitle)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
