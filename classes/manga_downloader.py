import os
import requests
from PIL import Image
from fpdf import FPDF
from bs4 import BeautifulSoup
import re
from math import gcd
import sys

class MangaDownloader:
    BASE_URL = "https://www.read-onepiece-manga.com/manga/one-piece-chapter-{}/"
    TABLE_OF_CONTENTS_URL = 'https://w17.read-onepiece-manga.com/'
    IMAGE_EXTENSION = ".jpeg"
    LAST_CHAPTER_FILE = "last_chapter.txt"
    OUTPUT_DIR = "manga_chapters"

    def __init__(self):
        if not os.path.exists(self.OUTPUT_DIR):
            os.makedirs(self.OUTPUT_DIR)

    def delete_images(self):
        for file in os.listdir(self.OUTPUT_DIR):
            if file.endswith(self.IMAGE_EXTENSION):
                os.remove(os.path.join(self.OUTPUT_DIR, file))

    def download_and_get_title(self, url):
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        print(self.get_title(soup))
        return self.get_title(soup)

    def download_chapter(self, chapter, delete_images=True):
        url = self.get_url(chapter)
        print(f"Downloading chapter {chapter} from {url}...")
        images = self.find_images(url)

        images_on_disk = []
        allowed_domains = [
            "blogger.googleusercontent.com",
            "cdn.onepiecechapters.com",
            r"([a-z0-9]+)\.wp\.com",  # Regex to match any subdomain of wp.com
            "cdn",  # loosely allow cdn
            "wp-content"  # loosely allow wp-content
        ]

        blocked_patterns = [
            ".avif",
            "wanted-poster.png",
            "One-Piece-Manga.webp",
            "fiver",
            "ck-cdn.com"
        ]

        for i, image_url in enumerate(images):
            print(f"Downloading image {i+1}... {image_url}", end=' ')

            # Check if URL matches allowed domains
            if not any(re.search(pattern, image_url) for pattern in allowed_domains) or any(re.search(pattern, image_url) for pattern in blocked_patterns):
                print("❌ [Blocked]")
                continue  # Skip downloading

            try:
                response = requests.get(image_url)
                response.raise_for_status()
            except Exception as e:
                print(f"❌ Failed to download image: {e}")
                continue

            ext = os.path.splitext(image_url)[1].split('?')[0]
            if ext.lower() not in ['.jpg', '.jpeg', '.png']:
                ext = self.IMAGE_EXTENSION  # fallback extension

            image_path = os.path.join(self.OUTPUT_DIR, f"{chapter}_{i+1}{ext}")
            with open(image_path, "wb") as f:
                f.write(response.content)

            images_on_disk.append(image_path)
            print('✅')

        if not images_on_disk:
            print("No images downloaded.")
            return None, []

        output_pdf = os.path.join(self.OUTPUT_DIR, f"one piece - {chapter}.pdf")
        self.images_to_pdf(images_on_disk, output_pdf)
        print(f"Chapter {chapter} downloaded as PDF: {output_pdf}")

        if delete_images:
            self.delete_images()

        return output_pdf, images_on_disk

    def download_from_url(self, url, output_name="manual", delete_images=True):
        print(f"Downloading from direct URL: {url}")
        images = self.find_images(url)

        if not images:
            print("❌ No images found.")
            return None, []

        images_on_disk = []
        for i, image_url in enumerate(images):
            print(f"Downloading image {i+1}... {image_url}", end=' ')
            try:
                response = requests.get(image_url)
                response.raise_for_status()
                ext = os.path.splitext(image_url)[1].split('?')[0]
                if not ext.lower() in ['.jpg', '.jpeg', '.png']:
                    ext = '.jpeg'  # fallback
                image_path = os.path.join(self.OUTPUT_DIR, f"{output_name}_{i+1}{ext}")
                with open(image_path, "wb") as f:
                    f.write(response.content)
                images_on_disk.append(image_path)
                print('✅')
            except Exception as e:
                print(f"❌ Failed to download image: {e}")
                continue

        if not images_on_disk:
            return None, []

        output_pdf = os.path.join(self.OUTPUT_DIR, f"{output_name}.pdf")
        self.images_to_pdf(images_on_disk, output_pdf)
        print(f"✅ Download complete: {output_pdf}")

        if delete_images:
            self.delete_images()

        return output_pdf, images_on_disk

    def download_images(self, chapter):
        url = self.get_url(chapter) 
        print(f"Checking... {url}")
        images = self.find_images(url)

        images_on_disk = []
        allowed_domains = [
            "blogger.googleusercontent.com",
            "cdn.onepiecechapters.com",
            r"([a-z0-9]+)\.wp\.com",  # Regex to match any subdomain of wp.com
            "cdn", # loosely allow cdn
            "wp-content" # loosely allow wp-content
        ]

        blocked_patterns = [
            ".avif",
            "wanted-poster.png",
            "One-Piece-Manga.webp",
            "fiver",
            "ck-cdn.com"
        ]

        for i, image_url in enumerate(images):
            print(f"Downloading image {i+1}... {image_url}", end=' ')

            # Check if URL matches allowed domains
            if not any(re.search(pattern, image_url) for pattern in allowed_domains) or any(re.search(pattern, image_url) for pattern in blocked_patterns):
                print("❌ [Blocked]")
                continue  # Skip downloading

            response = requests.get(image_url)
            if response.status_code == 404:
                break
            
            image_path = os.path.join(self.OUTPUT_DIR, f"{chapter}_{i+1}{self.IMAGE_EXTENSION}")
            with open(image_path, "wb") as f:
                f.write(response.content)

            images_on_disk.append(image_path)
            print('✅')

        return images_on_disk

    def file_exists(self, file):
        return os.path.exists(file)

    def find_images(self, url):
        try:
            response = requests.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            image_links = []

            # Extract images from <img> tags
            for img in soup.find_all('img', src=True):
                img_src = img['src'].strip()
                if img_src.startswith("http") and img_src not in image_links:
                    image_links.append(img_src)

            # Extract images from <meta property="og:image">
            for meta in soup.find_all("meta", attrs={"property": "og:image"}):
                img_src = meta.get("content", "").strip()
                if img_src.startswith("http") and img_src not in image_links:
                    image_links.append(img_src)  # No modifications

            # for i in image_links:
            #     print(i)
            #     print()

            if(len(image_links) <= 5):
                print("Not enough images found, rejecting")
                for i in image_links:
                    print("  "+i)
                image_links = []

            return image_links
        except requests.RequestException as e:
            print(f"Error downloading the page: {e}")
            return []

    # def get_aspect_ratio(self, image_path):
    #     with Image.open(image_path) as img:
    #         width, height = img.size
    #         ratio_gcd = gcd(width, height)
    #         aspect_width = width // ratio_gcd
    #         aspect_height = height // ratio_gcd
    #         return f"{aspect_width}:{aspect_height}"

    def get_last_chapter(self):
        if os.path.exists(self.LAST_CHAPTER_FILE):
            with open(self.LAST_CHAPTER_FILE, "r") as f:
                return int(f.read().strip())
        return None

    def get_title(self, soup):
        p_tag = soup.find('p', class_='text-center text-text-muted font-bold mt-2')
        return p_tag.get_text(strip=True) if p_tag else soup.title.string

    def get_url(self, chapter):
        # return self.BASE_URL.format(chapter) 
        return self.get_url_from_table_of_contents(chapter)
    
    def get_url_from_table_of_contents(self, chapter):
        # Download the page content
        response = requests.get(self.TABLE_OF_CONTENTS_URL)
        response.raise_for_status()  # Raise an exception for HTTP errors
        # Parse the page with BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')
        # Search for all hyperlinks
        links = soup.find_all('a', href=True)
        # Construct the chapter string to match
        chapter_str = f"one-piece-chapter-{chapter}"
        # Search for the chapter in the hyperlinks
        for link in links:
            href = link['href']
            if chapter_str in href:
                return href  # Return the first matching URL
        # If no match is found, return None or raise an exception
        return None

    def images_to_pdf(self, image_paths, output_pdf):
        images = [Image.open(image_path).convert("L") for image_path in image_paths]
        images[0].save(output_pdf, "PDF", resolution=100.0, save_all=True, append_images=images[1:])

    def save_last_chapter(self, chapter):
        last_chapter = self.get_last_chapter()
        if last_chapter is None or chapter > last_chapter:
            print(f"Saving last chapter as {chapter}...")
            with open(self.LAST_CHAPTER_FILE, "w") as f:
                f.write(str(chapter))
        else:
            print(f"Keeping chapter already saved as {last_chapter}...")
