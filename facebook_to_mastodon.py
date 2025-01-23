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

# Gespeicherte IDs werden in einer Datei gehalten
def get_saved_entry_ids():
    try:
        with open("saved_entry_ids.json", "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return []

def save_entry_ids(saved_ids):
    with open("saved_entry_ids.json", "w") as file:
        json.dump(saved_ids, file)

def fetch_feed_entries(feed_url):
    # Parse den RSS-Feed und extrahiere die Einträge
    feed = feedparser.parse(feed_url)
    entries = feed.entries
    return sorted(entries, key=lambda x: parse(x.get('published', '')), reverse=False)  # Sortiere nach Datum (älteste zuerst)

def post_tweet(mastodon, message):
    # Veröffentliche den Tweet auf Mastodon
    message_cut = truncate_text(message)

    retries = 3
    while retries > 0:
        try:
            mastodon.status_post(message_cut, visibility='public')
            break  # Erfolgreich, Schleife beenden
        except mastodon.MastodonAPIError as e:
            if e.status_code == 503:  # Prüfen, ob es sich um einen 503-Fehler handelt
                print(f"ERROR: Mastodon API ist nicht erreichbar: {e}")
                retries -= 1
                if retries > 0:
                    print("Warte 10 Sekunden und versuche es erneut...")
                    time.sleep(10)
                else:
                    print("Maximale Anzahl an Versuchen erreicht. Überspringe diesen Post.")
                    break
            else:
                raise  # Anderen Fehler weiterwerfen

def post_tweet_with_images(mastodon, message, image_urls):
    # Veröffentliche den Beitrag mit einem oder mehreren Bildern auf Mastodon
    message_cut = truncate_text(message)

    # Beschränke die Anzahl der Bilder auf maximal 4
    limited_image_urls = image_urls[:4]

    # Lade die Bilder hoch und erhalte die Media-IDs
    media_ids = upload_images(mastodon, limited_image_urls)

    retries = 3
    while retries > 0:
        try:
            mastodon.status_post(message_cut, media_ids=media_ids, visibility='public')
            break  # Erfolgreich, Schleife beenden
        except mastodon.MastodonAPIError as e:
            if e.status_code == 503:  # Prüfen, ob es sich um einen 503-Fehler handelt
                print(f"ERROR: Mastodon API ist nicht erreichbar: {e}")
                retries -= 1
                if retries > 0:
                    print("Warte 10 Sekunden und versuche es erneut...")
                    time.sleep(10)
                else:
                    print("Maximale Anzahl an Versuchen erreicht. Überspringe diesen Post.")
                    break
            else:
                raise  # Anderen Fehler weiterwerfen

def upload_images(mastodon, image_urls):
    # Lade Bilder hoch und gib die Media-IDs zurück
    media_ids = []
    for image_url in image_urls:
        retries = 3
        while retries > 0:
            try:
                print(f"DEBUG: Bild-URL {image_url}")
                response = requests.get(image_url, timeout=20)  # Erhöhter Timeout
                response.raise_for_status()  # Überprüfe HTTP-Status

                with NamedTemporaryFile(delete=False) as tmp_file:
                    tmp_file.write(response.content)
                    image_path = tmp_file.name

                # Bestimme den MIME-Typ der Datei
                mime_type, _ = mimetypes.guess_type(image_path)
                if not mime_type:
                    mime_type = 'image/jpeg'  # Standard-MIME-Typ, falls nicht erkannt

                # Lade das Bild hoch und erhalte die Media-ID
                with open(image_path, 'rb') as image_file:
                    media_info = mastodon.media_post(
                        image_file, 
                        description="Automatisch generiertes Bild",
                        mime_type=mime_type
                    )
                    media_ids.append(media_info['id'])

                # Temporäre Datei löschen
                os.unlink(image_path)
                break  # Erfolgreich, keine weiteren Versuche nötig
            except Exception as e:
                print(f"ERROR: Bild konnte nicht hochgeladen werden: {e}")
                retries -= 1
                if retries > 0:
                    print("Retrying in 5 seconds...")
                    time.sleep(5)  # Wartezeit vor erneutem Versuch
                else:
                    print("Max retries reached. Skipping image.")
                    break
    return media_ids

def truncate_text(text):
    # Prüfe, ob der Text länger als 500 Zeichen ist
    if len(text) > 500:
        return text[:500]
    else:
        return text

def clean_content_keep_links(content):
    # Entferne Bilder-Tags, behalte Links-Tags
    cleaned_content = re.sub(r'<img\s+[^>]*>', '', content)
    # Entferne alle anderen HTML-Tags
    cleaned_content = re.sub(r'<[^<]+?>', '', cleaned_content).strip()
    # Entferne Zeilenumbrüche und Leerzeichen
    cleaned_content = cleaned_content.replace('\n', ' ').replace('\r', '')
    # Entferne doppelte Leerzeichen
    cleaned_content = ' '.join(cleaned_content.split())
    return cleaned_content

def extract_image_urls_from_summary(summary):
    # Extrahiere alle Bild-URLs aus dem HTML-Inhalt des summary-Felds
    soup = BeautifulSoup(summary, 'html.parser')
    image_urls = []
    for img in soup.find_all('img'):
        if 'src' in img.attrs:
            image_urls.append(img['src'])
    return image_urls

def main(feed_entries):
    mastodon = Mastodon(
        access_token=access_token,
        api_base_url=api_base_url,
        request_timeout=20  # Erhöhter Timeout für Mastodon-API
    )
    
    # Verarbeitete IDs aus Datei laden
    saved_entry_ids = get_saved_entry_ids()

    entry_found = False
    for entry in feed_entries:
        title = entry.get('title', '')
        summary = entry.get('summary', '')
        link = entry.get('link', '')
        published = entry.get('published', '')
        author = entry.get('author', 'Unbekannt')

        # Extrahiere die Zahlen am Ende der URL
        match = re.search(r'\d+$', link)
        if match:
            entry_id = match.group()
        else:
            entry_id = ""

        # Prüfe, ob die entry_id bereits gespeichert ist
        if entry_id in saved_entry_ids:
            continue  # Überspringe bereits verarbeitete Einträge

        entry_found = True

        # Bereinige den Inhalt
        clean_content = clean_content_keep_links(summary)
        clean_content = clean_content.replace("(Feed generated with FetchRSS)", "").strip()

        # Veröffentlichungsdatum formatieren
        if published:
            posted_time_utc = parse(published)
            posted_time_local = posted_time_utc.astimezone()  # Lokale Zeitzone
            posted_time = posted_time_local.strftime("%d.%m.%Y %H:%M")
        else:
            posted_time = "Unbekannt"

        # Bilder extrahieren
        image_urls = extract_image_urls_from_summary(summary)

        # Nachricht erstellen
        message = f"{clean_content} \n\n#Beşiktaş #Football #BJK\n\n{posted_time}"

        # Nachricht posten
        if image_urls:
            post_tweet_with_images(mastodon, message, image_urls)
        else:
            post_tweet(mastodon, message)

        # Füge die entry_id zur Liste der gespeicherten entry_ids hinzu
        saved_entry_ids.append(entry_id)

        # Stelle sicher, dass nur die neuesten 5 Einträge gespeichert werden
        if len(saved_entry_ids) > 5:
            saved_entry_ids = saved_entry_ids[-5:]

        # Wartezeit von 1 Minute zwischen den Posts
        time.sleep(60)

    # Speichere die IDs in die Datei
    save_entry_ids(saved_entry_ids)

    if not entry_found:
        print("Keine neuen Einträge gefunden.")

    print("Erfolgreich beendet: Alle neuen Einträge wurden verarbeitet.")

if __name__ == "__main__":
    feed_entries = fetch_feed_entries(feed_url)
    main(feed_entries)
