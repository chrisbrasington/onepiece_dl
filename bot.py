#!/usr/bin/env python3
import discord
from discord import app_commands
from classes.manga_downloader import MangaDownloader
import json

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
        await interaction.response.send_message(f'Checking Chapter {chapter} of One Piece...')
        path = bot.downloader.download_chapter(chapter, False)
        url = bot.downloader.get_url(chapter)
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
            # Upload file, send as followup, use filename and file object as a PDF
            file_name = path.split("/")[-1]
            with open(path, "rb") as f:
                await interaction.followup.send(f'# {manga_title}\nChapter {chapter} available at {url}', file=discord.File(f, file_name))

                # Respond with all images in as few interactions as possible
                for i in range(0, len(images), 10):
                    title = f'# {manga_title}\n{i+1}-{min(i+10, len(images))}'
                    # print uploading..
                    print(f'Uploading {title}...')
                    await interaction.followup.send(title, files=[discord.File(img) for img in images[i:i+10]])

            # Delete images if downloaded
            bot.downloader.delete_images()

    except Exception as e:
        # tell user chapter may not yet be released, check back next Sunday
        await interaction.followup.send('Chapter may not yet be released, check back next Sunday')
        

@tree.command(name="check", description="Check the latest chapter of One Piece")
async def check_latest_chapter(interaction: discord.Interaction):
    await handle_chapter_request(interaction)

@tree.command(name="chapter", description="Download a specific chapter of One Piece")
@app_commands.describe(chapter="The chapter number to download")
async def download_chapter(interaction: discord.Interaction, chapter: int):
    await handle_chapter_request(interaction, chapter)


# Run the bot with your token
with open("bot_token.txt", "r") as f:
    token = f.read().strip()

bot.run(token)
