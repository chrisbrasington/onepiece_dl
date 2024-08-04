#!/usr/bin/env python3
import sys
from classes.manga_downloader import MangaDownloader

def main():
    downloader = MangaDownloader()

    if len(sys.argv) > 1:
        try:
            chapter = int(sys.argv[1])
            downloader.download_chapter(chapter)
        except ValueError:
            print("Please provide a valid chapter number.")
    else:
        downloader.download_chapter()  # Download the next chapter based on the last saved chapter

if __name__ == "__main__":
    main()