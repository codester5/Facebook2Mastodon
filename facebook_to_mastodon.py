import feedparser
from mastodon import Mastodon
from tempfile import NamedTemporaryFile
import os
import requests
import json
import time
from dateutil.parser import parse
from bs4 import BeautifulSoup
import mimetypes
import re

# Anpassbare Variablen
api_base_url = os.getenv("MASTODON_API_URL")
access_token = os.getenv("MASTODON_ACCESS_TOKEN")
feed_url = os.getenv("FEED_URL")

def get_saved_timestamps():
    try:
        with open("saved_timestamps.json", "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return []

def save_timestamps(timestamps):
    with open("saved_timestamps.json", "w") as file:
        json.dump(timestamps, file)

def fetch_feed_entries(feed_url):
    feed = feedparser.parse(feed_url)
    print(f"DEBUG: {len(feed.entries)} Einträge im RSS-Feed gefunden.")
    return sorted(feed.entries, key=lambda x: parse(x.get('published', '')), reverse=False)

def upload_media(mastodon, media_urls, media_type):
    media_ids = []
    for media_url in media_urls[:4]:
        try:
            response = requests.get(media_url, timeout=20)
            response.raise_for_status()
            with NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(response.content)
                media_path = tmp_file.name
            mime_type = mimetypes.guess_type(media_path)[0] or 'application/octet-stream'
            with open(media_path, 'rb') as media_file:
                media_info = mastodon.media_post(
                    media_file,
                    mime_type=mime_type,
                    description="Automatisch generiertes Bild/Video"
                )
                media_ids.append(media_info['id'])
            os.unlink(media_path)
        except Exception as e:
            print(f"ERROR: {media_type.capitalize()}-Upload fehlgeschlagen: {e}")
    return media_ids

def clean_content_and_extract_media(summary):
    soup = BeautifulSoup(summary, 'html.parser')
    images = [img['src'] for img in soup.find_all('img') if 'src' in img.attrs]
    videos = [source['src'] for source in soup.find_all('source') if 'src' in source.attrs]
    text = soup.get_text().strip()
    text = re.sub(r'https?://(www\.)?facebook\.com\S*', '', text)
    return text.strip(), images, videos

def truncate_text(text, published_info, max_length=500):
    reserved_length = len(published_info) + 5
    text_cut = text[:max_length - reserved_length]
    if len(text) > len(text_cut):
        text_cut = text_cut.rstrip() + "..."
    return f"{text_cut}\n\n{published_info}"

def main(feed_entries):
    mastodon = Mastodon(access_token=access_token, api_base_url=api_base_url)
    saved_timestamps = get_saved_timestamps()
    print(f"DEBUG: Gespeicherte Zeitstempel: {saved_timestamps}")

    for entry in feed_entries:
        entry_time = parse(entry.published) if 'published' in entry else None
        if not entry_time:
            print(f"DEBUG: Kein Zeitstempel für Eintrag: {entry.link}")
            continue

        if entry_time.isoformat() in saved_timestamps:
            print(f"DEBUG: Eintrag {entry.link} übersprungen (bereits gepostet).")
            continue

        clean_text, image_urls, video_urls = clean_content_and_extract_media(entry.summary)
        published_info = f"Published on: {entry_time.strftime('%d/%m/%Y %H:%M')}"
        message = truncate_text(clean_text, published_info)

        if not message.strip():
            print("WARNUNG: Nachricht ist leer, überspringe Eintrag.")
            continue

        try:
            media_ids = []
            if image_urls:
                media_ids += upload_media(mastodon, image_urls, media_type="image")
            if video_urls:
                media_ids += upload_media(mastodon, video_urls, media_type="video")

            response = mastodon.status_post(message, media_ids=media_ids, visibility='public')
            print(f"INFO: Post erfolgreich: {response}")

            saved_timestamps.append(entry_time.isoformat())
            if len(saved_timestamps) > 20:
                saved_timestamps = saved_timestamps[-20:]
            save_timestamps(saved_timestamps)

        except Exception as e:
            print(f"ERROR: Fehler beim Posten von {entry.link}: {e}")
            continue

        time.sleep(15)

if __name__ == "__main__":
    entries = fetch_feed_entries(feed_url)
    main(entries)
