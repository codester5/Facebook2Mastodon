import requests
from bs4 import BeautifulSoup
from mastodon import Mastodon
from tempfile import NamedTemporaryFile
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
import os
import mimetypes
import time
from datetime import datetime
import re
import shutil

# Mastodon-Konfigurationsvariablen
api_base_url = os.getenv("MASTODON_API_URL")
access_token = os.getenv("MASTODON_ACCESS_TOKEN")
hashtags = os.getenv("HASHTAGS", "#Besiktas")  # Standard-Hashtags

twitter_url = os.getenv("TWITTER_URL")  # Muss gesetzt werden
TROET_LIMIT = 500
TROET_PAUSE = 35

def get_driver():
    options = Options()
    options.headless = True
    geckodriver_path = shutil.which("geckodriver")
    if not geckodriver_path:
        raise FileNotFoundError("GeckoDriver nicht im PATH gefunden.")
    service = Service(geckodriver_path)
    return webdriver.Firefox(service=service, options=options)

def scrape_twitter():
    driver = get_driver()
    driver.get(twitter_url)
    time.sleep(5)

    tweets = []
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_attempts = 0

    while True:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        for article in soup.find_all("article", {"role": "article"}):
            try:
                text_div = article.find("div", {"data-testid": "tweetText"})
                tweet_text = ""
                if text_div:
                    tweet_html = "".join(str(tag) for tag in text_div.contents)
                    tweet_text = BeautifulSoup(tweet_html, "html.parser").get_text(separator="\n")

                media_urls = []
                for img in article.find_all("img", {"src": True}):
                    if "twimg.com" in img["src"]:
                        media_urls.append(img["src"])

                for video in article.find_all("video"):
                    source = video.find("source", {"src": True})
                    if source and "twimg.com" in source["src"]:
                        media_urls.append(source["src"])

                if media_urls and "profile_images" in media_urls[0]:
                    print(f"DEBUG: Entferne das Profilbild: {media_urls[0]}")
                    media_urls = media_urls[1:]

                time_tag = article.find("time")
                tweet_time = (
                    datetime.strptime(time_tag["datetime"], "%Y-%m-%dT%H:%M:%S.%fZ")
                    if time_tag and time_tag.get("datetime")
                    else None
                )
                if not tweet_time:
                    continue

                if any(tweet["time"] == tweet_time for tweet in tweets):
                    continue

                tweets.append({"text": tweet_text, "media": media_urls, "time": tweet_time})
                print(f"DEBUG: Gefundener Tweet: {tweets[-1]}")
            except Exception as e:
                print(f"ERROR: Fehler beim Verarbeiten eines Tweets: {e}")
                continue

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(5)

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            scroll_attempts += 1
            if scroll_attempts > 4:
                break
        else:
            scroll_attempts = 0
            last_height = new_height

    driver.quit()
    print(f"DEBUG: Insgesamt {len(tweets)} Tweets gefunden.")
    return sorted(tweets, key=lambda x: x["time"])

def upload_media(mastodon, media_urls):
    media_ids = []
    for media_url in media_urls[:4]:
        try:
            print(f"DEBUG: Lade Medien hoch: {media_url}")
            response = requests.get(media_url, timeout=20)
            response.raise_for_status()

            mime_type = mimetypes.guess_type(media_url)[0]
            if not mime_type:
                mime_type = "image/jpeg"

            with NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(response.content)
                media_path = tmp_file.name

            with open(media_path, "rb") as media_file:
                media_info = mastodon.media_post(
                    media_file,
                    mime_type=mime_type,
                    description="Automatisch generiertes Bild/Video"
                )
                media_ids.append(media_info["id"])
            os.unlink(media_path)
        except Exception as e:
            print(f"ERROR: Fehler beim Hochladen von Medien: {e}")
    print(f"DEBUG: Hochgeladene Medien-IDs: {media_ids}")
    return media_ids

def truncate_text(text, hashtags, date_info, max_length=500):
    hashtags_part = f"{hashtags}\n\n" if hashtags else ""
    reserved_length = len(hashtags_part) + len(date_info) + 5
    text_cut = text[:max_length - reserved_length]
    if len(text) > len(text_cut):
        text_cut = text_cut.rstrip() + "..."
    return f"{text_cut}\n\n{hashtags_part}{date_info}".strip()

def get_last_published_date(mastodon):
    user_info = mastodon.me()
    last_status = mastodon.account_statuses(user_info["id"], limit=1)
    if last_status:
        content = last_status[0]["content"]
        match = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", content)
        if match:
            return datetime.strptime(match.group(1), "%d/%m/%Y %H:%M")
    return None

def is_strictly_newer(last_date, new_date):
    if not last_date:
        return True
    if new_date > last_date:
        return True
    return False

def main():
    mastodon = Mastodon(access_token=access_token, api_base_url=api_base_url)
    last_published_date = get_last_published_date(mastodon)

    tweets = scrape_twitter()
    for tweet in tweets:
        if not is_strictly_newer(last_published_date, tweet["time"]):
            print(f"DEBUG: Übersprungener Tweet wegen Datum: {tweet}")
            continue

        date_info = tweet["time"].strftime("%d/%m/%Y %H:%M")
        message = truncate_text(tweet["text"], hashtags, date_info)
        media_ids = upload_media(mastodon, tweet["media"])

        try:
            mastodon.status_post(message, media_ids=media_ids, visibility="public")
            last_published_date = tweet["time"]
            print(f"DEBUG: Warte {TROET_PAUSE} Sekunden vor dem nächsten Tröt...")
            time.sleep(TROET_PAUSE)
        except Exception as e:
            print(f"ERROR: Fehler beim Posten des Tweets: {e}")

if __name__ == "__main__":
    main()
