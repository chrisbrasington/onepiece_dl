# Manga Downloader and Sync Script

## Overview

This project consists of two main components:
1. **Manga Downloader Script**: A Python script that downloads manga chapters from a specified URL, converts the downloaded images into a PDF, and deletes the images afterward.
2. **Sync Script**: A Bash script that synchronizes the downloaded PDF files to a KOBO eReader device.

## Manga Downloader Script

### Description

The Manga Downloader script performs the following tasks:
1. Downloads incrementing JPEG images from a specified URL until a 404 error is encountered.
2. Converts the downloaded images into a single PDF file.
3. Deletes the images after the PDF is created.
4. Stores the last downloaded chapter number on disk for future runs.

### Usage

Ensure you have the required Python packages installed:

```bash
pip install -r requirements.txt
```

Run the script with an optional chapter number argument:

```bash
python manga_downloader.py [chapter_number]
```

If no chapter number is provided, the script will continue from the last downloaded chapter.

## Sync Script

### Description

The Sync script performs the following tasks:
1. Mounts the KOBO eReader device using `sshfs`.
2. Creates a directory for the manga on the KOBO eReader if it does not exist.
3. Synchronizes the downloaded PDF files to the KOBO eReader, ignoring existing files.
4. Unmounts the KOBO eReader device.

### Usage

Run the script:

```bash
./sync_script.sh
```

Ensure the `sync_script.sh` has execution permissions:

```bash
chmod +x sync_script.sh
```

## Requirements

### Python Packages

- `requests`
- `Pillow`
- `fpdf`

### System Requirements

- `sshfs`
- `rsync`

## License

This project is licensed under the MIT License.
