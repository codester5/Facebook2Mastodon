import feedparser
from mastodon import Mastodon
from tempfile import NamedTemporaryFile
import os
import requests
import time
from dateutil.parser import parse
from bs4 import BeautifulSoup
import mimetypes
import datetime
import re

# Anpassbare Variablen
api_base_url = os.getenv("MASTODON_API_URL")  # Mastodon-Instanz
access_token = os.getenv("MASTODON_ACCESS_TOKEN")  # Access-Token
feed_url = os.getenv("FEED_URL")  # RSS-Feed-URL
hashtags = os.getenv("HASHTAGS")  # Hashtags

def fetch_feed_entries(feed_url):
    """RSS-Feed abrufen und Einträge sortieren."""
    feed = feedparser.parse(feed_url)
    print(f"DEBUG: {len(feed.entries)} Einträge im RSS-Feed gefunden.")
    return sorted(feed.entries, key=lambda x: parse(x.get('published', '')), reverse=False)

def extract_date_parts(date_str):
    """Extrahiere Jahr, Monat, Tag, Stunde und Minute aus einem Datumsstring im Format 'TT/MM/JJJJ HH:MM'."""
    try:
        day, month, year, hour, minute = map(int, re.match(r"(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2})", date_str).groups())
        return year, month, day, hour, minute
    except AttributeError:
        print("FEHLER: Ungültiges Datumsformat im letzten Post.")
        return None

def get_last_published_date(mastodon):
    """Abrufen des Datums aus dem letzten geposteten Status."""
    try:
        user_info = mastodon.me()
        print(f"DEBUG: Erfolgreich verbunden als: {user_info['username']}")
        
        last_status = mastodon.account_statuses(user_info['id'], limit=1)
        if last_status:
            content = last_status[0]['content']
            match = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2})$", content)
            if match:
                date_parts = extract_date_parts(match.group(1))
                print(f"DEBUG: Letztes Veröffentlichungsdatum (Teile): {date_parts}")
                return date_parts
            else:
                print("DEBUG: Kein gültiger Datumsstempel im letzten Post gefunden.")
                return None
        else:
            print("DEBUG: Keine vorherigen Posts gefunden.")
            return None
    except Exception as e:
        print(f"FEHLER: Verbindung zur Mastodon-API fehlgeschlagen: {e}")
        return None

def is_newer(last_date_parts, new_date):
    """Vergleiche Jahr, Monat, Tag, Stunde und Minute schrittweise."""
    if not last_date_parts:
        return True  # Kein vorheriger Post vorhanden

    new_date_parts = (new_date.year, new_date.month, new_date.day, new_date.hour, new_date.minute)

    if new_date_parts > last_date_parts:
        return True
    return False

def upload_media(mastodon, media_urls, media_type):
    """Bilder oder Videos hochladen und Media-IDs zurückgeben."""
    media_ids = []
    for media_url in media_urls[:4]:  # Maximal 4 Dateien
        try:
            response = requests.get(media_url, timeout=20)
            response.raise_for_status()
            with NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(response.content)
                image_path = tmp_file.name
            mime_type = mimetypes.guess_type(image_path)[0] or 'image/jpeg'
            with open(image_path, 'rb') as media_file:
                media_info = mastodon.media_post(
                    media_file,
                    mime_type=mime_type,
                    description="Automatisch generiertes Bild/Video"
                )
                media_ids.append(media_info['id'])
            os.unlink(image_path)
        except Exception as e:
            print(f"ERROR: {media_type.capitalize()}-Upload fehlgeschlagen: {e}")
    return media_ids

def clean_content_and_extract_media(summary):
    """Inhalt bereinigen und Medien-URLs extrahieren."""
    soup = BeautifulSoup(summary, 'html.parser')
    images = [img['src'] for img in soup.find_all('img') if 'src' in img.attrs]
    videos = [source['src'] for source in soup.find_all('source') if 'src' in source.attrs]
    text = soup.get_text().strip()
    text = re.sub(r'https?://(www\.)?facebook\.com\S*', '', text)
    return text.strip(), images, videos

def truncate_text(text, hashtags, date_info, max_length=500):
    """Text auf die maximale Länge kürzen."""
    hashtags_part = f"{hashtags}\n\n" if hashtags else ""
    reserved_length = len(hashtags_part) + len(date_info) + 5
    text_cut = text[:max_length - reserved_length]
    if len(text) > len(text_cut):
        text_cut = text_cut.rstrip() + "..."
    return f"{text_cut}\n\n{hashtags_part}{date_info}".strip()

def main(feed_entries, last_published_date_parts):
    mastodon = Mastodon(access_token=access_token, api_base_url=api_base_url)
    for entry in feed_entries:
        entry_time = parse(entry.published).astimezone(datetime.timezone.utc) if 'published' in entry else None
        if not entry_time:
            print(f"DEBUG: Kein Zeitstempel für Eintrag: {entry.link}")
            continue

        print(f"DEBUG: Eintrag {entry.link} - Veröffentlichungszeit (UTC): {entry_time}")
        if not is_newer(last_published_date_parts, entry_time):
            print(f"DEBUG: Eintrag {entry.link} übersprungen (älter oder gleich dem letzten Veröffentlichungsdatum).")
            continue

        clean_text, image_urls, video_urls = clean_content_and_extract_media(entry.summary)
        date_info = entry_time.strftime('%d/%m/%Y %H:%M')
        message = truncate_text(clean_text, hashtags, date_info)

        if not message.strip():
            print("WARNUNG: Nachricht ist leer, überspringe Eintrag.")
            continue

        media_ids = []
        if image_urls:
            media_ids += upload_media(mastodon, image_urls, media_type="image")
        if video_urls:
            media_ids += upload_media(mastodon, video_urls, media_type="video")

        try:
            mastodon.status_post(message, media_ids=media_ids, visibility='public')
            print(f"INFO: Post erfolgreich: {entry.link}")
        except Exception as e:
            print(f"ERROR: Fehler beim Posten von {entry.link}: {e}")

        # Aktualisiere das letzte Veröffentlichungsdatum
        last_published_date_parts = (entry_time.year, entry_time.month, entry_time.day, entry_time.hour, entry_time.minute)

        # Wartezeit zwischen den Posts
        time.sleep(15)

if __name__ == "__main__":
    mastodon_client = Mastodon(access_token=access_token, api_base_url=api_base_url)
    last_published_date_parts = get_last_published_date(mastodon_client)
    entries = fetch_feed_entries(feed_url)
    main(entries, last_published_date_parts)
