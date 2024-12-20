import os
import requests
from PIL import Image
from fpdf import FPDF
from bs4 import BeautifulSoup
import re

class MangaDownloader:
    TABLE_OF_CONTENTS_URL = "https://w15.read-onepiece-manga.com/"
    BASE_URL = "https://cdn.readonepiece.com/file/mangap/2"
    IMAGE_EXTENSION = ".jpeg"
    LAST_CHAPTER_FILE = "last_chapter.txt"
    OUTPUT_DIR = "manga_chapters"

    def __init__(self):
        # Ensure the output directory exists
        if not os.path.exists(self.OUTPUT_DIR):
            os.makedirs(self.OUTPUT_DIR)

    def get_url(self, chapter):

        if(chapter is None):
            # load from file
            with open(self.LAST_CHAPTER_FILE, "r") as f:
                chapter = int(f.read().strip())

        #return f'https://ww10.readonepiece.com/chapter/one-piece-chapter-{chapter}/'
        # https://w13.read-onepiece-manga.com/
        return f'https://www.read-onepiece-manga.com/manga/one-piece-chapter-{chapter}/'

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


    def get_last_chapter(self):
        if os.path.exists(self.LAST_CHAPTER_FILE):
            with open(self.LAST_CHAPTER_FILE, "r") as f:
                return int(f.read().strip())
        return None

    def save_last_chapter(self, chapter):
        last_chapter = self.get_last_chapter()
        if chapter > last_chapter:
            print(f"Saving last chapter as {chapter}...")
            with open(self.LAST_CHAPTER_FILE, "w") as f:
                f.write(str(chapter))
        else:
            print(f"Keeping chapter already saved as {last_chapter}...")

    def find_cdn_images(self, url):
        try:
            print(f"Checking images from... {url}")
            # Download the page content
            response = requests.get(url)
            response.raise_for_status()  # Raise an exception for HTTP errors

            # Parse the page with BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')

            # Find all the links that match the patterns
            cdn_image_links = []

            # Define patterns for matching the image URLs
            patterns = [
                re.compile(r'https://cdn.*\.(png|jpeg)'),
                re.compile(r'https://.*manga_.*\.jpeg')
            ]

            # Check each image source against the patterns
            for img in soup.find_all('img', src=True):
                img_src = img['src'].replace('\r', '')
                if any(pattern.match(img_src) for pattern in patterns):
                    cdn_image_links.append(img_src)
                    print(img_src)
                # else:
                #     print(f"Skipping image... {img_src}")

            # Remove any potential ? query string from end of URLs
            cdn_image_links = [re.sub(r'\?.*', '', img) for img in cdn_image_links]
            
            title = self.get_title(soup)

            return cdn_image_links

        except requests.RequestException as e:
            print(f"Error downloading the page: {e}")
            return []

    def download_images(self, chapter, cdn_images = None):

        if cdn_images is not None:
            print(f"Downloading known images from CDN...")
            images = cdn_images
        else:
            url = self.get_url(chapter)
            print(f"Checking... {url}")
            images = self.find_cdn_images(url)

        if(len(images) == 0):
            content_url = self.get_url_from_table_of_contents(chapter)

            if url is not None and content_url is not None:       
                url = content_url     
                print(f"Checking... {url}")
                images = self.find_cdn_images(url)

        print(images)

        images_on_disk = []

        for i, image_url in enumerate(images):
            # skip title or translator cover images
            # not reliable enough atm
            # if image_url.endswith('01.png') or image_url.endswith('01.jpeg'):
            #     print(f"Skipping image {i+1}... {image_url}")
            #     continue

            print(f"Downloading image {i+1}... {image_url}")
            response = requests.get(image_url)
            if response.status_code == 404:
                break
            image_path = os.path.join(self.OUTPUT_DIR, f"{chapter}_{i+1}{self.IMAGE_EXTENSION}")
            with open(image_path, "wb") as f:
                f.write(response.content)
            images_on_disk.append(image_path)

        return images_on_disk

    def images_to_pdf(self, image_paths, output_pdf):
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

    def delete_images(self, image_paths):
        for image_path in image_paths:
            os.remove(image_path)

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
            return None, chapter

    def delete_images(self):
        # delete any image files from manga_chapters folder

        # for each file in the manga_chapters folder
        for file in os.listdir("manga_chapters"):
            # if the file is an image
            if file.endswith(self.IMAGE_EXTENSION):
                # delete the file
                os.remove(os.path.join(self.OUTPUT_DIR, file))

    def file_exists(self, file):
        return os.path.exists(file)

    def get_title(self, soup):
        # Find the <p> tag with the specific class
        p_tag = soup.find('p', class_='text-center text-text-muted font-bold mt-2')
        
        # Extract the text content
        if p_tag:
            return p_tag.get_text(strip=True)
        return soup.title.string
        
    def download_and_get_title(self, url):
        # Download the page content
        response = requests.get(url)
        response.raise_for_status()

        # Parse the page with BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')

        print(self.get_title(soup))

        return self.get_title(soup)