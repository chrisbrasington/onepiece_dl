# One Piece downloader pipeline

Downloads One Piece manga chapters into PDFs and fans them out: a Discord bot
posts new chapters automatically, a web app lets you browse/read/download them,
and an uploader pushes them into Calibre-Web. One `docker compose up` runs the lot.

## Architecture

The download/PDF logic lives in the shared `onepiece/` package. Four small
services coordinate through one shared storage volume — the **downloader** is the
only writer (producer); the others are readers (consumers) that reconcile against
what's on disk and react to new chapters.

```
            downloader  ──writes──▶  shared volume (/data)
          (checks for new            pdfs/  discord_pdfs/  previews/
           chapters, builds          meta/  requests/  work/  last_chapter.txt
           pdf+preview+meta)               │
                                  ┌─────────┼──────────┐
                                  ▼         ▼          ▼
                                 bot     calibre     webapp
                            (auto-posts  (uploads   (browse / read /
                             to Discord)  to CW)     download / request)
```

Coordination is filesystem-based: each consumer keeps a persisted record of what
it has handled (`.processed_<name>.json`), backfills on startup, and watches for
new files. No message broker. The webapp queues a missing chapter by dropping a
marker in `requests/`, which the downloader fulfills.

## Services

| Service          | What it does                                                        |
|------------------|---------------------------------------------------------------------|
| `downloader`     | Polls for new chapters (adaptive schedule), fulfills webapp requests, writes pdf/preview/metadata. |
| `bot`            | Discord bot. Auto-posts new chapters to a channel; `/check`, `/chapter`, `/url`, `/napier` commands. |
| `calibre-uploader` | Uploads chapter PDFs to Calibre-Web over HTTP; backfills what's missing on startup. |
| `webapp`         | Cover grid, in-browser reader, PDF download, request-missing-chapter. |

### Release schedule (heuristic)

There is no official API for chapter release dates. Oda's pattern is roughly
three weekly Sunday chapters then a ~1-week break (about monthly), plus occasional
hiatuses. The downloader estimates and adapts: poll slowly until a chapter is due
(~6 days after the last), then hourly until it lands, then back off during long
breaks. It's best-effort, not authoritative — tune the thresholds below.

## Configuration (`.env`)

Copy `.env.example` to `.env` and fill it in. `.env` is gitignored; never commit it.

