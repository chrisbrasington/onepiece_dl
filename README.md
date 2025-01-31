
# Project Overview

This project consists of three main components:
1. **Manga Downloader Script**: Downloads manga chapters from a specified URL, converts the images into a PDF, and deletes the images afterward.
2. **Sync Script**: Synchronizes the downloaded PDF files to a KOBO eReader device.
3. **Discord Bot**: A Discord bot that allows users to interact with the Manga Downloader script via Discord commands.

## Manga Downloader Script

### Host

https://www.read-onepiece-manga.com/

### Description

The Manga Downloader script performs the following tasks:
1. Downloads JPEG images from a specified URL until a 404 error is encountered.
2. Converts the images into a single PDF file.
3. Deletes the images after the PDF is created.
4. Stores the last downloaded chapter number for future runs.

### Usage

Ensure you have the required Python packages installed:

```bash
pip install -r requirements.txt
```

Run the script with an optional chapter number argument:

```bash
python program.py [chapter_number]
```

## Sync Script

### Description

The Sync Script synchronizes the downloaded PDF files to a KOBO eReader device.

### Usage

Run the script:

```bash
bash sync.sh
```

## Discord Bot

### Description

The Discord bot allows users to interact with the Manga Downloader script via Discord commands.

### Usage

Ensure you have the required Python packages installed:

```bash
pip install -r requirements.txt
```

Run the bot:

```bash
python bot.py
```

### Bot Commands

The following commands are available for the Discord bot:

- `/check`: Check the latest chapter of One Piece.
- `/chapter [chapter]`: Download a specific chapter of One Piece.
- `/napier [chapter]`: Check if Merphy Napier has a video for a specific One Piece chapter. If no chapter number is provided, it checks the latest chapter.
    - https://www.youtube.com/@merphynapier42/videos