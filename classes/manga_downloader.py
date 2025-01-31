import os
import requests
from PIL import Image
from fpdf import FPDF
from bs4 import BeautifulSoup
import re

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

    def download_chapter(self, chapter=None, delete_images=True):
        if chapter is None:
            last_chapter = self.get_last_chapter()
            chapter = last_chapter + 1 if last_chapter else 1

        print(f"Downloading chapter {chapter}...")
        images = self.download_images(chapter)
        if images:
            output_pdf = os.path.join(self.OUTPUT_DIR, f"one piece - {chapter}.pdf")
            self.images_to_pdf(images, output_pdf)
            print(f"Chapter {chapter} downloaded and saved as {output_pdf}")
            if delete_images:
                self.delete_images()
            self.save_last_chapter(chapter)
            return output_pdf
        else:
            print(f"No images found for chapter {chapter}. It might not be released yet.")
            return None

    def download_images(self, chapter):
        url = self.get_url(chapter)  # Fix: No longer returns a tuple
        print(f"Checking... {url}")
        images = self.find_images(url)

        images_on_disk = []
        for i, image_url in enumerate(images):
            print(f"Downloading image {i+1}... {image_url}")
            response = requests.get(image_url)
            if response.status_code == 404:
                break
            image_path = os.path.join(self.OUTPUT_DIR, f"{chapter}_{i+1}{self.IMAGE_EXTENSION}")
            with open(image_path, "wb") as f:
                f.write(response.content)
            images_on_disk.append(image_path)

        return images_on_disk

    def file_exists(self, file):
        return os.path.exists(file)

    def find_images(self, url):
        try:
            response = requests.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            image_links = []
            pattern = re.compile(r'https://.*\.(png|jpg|jpeg)')

            for img in soup.find_all('img', src=True):
                
                img_src = img['src'].replace('\r', '')
                # if pattern.match(img_src) and re.match(r'.*/[\d-]+\.(png|jpg|jpeg)$', img_src):
                #     image_links.append(img_src)

                print('Checking: ', img_src)

                # allow any image so long as it ends with a number and extension: png, jpg, jpeg
                # for example: https://cdn.onepiecechapters.com/file/CDN-M-A-N/onepiece_1136_sun_001.png
                # also must start with https://
                if re.match(r'https://.*\d+\.(png|jpg|jpeg)$', img_src):
                    image_links.append(img_src)

            image_links = [re.sub(r'\?.*', '', img) for img in image_links]
            return image_links
        except requests.RequestException as e:
            print(f"Error downloading the page: {e}")
            return []

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
