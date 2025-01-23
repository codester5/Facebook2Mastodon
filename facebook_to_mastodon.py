import feedparser
from mastodon import Mastodon
from tempfile import NamedTemporaryFile
import re
import os
import requests
import datetime
from dateutil.parser import parse
import mimetypes
from bs4 import BeautifulSoup
import time
import json

# Anpassbare Variablen
api_base_url = os.getenv("MASTODON_API_URL")  # Die Basis-URL deiner Mastodon-Instanz
access_token = os.getenv("MASTODON_ACCESS_TOKEN")  # Dein Access-Token
feed_url = os.getenv("FEED_URL")  # URL des RSS-Feeds

SAVED_ENTRIES_FILE = "saved_entry_ids.json"
MAX_SAVED_ENTRIES = 20  # Anzahl der gespeicherten IDs


def get_saved_entry_ids():
    """Lädt die gespeicherten IDs aus einer Datei."""
    try:
        with open(SAVED_ENTRIES_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_entry_ids(saved_ids):
    """Speichert die IDs in einer Datei."""
    with open(SAVED_ENTRIES_FILE, "w") as file:
        json.dump(saved_ids, file)


def fetch_feed_entries(feed_url):
    """Ruft den RSS-Feed ab und gibt die Einträge sortiert zurück."""
    feed = feedparser.parse(feed_url)
    return sorted(feed.entries, key=lambda x: parse(x.get("published", "")), reverse=False)


def generate_entry_id(entry):
    """Erzeugt eine eindeutige ID für einen Feed-Eintrag."""
    link = entry.get("link", "")
    published = entry.get("published", "")
    return f"{link}-{published}" if published else link


def post_to_mastodon(mastodon, message, image_urls=None):
    """Postet einen Beitrag (mit oder ohne Bilder) auf Mastodon."""
    message = truncate_text(message)
    media_ids = []

    if image_urls:
        media_ids = upload_images(mastodon, image_urls)

    mastodon.status_post(message, media_ids=media_ids, visibility="public")


def truncate_text(text):
    """Kürzt den Text auf 500 Zeichen."""
    return text[:500] if len(text) > 500 else text


def upload_images(mastodon, image_urls):
    """Lädt Bilder hoch und gibt die Media-IDs zurück."""
    media_ids = []
    for image_url in image_urls[:4]:  # Maximal 4 Bilder
        try:
            response = requests.get(image_url, timeout=20)
            response.raise_for_status()

            with NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(response.content)
                image_path = tmp_file.name

            mime_type, _ = mimetypes.guess_type(image_path)
            if not mime_type:
                mime_type = "image/jpeg"

            with open(image_path, "rb") as image_file:
                media_info = mastodon.media_post(image_file, description="Automatisch generiertes Bild")
                media_ids.append(media_info["id"])

            os.unlink(image_path)  # Temporäre Datei löschen
        except Exception as e:
            print(f"Fehler beim Hochladen des Bildes: {e}")
    return media_ids


def clean_content_keep_links(content):
    """Bereinigt den Inhalt und behält Links."""
    cleaned_content = re.sub(r"<img\s+[^>]*>", "", content)
    cleaned_content = re.sub(r"<[^<]+?>", "", cleaned_content).strip()
    return " ".join(cleaned_content.split())


def extract_image_urls_from_summary(summary):
    """Extrahiert Bild-URLs aus dem Summary-Feld."""
    soup = BeautifulSoup(summary, "html.parser")
    return [img["src"] for img in soup.find_all("img") if "src" in img.attrs]


def main():
    """Hauptprogramm."""
    mastodon = Mastodon(
        access_token=access_token,
        api_base_url=api_base_url,
        request_timeout=20
    )

    # Verarbeitete IDs laden
    saved_entry_ids = get_saved_entry_ids()
    feed_entries = fetch_feed_entries(feed_url)

    for entry in feed_entries:
        entry_id = generate_entry_id(entry)
        if entry_id in saved_entry_ids:
            continue  # Überspringe bereits verarbeitete Einträge

        title = entry.get("title", "")
        summary = entry.get("summary", "")
        link = entry.get("link", "")
        published = entry.get("published", "")
        clean_content = clean_content_keep_links(summary).strip()

        image_urls = extract_image_urls_from_summary(summary)

        # Erstelle den Beitragstext
        if published:
            posted_time = parse(published).astimezone().strftime("%d.%m.%Y %H:%M")
        else:
            posted_time = "Unbekannt"

        message = f"{clean_content}\n\n{link}\n\nVeröffentlicht am: {posted_time}"

        # Beitrag posten
        post_to_mastodon(mastodon, message, image_urls)

        # ID speichern
        saved_entry_ids.append(entry_id)

        # Begrenze die Anzahl gespeicherter IDs
        if len(saved_entry_ids) > MAX_SAVED_ENTRIES:
            saved_entry_ids = saved_entry_ids[-MAX_SAVED_ENTRIES:]

        # Speichere die aktualisierte Liste
        save_entry_ids(saved_entry_ids)

        # Wartezeit
        time.sleep(60)

    print("Alle neuen Einträge verarbeitet.")


if __name__ == "__main__":
    main()
