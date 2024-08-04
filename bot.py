#!/usr/bin/env python3
import discord
from discord import app_commands
from discord.ext import commands
from classes.manga_downloader import MangaDownloader

class MangaBotClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.synced = False
        # self.tree = 
        self.downloader = MangaDownloader()

    async def on_ready(self):
        print(f'Logged in as {self.user.name}')
        guild_id = '1048782527357272177'  # Replace with your guild ID
        guild = discord.Object(id=guild_id) if guild_id else None

        if not self.synced:
            print('Syncing commands...')
            print(tree)
            print(guild)
            if guild:
                await tree.sync(guild=guild)
                await tree.sync(guild=None)
                print(f'Synced commands to guild ID: {guild_id}')
            else:
                await tree.sync()
                print('Synced commands globally')
            self.synced = True

        commands = await tree.fetch_commands(guild=guild)
        for command in commands:
            print(f'Command: {command.name}')

        print('Bot is ready')

    async def close(self):
        await super().close()
        print('Bot is shutting down')

bot = MangaBotClient()
tree = app_commands.CommandTree(bot)


@tree.command(name="check", description="Check the latest chapter of One Piece")
async def check_latest_chapter(interaction: discord.Interaction):
    latest_chapter = bot.downloader.get_latest_chapter()
    if latest_chapter:
        await interaction.response.send_message(f'The latest chapter of One Piece is Chapter {latest_chapter}.')
    else:
        await interaction.response.send_message('Could not retrieve the latest chapter.')

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
