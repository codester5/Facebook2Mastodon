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
api_base_url = os.getenv("MASTODON_API_URL")  # Mastodon-Instanz
access_token = os.getenv("MASTODON_ACCESS_TOKEN")  # Access-Token
feed_url = os.getenv("FEED_URL")  # RSS-Feed-URL

# Gespeicherte Zeitstempel verwalten
def get_saved_timestamps():
    try:
        with open("saved_timestamps.json", "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return []

def save_timestamps(timestamps):
    with open("saved_timestamps.json", "w") as file:
        json.dump(timestamps, file)

# RSS-Feed einlesen
def fetch_feed_entries(feed_url):
    feed = feedparser.parse(feed_url)
    return sorted(feed.entries, key=lambda x: parse(x.get('published', '')), reverse=False)

# Bilder hochladen
def upload_images(mastodon, image_urls):
    media_ids = []
    for image_url in image_urls[:4]:  # Maximal 4 Bilder
        try:
            response = requests.get(image_url, timeout=20)
            response.raise_for_status()
            with NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(response.content)
                image_path = tmp_file.name
            mime_type = mimetypes.guess_type(image_path)[0] or 'image/jpeg'
            with open(image_path, 'rb') as image_file:
                media_info = mastodon.media_post(image_file, mime_type=mime_type, description="Bild")
                media_ids.append(media_info['id'])
            os.unlink(image_path)
        except Exception as e:
            print(f"ERROR: Bild-Upload fehlgeschlagen: {e}")
    return media_ids

# HTML bereinigen
def clean_content(summary):
    soup = BeautifulSoup(summary, 'html.parser')
    for img in soup.find_all('img'):
        img.decompose()
    return soup.get_text().strip()

# Hauptfunktion
def main(feed_entries):
    mastodon = Mastodon(access_token=access_token, api_base_url=api_base_url)
    saved_timestamps = get_saved_timestamps()

    for entry in feed_entries:
        # Zeitstempel des Eintrags extrahieren
        entry_time = parse(entry.published) if 'published' in entry else None
        if not entry_time:
            continue

        # Prüfen, ob der Eintrag neuer ist als der letzte gespeicherte Zeitstempel
        if saved_timestamps and entry_time <= parse(saved_timestamps[-1]):
            print(f"DEBUG: Eintrag {entry.link} übersprungen (älter oder gleich dem letzten gespeicherten Zeitstempel).")
            continue

        clean_text = clean_content(entry.summary)
        image_urls = [img['src'] for img in BeautifulSoup(entry.summary, 'html.parser').find_all('img')]
        message = f"{clean_text}\n\n{entry.link}"

        try:
            if image_urls:
                media_ids = upload_images(mastodon, image_urls)
                mastodon.status_post(message, media_ids=media_ids, visibility='public')
            else:
                mastodon.status_post(message, visibility='public')
            print(f"INFO: Eintrag gepostet: {entry.link}")
        except Exception as e:
            print(f"ERROR: Fehler beim Posten von {entry.link}: {e}")
            continue

        # Zeitstempel speichern
        saved_timestamps.append(entry_time.isoformat())

        # Nur die letzten 20 Zeitstempel speichern
        if len(saved_timestamps) > 20:
            saved_timestamps = saved_timestamps[-20:]

        # Zeitstempel aktualisieren
        save_timestamps(saved_timestamps)

        time.sleep(15)  # 15 Sekunden Pause zwischen den Posts

if __name__ == "__main__":
    entries = fetch_feed_entries(feed_url)
    main(entries)
