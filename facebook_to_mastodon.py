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

def fetch_feed_entries(feed_url):
    """RSS-Feed abrufen und Einträge sortieren."""
    feed = feedparser.parse(feed_url)
    print(f"DEBUG: {len(feed.entries)} Einträge im RSS-Feed gefunden.")
    return sorted(feed.entries, key=lambda x: parse(x.get('published', '')), reverse=False)

def get_last_published_date(mastodon):
    """Abrufen des Datums aus dem letzten geposteten Status."""
    try:
        user_info = mastodon.me()
        print(f"DEBUG: Erfolgreich verbunden als: {user_info['username']}")
        
        last_status = mastodon.account_statuses(user_info['id'], limit=1)
        if last_status:
            content = last_status[0]['content']
            match = re.search(r"Published on: (\d{2}/\d{2}/\d{4} \d{2}:\d{2})", content)
            if match:
                # Parse und Konvertierung in UTC
                last_published_date = parse(match.group(1), dayfirst=True).replace(tzinfo=datetime.timezone.utc)
                print(f"DEBUG: Letztes 'Published on'-Datum (UTC): {last_published_date}")
                return last_published_date
            else:
                print("DEBUG: Kein 'Published on'-Datum im letzten Post gefunden.")
                return None
        else:
            print("DEBUG: Keine vorherigen Posts gefunden.")
            return None
    except Exception as e:
        print(f"FEHLER: Verbindung zur Mastodon-API fehlgeschlagen: {e}")
        return None

def is_newer(last_date, new_date):
    """Vergleiche Jahr, Monat, Tag, Stunde und Minute schrittweise."""
    if not last_date:
        return True  # Kein vorheriger Post vorhanden

    # Schrittweiser Vergleich
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
    elif new_date.minute < last_date.minute:
        return False

    # Alle Werte sind gleich
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

def truncate_text(text, published_info, max_length=500):
    """Text auf die maximale Länge kürzen."""
    reserved_length = len(published_info) + 5
    text_cut = text[:max_length - reserved_length]
    if len(text) > len(text_cut):
        text_cut = text_cut.rstrip() + "..."
    return f"{text_cut}\n\n{published_info}"

def main(feed_entries, last_published_date):
    mastodon = Mastodon(access_token=access_token, api_base_url=api_base_url)
    for entry in feed_entries:
        entry_time = parse(entry.published).astimezone(datetime.timezone.utc) if 'published' in entry else None
        if not entry_time:
            print(f"DEBUG: Kein Zeitstempel für Eintrag: {entry.link}")
            continue

        print(f"DEBUG: Eintrag {entry.link} - Veröffentlichungszeit (UTC): {entry_time}")
        # Schrittweise prüfen, ob der neue Eintrag gepostet werden soll
        if not is_newer(last_published_date, entry_time):
            print(f"DEBUG: Eintrag {entry.link} übersprungen (älter oder gleich dem letzten 'Published on'-Datum).")
            continue

        clean_text, image_urls, video_urls = clean_content_and_extract_media(entry.summary)
        published_info = f"Published on: {entry_time.strftime('%d/%m/%Y %H:%M')}"
        message = truncate_text(clean_text, published_info)

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
        last_published_date = entry_time

        # Wartezeit zwischen den Posts
        time.sleep(15)

if __name__ == "__main__":
    mastodon_client = Mastodon(access_token=access_token, api_base_url=api_base_url)
    last_published_date = get_last_published_date(mastodon_client)
    entries = fetch_feed_entries(feed_url)
    main(entries, last_published_date)
