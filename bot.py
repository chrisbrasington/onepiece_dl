#!/usr/bin/env python3
import discord
from discord import app_commands
from googleapiclient.discovery import build
from classes.manga_downloader import MangaDownloader
import json, os, re
from PIL import Image

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

async def upload_images(interaction, images, trim_title):
    max_file_size = 2 * 1024 * 1024  # 2MB per file
    max_attachments = 5  # Max 5 files per batch
    batch = []
    index = 1

    for i, img in enumerate(images):
        if i == 0:
            print(f"Skipping first image: {img}, already sent")
            continue  # Skip first image
        file_size = os.path.getsize(img)

        # Convert and compress image if necessary
        print(f"Processing {img} ({file_size / (1024 * 1024):.2f}MB)...")
        if file_size > max_file_size:
            img = await convert_and_compress_image(img)

        file_size = os.path.getsize(img)  # Re-check after compression
        if file_size > max_file_size:
            print(f"Skipping {img}, still too large after compression.")
            continue

        batch.append(img)

        # Upload when batch reaches max attachments
        if len(batch) == max_attachments:
            await send_batch(interaction, batch, trim_title, index, len(images))
            index += len(batch)
            batch = []  # Reset batch

    # Upload any remaining images
    if batch:
        await send_batch(interaction, batch, trim_title, index, len(images))

async def send_batch(interaction, batch, trim_title, index, total_images):
    """Uploads a batch of images to Discord."""
    if not batch:  # <-- Fix: Prevent empty batch error
        return  
    
    title = f'# {trim_title}\n{index+1}-{index+len(batch)}/{total_images}'
    batch_sizes = [os.path.getsize(f) / (1024 * 1024) for f in batch]
    
    print(f'Uploading {title}...')
    print(f'Batch file sizes: {[f"{size:.2f}MB" for size in batch_sizes]}')

    await interaction.followup.send(title, files=[discord.File(f) for f in batch])

# Configure Discord bot
class MangaBotClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default() # all?
        super().__init__(intents=intents)
        self.synced = False
        self.downloader = MangaDownloader()

    async def on_ready(self):
        print(f'Logged in as {self.user.name}')

        await self.wait_until_ready()
        if not self.synced:

            # get config from config.json
            with open("config.json", "r") as f:
                config = json.load(f)

            guild = self.get_guild(config['guild_id'])

            print(f'Syncing commands to {guild.name}...')

            # await tree.sync(guild=guild)
            await tree.sync()  # For global sync

            commands = await tree.fetch_commands()

            for command in commands:
                print(f'Command: {command.name}')

            # if no commands
            if not commands:
                print('No commands found.')

            print('Ready')

    async def close(self):
        await super().close()
        print('Bot is shutting down')

bot = MangaBotClient()
tree = app_commands.CommandTree(bot)

async def handle_download(interaction: discord.Interaction, url: str, chapter: int = None):
    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        manga_title = bot.downloader.download_and_get_title(url)
        trim_title = re.sub(r' - One Piece Manga Online$', '', manga_title)

        if chapter:
            path, images = bot.downloader.download_chapter(chapter, delete_images=False)
        else:
            output_name = trim_title.replace(" ", "_").lower()
            path, images = bot.downloader.download_from_url(url, output_name=output_name, delete_images=False)

        if path is None or not images:            
            await interaction.edit_original_response(content=f'Chapter {chapter} may not yet be released, check back next Sunday')
            #await interaction.user.send(f'Chapter {chapter} may not yet be released, check back next Sunday')
            return

        await interaction.edit_original_response(content=f'Uploading chapter...')

        file_name = os.path.basename(path)
        try:
            with open(path, "rb") as f:
                await interaction.followup.send(f'# {trim_title}\n{url}',
                                                file=discord.File(f, file_name),
                                                suppress_embeds=True)
        except Exception as e:
            print(f"PDF upload failed: {e}")
            await interaction.followup.send(f'# {trim_title}\n(no pdf)\n{url}', suppress_embeds=True)

        if images:
            await interaction.followup.send(f'# {trim_title}\n1/{len(images)}',
                                            file=discord.File(images[0]))
            await upload_images(interaction, images, trim_title)

        bot.downloader.delete_images()
        print(f"Chapter {'from URL' if not chapter else chapter} uploaded successfully")

        # if greater than last chapter, save
        bot.downloader.save_last_chapter(chapter)

    except Exception as e:
        print(f"Error during download: {e}")
        await interaction.edit_original_response(content=f"❌ Failed to download{' chapter ' + str(chapter) if chapter else ' from URL'}")

@tree.command(name="napier", description="Check if Merphy Napier has a video for a specific One Piece chapter")
@app_commands.describe(chapter="The chapter number to check (optional)")
async def check_napier_video(interaction: discord.Interaction, chapter: int = None):
    await interaction.response.defer(ephemeral=False, thinking=True)  # Defer the response to avoid timeouts

    # Load the YouTube API key from youtube.txt
    with open("youtube.txt", "r") as f:
        api_key = f.read().strip()

    if chapter is None:
        chapter = bot.downloader.get_last_chapter()

    # Check for the video
    result, exists = check_one_piece_chapter_video(api_key, chapter)

    if exists:
        await interaction.followup.send(result)
    else:
        # delete original
        await interaction.delete_original_response()

        # respond ephemerally
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


# Run the bot with your token
with open("bot_token.txt", "r") as f:
    token = f.read().strip()

bot.run(token)
