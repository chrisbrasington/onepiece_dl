#!/usr/bin/env python3
import os
import sys
import requests
from PIL import Image
from fpdf import FPDF

# Constants
BASE_URL = "https://cdn.readonepiece.com/file/mangap/2"
IMAGE_EXTENSION = ".jpeg"
LAST_CHAPTER_FILE = "last_chapter.txt"
OUTPUT_DIR = "manga_chapters"

# Ensure the output directory exists
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def get_last_chapter():
    if os.path.exists(LAST_CHAPTER_FILE):
        with open(LAST_CHAPTER_FILE, "r") as f:
            return int(f.read().strip())
    return None

def save_last_chapter(chapter):
    with open(LAST_CHAPTER_FILE, "w") as f:
        f.write(str(chapter))

def download_images(chapter):
    page = 1
    images = []
    while True:
        image_url = f"{BASE_URL}/{chapter}/{page}{IMAGE_EXTENSION}"
        print(image_url)
        response = requests.get(image_url)
        if response.status_code == 404:
            break
        image_path = os.path.join(OUTPUT_DIR, f"{chapter}_{page}{IMAGE_EXTENSION}")
        with open(image_path, "wb") as f:
            f.write(response.content)
        images.append(image_path)
        page += 1
    return images

def images_to_pdf(image_paths, output_pdf):
    images = []
    for image_path in image_paths:
        images.append(Image.open(image_path))

    converted_images = []
    # Iterate through the list of images and convert each one to grayscale
    for image in images:
        converted_images.append(image.convert("L"))

    # Save the images as a PDF
    converted_images[0].save(output_pdf, "PDF", resolution=100.0, save_all=True, append_images=converted_images[1:])

def delete_images(image_paths):
    for image_path in image_paths:
        os.remove(image_path)

def main():
    if len(sys.argv) > 1:
        chapter = int(sys.argv[1])
    else:
        last_chapter = get_last_chapter()
        chapter = last_chapter + 1 if last_chapter else 1

    chapter_id = f"1{chapter}000"
    print(f"Downloading chapter {chapter}...")

    images = download_images(chapter_id)
    if images:
        output_pdf = os.path.join(OUTPUT_DIR, f"one piece - {chapter}.pdf")
        images_to_pdf(images, output_pdf)
        print(f"Chapter {chapter} downloaded and saved as {output_pdf}")
        delete_images(images)
        save_last_chapter(chapter)
    else:
        print(f"No images found for chapter {chapter}. It might not be released yet.")

if __name__ == "__main__":
    main()
