#!/usr/bin/env python3
import sys
from classes.manga_downloader import MangaDownloader

def main():
    downloader = MangaDownloader()

    if len(sys.argv) > 1:
        try:
            chapter = int(sys.argv[1])
            pdf, images = downloader.download_chapter(chapter)
            if pdf:  # only save if download succeeded
                downloader.save_last_chapter(chapter)
        except ValueError:
            print("Please provide a valid chapter number.")
    else:
        last = downloader.get_last_chapter()
        chapter = (last or 0) + 1
        pdf, images = downloader.download_chapter(chapter)
        if pdf:  # only save if it worked
            downloader.save_last_chapter(chapter)

if __name__ == "__main__":
    main()
