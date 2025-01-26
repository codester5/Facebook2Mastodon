import requests
from bs4 import BeautifulSoup
from mastodon import Mastodon
from tempfile import NamedTemporaryFile
import os
import mimetypes
import time
from datetime import datetime
import re

# Mastodon-Konfigurationsvariablen
api_base_url = os.getenv("MASTODON_API_URL")
access_token = os.getenv("MASTODON_ACCESS_TOKEN")
hashtags = os.getenv("HASHTAGS")  # Standard-Hashtags

# Twitter-URL aus Umgebungsvariablen
twitter_url = os.getenv("TWITTER_URL")  # Muss gesetzt werden

# Zeichenlimit pro Tröt
TROET_LIMIT = 500


def get_last_published_date(mastodon):
    """Abrufen des letzten veröffentlichten Datums von Mastodon."""
    user_info = mastodon.me()
    last_status = mastodon.account_statuses(user_info['id'], limit=1)
    if last_status:
        content = last_status[0]['content']
        match = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", content)
        if match:
            return datetime.strptime(match.group(1), "%d/%m/%Y %H:%M")
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


def scrape_twitter():
    """Scrapt die Twitter-Seite nach Tweets und Medien."""
    if not twitter_url:
        raise ValueError("FEHLER: TWITTER_URL ist nicht gesetzt.")
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(twitter_url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")

    tweets = []
    for tweet in soup.find_all("div", {"data-testid": "tweet"}):
        try:
            tweet_text = tweet.find("div", {"class": "css-901oao"}).text
            media_urls = [img["src"] for img in tweet.find_all("img") if "src" in img.attrs]
            tweet_time = datetime.now()  # Placeholder für Zeitstempel
            tweets.append({"text": tweet_text, "media": media_urls, "time": tweet_time})
        except Exception as e:
            print(f"ERROR: Fehler beim Verarbeiten eines Tweets: {e}")
            continue

    return tweets


def upload_media(mastodon, media_urls):
    """Bilder oder Videos hochladen und Media-IDs zurückgeben."""
    media_ids = []
    for media_url in media_urls[:4]:  # Maximal 4 Dateien
        try:
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
    return media_ids


def truncate_text(text, hashtags, date_info, max_length=500):
    """Text auf die maximale Länge kürzen."""
    hashtags_part = f"{hashtags}\n\n" if hashtags else ""
    reserved_length = len(hashtags_part) + len(date_info) + 5
    text_cut = text[:max_length - reserved_length]
    if len(text) > len(text_cut):
        text_cut = text_cut.rstrip() + "..."
    return f"{text_cut}\n\n{hashtags_part}{date_info}".strip()


def main():
    mastodon = Mastodon(access_token=access_token, api_base_url=api_base_url)
    last_published_date = get_last_published_date(mastodon)

    tweets = scrape_twitter()
    for tweet in tweets:
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
