import requests
from bs4 import BeautifulSoup
from mastodon import Mastodon
from tempfile import NamedTemporaryFile
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import os
import mimetypes
import time
from datetime import datetime
import re

# Mastodon-Konfigurationsvariablen
api_base_url = os.getenv("MASTODON_API_URL")
access_token = os.getenv("MASTODON_ACCESS_TOKEN")
hashtags = os.getenv("HASHTAGS", "#Besiktas")  # Standard-Hashtags

# Twitter-URL aus Umgebungsvariablen
twitter_url = os.getenv("TWITTER_URL")  # Muss gesetzt werden

# Zeichenlimit pro Tröt
TROET_LIMIT = 500


def get_driver():
    """Erstelle und konfiguriere den Selenium WebDriver."""
    options = Options()
    options.add_argument("--headless")  # Ohne GUI
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    service = Service("/usr/local/bin/chromedriver")  # Anpassen, falls lokal ein anderer Pfad verwendet wird
    return webdriver.Chrome(service=service, options=options)


def scrape_twitter():
    """Scrapt die Twitter-Seite nach Tweets, Medien und Zeitstempeln."""
    if not twitter_url:
        raise ValueError("FEHLER: TWITTER_URL ist nicht gesetzt.")
    
    print(f"DEBUG: Scraping Twitter-Seite mit Selenium: {twitter_url}")
    driver = get_driver()
    driver.get(twitter_url)
    time.sleep(5)  # Warte, bis die Seite vollständig geladen ist

    # Extrahiere den HTML-Quellcode
    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    tweets = []
    for article in soup.find_all("article", {"role": "article"}):
        try:
            # Extrahiere den Text
            text_div = article.find("div", {"data-testid": "tweetText"})
            tweet_text = text_div.get_text(strip=True) if text_div else "Kein Text gefunden"

            # Extrahiere Medien-URLs (Bilder und Videos)
            media_urls = []
            for img in article.find_all("img", {"alt": "Bild"}):
                media_urls.append(img["src"])

            for video in article.find_all("video"):
                source = video.find("source")
                if source and source.get("src"):
                    media_urls.append(source["src"])

            # Extrahiere den Zeitstempel
            time_tag = article.find("time")
            tweet_time = (
                datetime.strptime(time_tag["datetime"], "%Y-%m-%dT%H:%M:%S.%fZ")
                if time_tag and time_tag.get("datetime")
                else datetime.now()
            )

            # Füge die Daten in die Tweets-Liste hinzu
            tweets.append({"text": tweet_text, "media": media_urls, "time": tweet_time})
            print(f"DEBUG: Gefundener Tweet: {tweet_text[:50]}... mit {len(media_urls)} Medien, Zeitstempel: {tweet_time}")
        except Exception as e:
            print(f"ERROR: Fehler beim Verarbeiten eines Tweets: {e}")
            continue

    print(f"DEBUG: Insgesamt {len(tweets)} Tweets gefunden.")
    return tweets


def get_last_published_date(mastodon):
    """Abrufen des letzten veröffentlichten Datums von Mastodon."""
    try:
        user_info = mastodon.me()
        print(f"DEBUG: Verbunden als Mastodon-Nutzer: {user_info['username']}")
        last_status = mastodon.account_statuses(user_info['id'], limit=1)
        if last_status:
            content = last_status[0]['content']
            print(f"DEBUG: Letzter Mastodon-Tröt: {content}")
            match = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", content)
            if match:
                timestamp = datetime.strptime(match.group(1), "%d/%m/%Y %H:%M")
                print(f"DEBUG: Letzter veröffentlichter Zeitstempel: {timestamp}")
                return timestamp
        print("DEBUG: Kein vorheriger Post mit gültigem Zeitstempel gefunden.")
    except Exception as e:
        print(f"ERROR: Fehler beim Abrufen des letzten Datums: {e}")
    return None


def is_strictly_newer(last_date, new_date):
    """Vergleiche Jahr, Monat, Tag, Stunde und Minute schrittweise."""
    if not last_date:
        return True
    if new_date.year > last_date.year:
        return True
    elif new_date.year < last_date.year:
        return False
    if new_date.month > last_date.month:
        return True
    elif new_date.month < last_date.month:
        return False
    if new_date.day > last_date.day:
        return True
    elif new_date.day < last_date.day:
        return False
    if new_date.hour > last_date.hour:
        return True
    elif new_date.hour < last_date.hour:
        return False
    if new_date.minute > last_date.minute:
        return True
    return False


def upload_media(mastodon, media_urls):
    """Bilder oder Videos hochladen und Media-IDs zurückgeben."""
    media_ids = []
    for media_url in media_urls[:4]:  # Maximal 4 Dateien
        try:
            print(f"DEBUG: Lade Medien hoch: {media_url}")
            response = requests.get(media_url, timeout=20)
            response.raise_for_status()
            with NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(response.content)
                media_path = tmp_file.name
            mime_type = mimetypes.guess_type(media_path)[0] or "image/jpeg"
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
    """Text auf die maximale Länge kürzen."""
    hashtags_part = f"{hashtags}\n\n" if hashtags else ""
    reserved_length = len(hashtags_part) + len(date_info) + 5
    text_cut = text[:max_length - reserved_length]
    if len(text) > len(text_cut):
        text_cut = text_cut.rstrip() + "..."
    truncated_text = f"{text_cut}\n\n{hashtags_part}{date_info}".strip()
    print(f"DEBUG: Trunkierter Text: {truncated_text[:50]}...")
    return truncated_text


def main():
    mastodon = Mastodon(access_token=access_token, api_base_url=api_base_url)
    last_published_date = get_last_published_date(mastodon)

    tweets = scrape_twitter()
    for tweet in tweets:
        print(f"DEBUG: Verarbeite Tweet mit Zeitstempel: {tweet['time']}")
        if not is_strictly_newer(last_published_date, tweet["time"]):
            print("DEBUG: Tweet übersprungen (älter oder gleich dem letzten Veröffentlichungsdatum).")
            continue

        date_info = tweet["time"].strftime("%d/%m/%Y %H:%M")
        message = truncate_text(tweet["text"], hashtags, date_info)

        media_ids = upload_media(mastodon, tweet["media"])

        try:
            mastodon.status_post(message, media_ids=media_ids, visibility="public")
            print(f"INFO: Tweet erfolgreich gepostet: {message}")
            last_published_date = tweet["time"]
        except Exception as e:
            print(f"ERROR: Fehler beim Posten des Tweets: {e}")

        # Pause zwischen Tröts
        time.sleep(15)


if __name__ == "__main__":
    main()
