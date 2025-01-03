#!/usr/bin/env python3
import discord
from discord import app_commands
from googleapiclient.discovery import build
from classes.manga_downloader import MangaDownloader
import json, re

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

    # print(response)

    # Check if any video title contains the chapter number
    for item in response['items']:
        if f"Chapter {chapter_number}" in item['snippet']['title']:
            # return f"Found: {item['snippet']['title']} - {item['snippet']['publishedAt']}"
            video_id = item['id']['videoId']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            return video_url, True
    
    # no video found for chapter
    return f"No video found yet for chapter {chapter_number}", False

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


async def handle_chapter_request(interaction: discord.Interaction, chapter: int = None):
    try:
        if chapter is None:
            # Handle checking the latest chapter (if required, implement the logic here)
            # Insert logic to check the latest chapter here
            chapter = bot.downloader.get_last_chapter()+1

        # Handle downloading a specific chapter
        # defer the response as thinking
        await interaction.response.defer(ephemeral=True, thinking=True)

        url = bot.downloader.get_url_from_table_of_contents(chapter)
        print(f'Chapter {chapter} URL: {url}')

        path = bot.downloader.download_chapter(chapter, False)
        manga_title = bot.downloader.download_and_get_title(url)
        images = bot.downloader.find_cdn_images(url)

        manga_title = f'{chapter}: {manga_title}'

        print(images)

        # Convert CDN images to file objects
        images = [f"manga_chapters/{chapter}_{i+1}{'.jpeg' if image.endswith('jpeg') else '.png'}" for i, image in enumerate(images)]

        # check if file exists, may accidentally be jpeg or png - or vice versa
        for i, image in enumerate(images):
            if not bot.downloader.file_exists(image):
                images[i] = image.replace('.jpeg', '.png') if image.endswith('.jpeg') else image.replace('.png', '.jpeg')

        print(images)

        success = path is not None

        if success:
            await interaction.edit_original_response(content=f'Chapter {chapter} uploading...')

            # Upload file, send as followup, use filename and file object as a PDF
            file_name = path.split("/")[-1]
            with open(path, "rb") as f:
                await interaction.followup.send(f'# {manga_title}\nChapter {chapter} available at {url}', 
                                                file=discord.File(f, file_name),
                                                suppress_embeds=True)

                # Respond with all images in as few interactions as possible
                for i in range(0, len(images), 10):
                    title = f'# {manga_title}\n{i+1}-{min(i+10, len(images))}'

                    title += f'/{len(images)}'

                    # print uploading..
                    print(f'Uploading {title}...')
                    await interaction.followup.send(title, files=[discord.File(img) for img in images[i:i+10]])

            # Delete images if downloaded
            bot.downloader.delete_images()

            print(f'Chapter {chapter} uploaded successfully')
            print('Done')

    except Exception as e:

        print(f'Error during download: {e}')

        # respond via DM that the chaper is not found, give the chapter number
        # await interaction.user.send(f'Chapter {chapter} may not yet be released, check back next Sunday')

        # delete_original_response
        # await interaction.delete_original_response()

        # edit original message
        await interaction.edit_original_response(content=f'Chapter {chapter} may not yet be released, check back next Sunday')

@tree.command(name="napier", description="Check if Merphy Napier has a video for a specific One Piece chapter")
@app_commands.describe(chapter="The chapter number to check (optional)")
async def check_napier_video(interaction: discord.Interaction, chapter: int = None):
    await interaction.response.defer(ephemeral=False, thinking=True)  # Defer the response to avoid timeouts

    # Load the YouTube API key from youtube.txt
    with open("youtube.txt", "r") as f:
        api_key = f.read().strip()

    if chapter is None:
        # Use the latest chapter number if not provided
        chapter = bot.downloader.get_last_chapter()

    # Check for the video
    result, exists = check_one_piece_chapter_video(api_key, chapter)
    

    if exists:
        await interaction.followup.send(result)
    else:
        # delete original
        await interaction.delete_original_response()

        # respond emphemerally
        await interaction.followup.send(result, ephemeral=True)      

@tree.command(name="check", description="Check the latest chapter of One Piece")
async def check_latest_chapter(interaction: discord.Interaction):
    await handle_chapter_request(interaction)

@tree.command(name="chapter", description="Download a specific chapter of One Piece")
@app_commands.describe(chapter="The chapter number to download")
async def download_chapter(interaction: discord.Interaction, chapter: int):
    await handle_chapter_request(interaction, chapter)

@tree.command(name="get", description="Download a manga chapter using a URL parameter")
@app_commands.describe(url="The URL of the manga chapter to download")
async def download_chapter_by_url(interaction: discord.Interaction, url: str):
    await interaction.response.defer()  # Defer the response to avoid timeouts
    
    try:
        # Inform user about the download attempt
        await interaction.followup.send(f"Attempting to download manga chapter from: {url}")

        # find chapter in last subset of url
        # example 1130 out of https://w13.read-onepiece-manga.com/manga/one-piece-chapter-1130-the-accursed-price/
        # Example URL
        url = "https://w13.read-onepiece-manga.com/manga/one-piece-chapter-1130-the-accursed-price/"

        # Regular expression to extract the chapter number
        match = re.search(r"chapter-(\d+)-", url)

        chapter = None

        if match:
            chapter = match.group(1)
            print(f"Chapter number: {chapter}")
        else:
            print("Chapter number not found.")
            # tell user of failure
            await interaction.followup.send("Chapter number not found in the URL.")

        # Use MangaDownloader to download chapter and get title
        manga_title = bot.downloader.download_and_get_title(url)
        cdn_images = bot.downloader.find_cdn_images(url)
        images = bot.downloader.download_images(chapter, cdn_images)

        # Check if any images were found
        if not images:
            await interaction.followup.send("No images found for the provided URL. It might be invalid or the chapter is not available.")
            return

        # Generate a PDF and get the path
        chapter = manga_title.split(':')[0]  # Using the title as chapter identifier if needed
        path = f"manga_chapters/{manga_title}.pdf"
        bot.downloader.images_to_pdf(images, path)

        # Upload the PDF file
        file_name = path.split("/")[-1]
        with open(path, "rb") as f:
            await interaction.followup.send(f"Downloaded chapter: {manga_title}\nURL: {url}", file=discord.File(f, file_name))

        # Respond with all images in as few interactions as possible
        for i in range(0, len(images), 10):
            title = f'# {manga_title}\n{i+1}-{min(i+10, len(images))}'

            title += f'/{len(images)}'

            # print uploading..
            print(f'Uploading {title}...')
            await interaction.followup.send(title, files=[discord.File(img) for img in images[i:i+10]])

        # Clean up images after creation
        bot.downloader.delete_images()

        print(f"Chapter from {url} uploaded successfully")
        print('Done')

    except Exception as e:
        print(f"Error during download: {e}")
        await interaction.followup.send(f"Failed to download manga chapter from the provided URL. Please check the URL and try again.")

# Run the bot with your token
with open("bot_token.txt", "r") as f:
    token = f.read().strip()

bot.run(token)
