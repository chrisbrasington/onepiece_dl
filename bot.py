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
        bot.downloader.download_chapter()
        await interaction.followup.send('Latest chapter checked successfully.')
    except Exception as e:
        await interaction.followup.send(f'Failed to check the latest chapter. Error: {str(e)}')

@tree.command(name="chapter", description="Download a specific chapter of One Piece")
@app_commands.describe(chapter="The chapter number to download")
async def download_chapter(interaction: discord.Interaction, chapter: int):
    await interaction.response.send_message(f'Downloading Chapter {chapter} of One Piece...')
    try:
        bot.downloader.download_chapter(chapter)
        await interaction.followup.send(f'Chapter {chapter} downloaded successfully.')
    except Exception as e:
        await interaction.followup.send(f'Failed to download Chapter {chapter}. Error: {str(e)}')

# Run the bot with your token
with open("bot_token.txt", "r") as f:
    token = f.read().strip()

bot.run(token)
