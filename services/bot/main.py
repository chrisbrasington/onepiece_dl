#!/usr/bin/env python3
import discord
from discord import app_commands
from discord.ext import tasks
from googleapiclient.discovery import build
import asyncio, json, os, re
from PIL import Image

from onepiece.storage import Storage, Reconciler
from onepiece.downloader import MangaDownloader

# Load .env if present (no-op if python-dotenv isn't installed or no .env exists)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DISCORD_UPLOAD_LIMIT = 10 * 1024 * 1024  # Discord free-tier per-file limit


# ---------------------------------------------------------------------------
# Secrets / config: prefer environment variables, fall back to legacy files so
# existing deployments keep working until they migrate to .env.
# ---------------------------------------------------------------------------
def _legacy_file(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read().strip()
    return None


def get_bot_token():
    token = os.environ.get("DISCORD_BOT_TOKEN") or _legacy_file("bot_token.txt")
    if not token:
        raise RuntimeError("No bot token: set DISCORD_BOT_TOKEN or provide bot_token.txt")
    return token


def get_youtube_api_key():
    key = os.environ.get("YOUTUBE_API_KEY") or _legacy_file("youtube.txt")
    if not key:
        raise RuntimeError("No YouTube key: set YOUTUBE_API_KEY or provide youtube.txt")
    return key


def get_guild_id():
    guild_id = os.environ.get("DISCORD_GUILD_ID")
    if guild_id:
        return int(guild_id)
    raw = _legacy_file("config.json")
    if raw:
        return json.loads(raw)["guild_id"]
    return None


def get_channel_id():
    """Channel the bot auto-posts new chapters to (the anime-manga channel)."""
    cid = os.environ.get("DISCORD_CHANNEL_ID")
    return int(cid) if cid else None


# Function to check if Merphy Napier has a video for the chapter
def check_one_piece_chapter_video(api_key, chapter_number):
    # YouTube channel ID for Merphy Napier
    channel_id = 'UC7FW6FYqPLeQIXMSulBfOLw'

    # Build the YouTube API client
    youtube = build('youtube', 'v3', developerKey=api_key)

    # Search for videos in the channel containing the chapter number
    request = youtube.search().list(
        part='snippet',
        channelId=channel_id,
        q=f"One Piece Chapter {chapter_number}",
        type='video',
        maxResults=5
    )

    response = request.execute()

    # Check if any video title contains the chapter number
    for item in response['items']:
        if f"Chapter {chapter_number}" in item['snippet']['title']:
            video_id = item['id']['videoId']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            return video_url, True

    # no video found for chapter
    return f"No video found yet for chapter {chapter_number}", False


async def convert_and_compress_image(image_path, max_size=2 * 1024 * 1024):
    """Convert image to JPEG and compress under 2MB."""
    img = Image.open(image_path).convert("RGB")  # Ensure compatibility
    temp_path = image_path.rsplit(".", 1)[0] + "_compressed.jpg"  # Avoid overwriting

    quality = 100  # Start with high quality
    img.save(temp_path, format="JPEG", quality=quality)

    # If file is small enough, return early
    if os.path.getsize(temp_path) <= max_size:
        return temp_path

    # If still too large, force compression
    while os.path.getsize(temp_path) > max_size and quality > 10:
        quality -= 5
        img.save(temp_path, format="JPEG", quality=quality)

    return temp_path


def trim_title(title):
    return re.sub(r' - One Piece Manga Online$', '', title or '')


def title_for(chapter, meta):
    return trim_title((meta or {}).get("title") or f"One Piece Chapter {chapter}")


# Configure Discord bot
class MangaBotClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.synced = False
        self.storage = Storage()
        self.downloader = MangaDownloader(self.storage)
        self.reconciler = None
        self.channel_id = get_channel_id()

    async def on_ready(self):
        print(f'Logged in as {self.user.name}')

        await self.wait_until_ready()
        if not self.synced:
            guild_id = get_guild_id()
            guild = self.get_guild(guild_id) if guild_id else None

            if guild:
                print(f'Syncing commands to {guild.name}...')
            else:
                print('No guild id configured; doing global sync only.')

            await tree.sync()  # global sync

            commands = await tree.fetch_commands()
            for command in commands:
                print(f'Command: {command.name}')
            if not commands:
                print('No commands found.')

            self.synced = True

        # Set up auto-post reconcile + watcher.
        self._setup_autopost()
        print('Ready')

    def _setup_autopost(self):
        if self.reconciler is not None:
            return  # already set up (on_ready can fire more than once)
        state_path = os.path.join(self.storage.root, ".processed_bot.json")
        first_run = not os.path.exists(state_path)
        self.reconciler = Reconciler(self.storage, "bot")

        if self.channel_id is None:
            print("[autopost] DISCORD_CHANNEL_ID not set; auto-posting disabled")
            return

        # On a fresh state file, skip the existing backlog so we don't dump every
        # chapter into the channel. Set BOT_POST_BACKLOG=1 to post them anyway.
        if first_run and not os.environ.get("BOT_POST_BACKLOG"):
            self.reconciler.mark_all_present()
            print(f"[autopost] first run: marked {len(self.reconciler.processed)} "
                  f"existing chapter(s) as already posted")

        if not autopost_loop.is_running():
            autopost_loop.start()
            print(f"[autopost] watching {self.storage.root} for new chapters")

    async def close(self):
        await super().close()
        print('Bot is shutting down')


bot = MangaBotClient()
tree = app_commands.CommandTree(bot)


async def post_chapter(channel, chapter):
    """Post a single chapter (cover image + PDF) to a channel."""
    meta = bot.storage.read_meta(chapter) or {}
    title = title_for(chapter, meta)
    url = meta.get("source_url")

    files = []

    # Cover preview (compressed if needed)
    preview = bot.storage.preview_path(chapter)
    if os.path.exists(preview):
        img = preview
        try:
            if os.path.getsize(img) > 2 * 1024 * 1024:
                img = await convert_and_compress_image(preview)
            files.append(discord.File(img))
        except Exception as e:
            print(f"[autopost] preview load failed for {chapter}: {e}")

    # PDF — prefer the Discord-sized copy the downloader made, else the full one.
    pdf = bot.storage.best_pdf(chapter)
    posted_pdf = False
    if os.path.exists(pdf) and os.path.getsize(pdf) <= DISCORD_UPLOAD_LIMIT:
        files.append(discord.File(pdf, filename=os.path.basename(bot.storage.pdf_path(chapter))))
        posted_pdf = True

    header = f'# [{title}]({url})' if url else f'# {title}'
    if not posted_pdf:
        header += "\n_(PDF too large for Discord — grab it from the web app.)_"

    await channel.send(header, files=files, suppress_embeds=True)
    print(f"[autopost] posted chapter {chapter} (pdf={'yes' if posted_pdf else 'no'})")


@tasks.loop(seconds=float(os.environ.get("BOT_POLL_INTERVAL", "60")))
async def autopost_loop():
    if bot.reconciler is None or bot.channel_id is None:
        return
    pending = bot.reconciler.pending()
    if not pending:
        return
    channel = bot.get_channel(bot.channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(bot.channel_id)
        except Exception as e:
            print(f"[autopost] cannot resolve channel {bot.channel_id}: {e}")
            return
    for chapter in pending:
        try:
            await post_chapter(channel, chapter)
            bot.reconciler.mark(chapter)
        except Exception as e:
            # Leave unmarked so the next pass retries.
            print(f"[autopost] failed to post chapter {chapter}: {e}")


@autopost_loop.before_loop
async def _before_autopost():
    await bot.wait_until_ready()


async def handle_download(interaction: discord.Interaction, url: str, chapter: int = None):
    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        manga_title = bot.downloader.download_and_get_title(url, chapter)
        trim = trim_title(manga_title)

        if chapter:
            path, images = bot.downloader.download_chapter(chapter, delete_images=False)
        else:
            output_name = trim.replace(" ", "_").lower()
            path, images = bot.downloader.download_from_url(
                url,
                output_name=output_name,
                delete_images=False
            )

        if path is None or not images:
            await interaction.edit_original_response(
                content=f'Chapter {chapter} may not yet be released, check back next Sunday'
            )
            return

        await interaction.edit_original_response(content='Uploading chapter...')

        # ------------------------
        # Prepare files
        # ------------------------
        files = []

        # PDF — compress if it exceeds Discord's free upload limit (10MB).
        safe_target = int(DISCORD_UPLOAD_LIMIT * 0.95)  # leave headroom

        pdf_size = os.path.getsize(path)
        if pdf_size > DISCORD_UPLOAD_LIMIT:
            print(f"PDF is {pdf_size / (1024 * 1024):.2f}MB — compressing under "
                  f"{safe_target / (1024 * 1024):.2f}MB...")
            await interaction.edit_original_response(content='Compressing PDF for upload...')
            fit = await asyncio.to_thread(
                bot.downloader.compress_pdf_to_size, images, path, safe_target
            )
            new_size = os.path.getsize(path)
            print(f"Compressed PDF: {new_size / (1024 * 1024):.2f}MB "
                  f"({'fits' if fit else 'still too large'})")

        # PDF
        try:
            if os.path.getsize(path) <= DISCORD_UPLOAD_LIMIT:
                files.append(discord.File(path, filename=os.path.basename(path)))
            else:
                print(f"Skipping PDF attachment — still over "
                      f"{DISCORD_UPLOAD_LIMIT / (1024 * 1024):.0f}MB after compression.")
        except Exception as e:
            print(f"PDF load failed: {e}")

        # First image only
        try:
            first_image = images[0]
            if os.path.getsize(first_image) > 2 * 1024 * 1024:
                first_image = await convert_and_compress_image(first_image)
            files.insert(0, discord.File(first_image))  # put image first (optional)
        except Exception as e:
            print(f"Image load failed: {e}")

        # ------------------------
        # Upload once
        # ------------------------
        if files:
            await interaction.followup.send(
                f'# [{trim}]({url})',
                files=files,
                suppress_embeds=True
            )
        else:
            await interaction.followup.send(
                f'# {trim}\n(no files uploaded)\n{url}',
                suppress_embeds=True
            )

        # ------------------------
        # Cleanup + state
        # ------------------------
        bot.downloader.delete_images()
        bot.downloader.save_last_chapter(chapter)
        # Mark so the auto-poster doesn't re-post a chapter we just shared.
        if chapter and bot.reconciler is not None:
            bot.reconciler.mark(chapter)

        print(f"Chapter {'from URL' if not chapter else chapter} uploaded successfully")

    except Exception as e:
        print(f"Error during download: {e}")
        await interaction.edit_original_response(
            content=f"❌ Failed to download{' chapter ' + str(chapter) if chapter else ' from URL'}"
        )


@tree.command(name="napier", description="Check if Merphy Napier has a video for a specific One Piece chapter")
@app_commands.describe(chapter="The chapter number to check (optional)")
async def check_napier_video(interaction: discord.Interaction, chapter: int = None):
    await interaction.response.defer(ephemeral=False, thinking=True)

    api_key = get_youtube_api_key()

    if chapter is None:
        chapter = bot.downloader.get_last_chapter()

    result, exists = check_one_piece_chapter_video(api_key, chapter)

    if exists:
        await interaction.followup.send(result)
    else:
        await interaction.delete_original_response()
        await interaction.followup.send(result, ephemeral=True)


@tree.command(name="check", description="Check the latest chapter of One Piece")
async def check_latest_chapter(interaction: discord.Interaction):
    chapter = bot.downloader.get_last_chapter() + 1
    url = bot.downloader.get_url(chapter)
    print(f'Latest chapter URL (probably {chapter}): {url}')
    await handle_download(interaction, url, chapter)


@tree.command(name="chapter", description="Download a specific chapter of One Piece")
@app_commands.describe(chapter="The chapter number to download")
async def download_chapter(interaction: discord.Interaction, chapter: int):
    url = bot.downloader.get_url(chapter)
    print(f'Chapter {chapter} URL: {url}')
    await handle_download(interaction, url, chapter)


@tree.command(name="url", description="Download a chapter using a direct URL")
@app_commands.describe(url="The full URL of the chapter")
async def download_from_url(interaction: discord.Interaction, url: str):
    print(f"Direct URL given: {url}")
    await handle_download(interaction, url)


if __name__ == "__main__":
    bot.run(get_bot_token())
