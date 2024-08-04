#!/usr/bin/env python3
import os
import sys
import requests
from PIL import Image
from fpdf import FPDF
from bs4 import BeautifulSoup
import re

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

    last_chapter = get_last_chapter()

    if(chapter > last_chapter):
        print(f"Saving last chapter as {chapter}...")
        with open(LAST_CHAPTER_FILE, "w") as f:
            f.write(str(chapter))
    else:
        print(f"Keeping chapter already saved as {last_chapter}...")

def find_cdn_images(url):
    try:
        # Download the page content
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for HTTP errors

        # Parse the page with BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')

        # Find all the links that match the pattern
        cdn_image_links = []
        pattern = re.compile(r'https://cdn.*\.(png|jpeg)')

        for img in soup.find_all('img', src=True):
            img_src = img['src'].replace('\r', '')
            if pattern.match(img_src):
                cdn_image_links.append(img_src)

        return cdn_image_links
    
    except requests.RequestException as e:
        print(f"Error downloading the page: {e}")
        return []

def download_images(chapter):

    url = f'https://ww10.readonepiece.com/chapter/one-piece-chapter-{chapter}/'
    images = find_cdn_images(url)

    imagesOnDisk = []

    for(i, image_url) in enumerate(images):
        # skip title or translator cover images
        # not reliable enough atm
        # if(image_url.endswith('01.png') or image_url.endswith('01.jpeg')):
        #     print(f"Skipping image {i+1}... {image_url}")
        #     continue;

        print(f"Downloading image {i+1}... {image_url}")
        response = requests.get(image_url)
        if response.status_code == 404:
            break
        image_path = os.path.join(OUTPUT_DIR, f"{chapter}_{i+1}{IMAGE_EXTENSION}")
        with open(image_path, "wb") as f:
            f.write(response.content)
        imagesOnDisk.append(image_path)

    return imagesOnDisk

def images_to_pdf(image_paths, output_pdf):
    images = []
    for image_path in image_paths:
        images.append(Image.open(image_path))

    # remove this if you want to keep the images in color
    # converted_images = images
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

    print(f"Downloading chapter {chapter}...")

    images = download_images(chapter)
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
