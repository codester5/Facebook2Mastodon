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
    print(f"DEBUG: {len(feed.entries)} Einträge im RSS-Feed gefunden.")
    return sorted(feed.entries, key=lambda x: parse(x.get('published', '')), reverse=False)

# Medien (Bilder/Videos) hochladen
def upload_media(mastodon, media_urls, media_type):
    media_ids = []
    for media_url in media_urls[:4]:  # Maximal 4 Medien
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

# HTML bereinigen und Medien extrahieren
def clean_content_and_extract_media(summary):
    soup = BeautifulSoup(summary, 'html.parser')
    images = [img['src'] for img in soup.find_all('img') if 'src' in img.attrs]
    videos = [source['src'] for source in soup.find_all('source') if 'src' in source.attrs]
    text = soup.get_text().strip()

    # Facebook-Link entfernen
    text = re.sub(r'https?://(www\.)?facebook\.com\S*', '', text)
    return text.strip(), images, videos

# Text kürzen
def truncate_text(text, published_info, max_length=500):
    """Kürzt den Text auf die maximale Länge und priorisiert das Datum."""
    # Berechne verfügbare Länge für den eigentlichen Text
    reserved_length = len(published_info) + 5  # Platz für Datum und Trennung
    text_cut = text[:max_length - reserved_length]
    
    # Anhängen von "..." bei Kürzung
    if len(text) > len(text_cut):
        text_cut = text_cut.rstrip() + "..."
    
    return f"{text_cut}\n\n{published_info}"

# Hauptfunktion
def main(feed_entries):
    mastodon = Mastodon(access_token=access_token, api_base_url=api_base_url)
    saved_timestamps = get_saved_timestamps()
    print(f"DEBUG: Gespeicherte Zeitstempel: {saved_timestamps}")

    for entry in feed_entries:
        # Zeitstempel des Eintrags extrahieren
        entry_time = parse(entry.published) if 'published' in entry else None
        if not entry_time:
            print(f"DEBUG: Kein Zeitstempel für Eintrag: {entry.link}")
            continue

        # Prüfen, ob der Eintrag neuer ist oder nicht gepostet wurde
        if entry_time.isoformat() in saved_timestamps:
            print(f"DEBUG: Eintrag {entry.link} übersprungen (bereits gepostet).")
            continue

        clean_text, image_urls, video_urls = clean_content_and_extract_media(entry.summary)

        # Datum und Uhrzeit des Originalposts hinzufügen (TT/MM/JJJJ HH:MM)
        published_info = f"Published on: {entry_time.strftime('%d/%m/%Y %H:%M')}"
        message = truncate_text(clean_text, published_info)

        try:
            media_ids = []
            if image_urls:
                media_ids += upload_media(mastodon, image_urls, media_type="image")
            if video_urls:
                media_ids += upload_media(mastodon, video_urls, media_type="video")

            response = mastodon.status_post(message, media_ids=media_ids, visibility='public')
            print(f"INFO: Post erfolgreich: {response}")

            # Zeitstempel sofort speichern
            saved_timestamps.append(entry_time.isoformat())
            if len(saved_timestamps) > 20:
                saved_timestamps = saved_timestamps[-20:]
            save_timestamps(saved_timestamps)  # Aktualisierung direkt nach dem Post

        except Exception as e:
            if "429" in str(e):
                print("WARNUNG: Ratenlimit überschritten. Warte 2 Minuten.")
                time.sleep(120)
            else:
                print(f"ERROR: Fehler beim Posten von {entry.link}: {e}")
                continue

        time.sleep(45)  # 15 Sekunden Pause zwischen den Posts

if __name__ == "__main__":
    entries = fetch_feed_entries(feed_url)
    main(entries)