| Variable | Used by | Notes |
|----------|---------|-------|
| `DISCORD_BOT_TOKEN` | bot | required |
| `DISCORD_GUILD_ID` | bot | command sync |
| `DISCORD_CHANNEL_ID` | bot | channel to auto-post into; unset disables auto-post |
| `YOUTUBE_API_KEY` | bot | for `/napier` |
| `BOT_POLL_INTERVAL` | bot | seconds between auto-post checks (default 60) |
| `BOT_POST_BACKLOG` | bot | set to post the existing backlog on first run |
| `START_CHAPTER` | downloader | first chapter to try when `last_chapter.txt` is empty |
| `MAX_CATCHUP` | downloader | max chapters to grab per pass (default 3) |
| `CHECK_INTERVAL_IDLE` / `CHECK_INTERVAL_WINDOW` / `CHECK_INTERVAL_LONGBREAK` | downloader | poll cadences, seconds (default 86400 / 3600 / 21600) |
| `WINDOW_START_DAYS` / `LONG_BREAK_DAYS` | downloader | schedule thresholds (default 6 / 14) |
| `DISCORD_PDF_LIMIT` | downloader + bot | Discord per-file limit, bytes (default 10MB). Above this the downloader builds a compressed copy in `discord_pdfs/` and the bot posts that; the full PDF is never altered. Shared by both so "fits" and "compressed" agree. |
| `CALIBRE_URL` | calibre | host-published Calibre-Web; from a container use `http://host.docker.internal:8083` (or the host LAN IP), not the host's hostname |
| `CALIBRE_USERNAME` / `CALIBRE_PASSWORD` | calibre | Calibre-Web login |
| `CALIBRE_POLL_INTERVAL` | calibre | seconds between watch passes (default 300) |
| `CALIBRE_UPLOAD_FIELD` | calibre | upload form field name if your CW version differs (default `btn-upload`) |
| `CALIBRE_AUTHOR` / `CALIBRE_SERIES` / `CALIBRE_TAGS` | calibre | metadata defaults |
| `STORAGE_PATH` | compose | host dir bind-mounted to `/data` (default `./data`); where PDFs + `last_chapter.txt` live on the host |
| `ONEPIECE_STORAGE` | all | storage root *inside* the container (set to `/data`; don't change) |
| `WEBAPP_PORT` | webapp | container listen port (default 8080) |

## Deploying on valhalla

1. **Clone and configure.**
   ```bash
   git clone <repo> onepiece_dl && cd onepiece_dl
   cp .env.example .env
   # edit .env: DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, DISCORD_CHANNEL_ID,
   # YOUTUBE_API_KEY, CALIBRE_URL/USERNAME/PASSWORD, and (first run) START_CHAPTER
   ```

2. **Prep Calibre-Web** (on the host, port 8083): in admin settings enable
   uploads and add `pdf` to the allowed upload formats. Otherwise `/upload` rejects PDFs.

3. **Bring it up.**
   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```
   The web app is published on host port **8680** by default (`compose.yaml` →
   `webapp.ports`). Change it there if it clashes.

4. **Seed the starting chapter** (first run only). Either set `START_CHAPTER` in
   `.env` before step 3, or write it into the storage dir on the host:
   ```bash
   echo 1185 > "${STORAGE_PATH:-./data}/last_chapter.txt"
   ```
   (`STORAGE_PATH` is bind-mounted to `/data`, so the host file and the
   container's `/data/last_chapter.txt` are the same file.)

### Notes
- `CALIBRE_URL` must be reachable *from inside the container*. Calibre-Web runs on
  the host, so use `http://host.docker.internal:8083` (compose maps host-gateway
  for the uploader) — not the host's hostname, which won't resolve in a container.
  If it still fails, use the host's LAN IP.
- The Calibre-Web client drives the web UI (no real upload API), so upload field
  names / endpoints can vary by version. If uploads fail, check the logs and
  override `CALIBRE_UPLOAD_FIELD`; metadata-setting is best-effort.
- On first run the bot marks existing chapters as already-posted so it doesn't
  flood the channel. Set `BOT_POST_BACKLOG=1` if you want them posted.

## Local development

`onepiece/storage.py` is stdlib-only and unit-testable. Each service has its own
`requirements.txt`. Run a service directly from the repo root, e.g.:
```bash
ONEPIECE_STORAGE=./storage RUN_ONCE=1 python services/downloader/main.py
```

## Requesting a chapter manually (`opctl`)

Run from the repo dir on valhalla (talks to the running downloader container):

```bash
./opctl request 1180             # download 1180 now; calibre + bot react
./opctl request 1180 --no-post   # download it, but the bot won't post it (calibre still uploads)
./opctl request 1180 --force     # re-download even if already on disk
```

The download lands in the shared volume immediately, so the webapp shows it right
away and calibre (and the bot, unless `--no-post`) pick it up on their next pass.
The webapp's "Request" box does the same thing via the request queue.

## PDF handling

The full-quality PDF (`pdfs/one piece - N.pdf`) is the canonical file — calibre and
the webapp only ever use it, and it's never modified. If it exceeds the Discord
limit, the downloader builds a compressed copy in `discord_pdfs/`; the bot posts
the full one when it fits and the compressed one otherwise, then deletes the
compressed copy after a successful post.

## Other tools
- `download.py [chapter]` — one-off CLI download into the storage layout.
- `sync` — rsync chapter PDFs to a mounted Kobo eReader.
