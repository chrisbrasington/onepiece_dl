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

@tree.command(name="check", description="Check the latest chapter of One Piece")
async def check_latest_chapter(interaction: discord.Interaction):
    await interaction.response.send_message('Checking the latest chapter of One Piece...')
    try:
        path = bot.downloader.download_chapter()

        url = bot.downloader.get_url(None)
        chapter_number = bot.downloader.get_last_chapter() 

        await interaction.followup.send(f'Latest chapter is available at {url}')

        print(path)

        # upload file, send as followup, use filename and file object is a pdf
        # get filename from path
        file_name = path.split("/")[-1]
        with open(path, "rb") as f:
            await interaction.followup.send(file=discord.File(f, file_name))

    except Exception as e:
        await interaction.followup.send(f'Failed to check the latest chapter. Error: {str(e)}')

@tree.command(name="chapter", description="Download a specific chapter of One Piece")
@app_commands.describe(chapter="The chapter number to download")
async def download_chapter(interaction: discord.Interaction, chapter: int):
    await interaction.response.send_message(f'Downloading Chapter {chapter} of One Piece...')
    try:
        path = bot.downloader.download_chapter(chapter, False)
        url = bot.downloader.get_url(chapter)
        images = bot.downloader.find_cdn_images(url)

        print(images)

        # convert CDN images to file objects
        #  images will exist in manga_chapters like "1121_01.jpeg"
        #  images are named by chapter number and image number, so file name has to be modified to this format
        #  use file extension to determine if image is a jpeg or png
        # remove any query string ? from end of url
        images = [f"manga_chapters/{chapter}_{i+1}{'.jpeg' if image.endswith('jpeg') else '.png'}" for i, image in enumerate(images)]

        print(images)

        success = path is not None

        if success:
            # upload file, send as followup, use filename and file object is a pdf
            # get filename from path
            file_name = path.split("/")[-1]
            with open(path, "rb") as f:
                await interaction.followup.send(f'Chapter {chapter} available at {url}', file=discord.File(f, file_name))

                # respond with all image in as few interactions as possible
                #   limit 10 images per interaction
                #   send all images in one interaction if less than 10
                #   send all images in multiple interactions if more than 10
                for i in range(0, len(images), 10):
                    title = f'Chapter {chapter} Images {i+1}-{min(i+10, len(images))}'
                    await interaction.followup.send(title, files=[discord.File(img) for img in images[i:i+10]])

        # delete images if downloaded
        bot.downloader.delete_images()

    except Exception as e:
        await interaction.followup.send(f'Failed to download Chapter {chapter}. Error: {str(e)}')

# Run the bot with your token
with open("bot_token.txt", "r") as f:
    token = f.read().strip()

bot.run(token)
