import os
import feedparser
from mastodon import Mastodon
from urllib.parse import urlparse
import hashlib

# Anpassbare Variablen
api_base_url = os.getenv("MASTODON_API_URL")  # Die Basis-URL deiner Mastodon-Instanz
access_token = os.getenv("MASTODON_ACCESS_TOKEN")  # Dein Access-Token
feed_url = os.getenv("FEED_URL")  # URL des RSS-Feeds

# Initialisiere Mastodon-Client
mastodon = Mastodon(
    api_base_url=api_base_url,
    access_token=access_token
)

# Funktion zum Erstellen eines Hashes für den Titel/Link
def generate_post_hash(entry):
    unique_string = entry.get("title", "") + entry.get("link", "")
    return hashlib.sha256(unique_string.encode('utf-8')).hexdigest()

# Funktion zum Abrufen bereits geposteter Inhalte
def get_already_posted():
    posted_hashes = set()
    try:
        for status in mastodon.account_statuses(mastodon.me()["id"], limit=100):
            if "#rss" in status["content"]:
                post_hash = status["content"].split("<!--hash:")[1].split("-->")[0]
                posted_hashes.add(post_hash)
    except Exception as e:
        print(f"Fehler beim Abrufen der geposteten Inhalte: {e}")
    return posted_hashes

# RSS-Feed einlesen
feed = feedparser.parse(feed_url)

# Bereits gepostete Hashes abrufen
already_posted = get_already_posted()

# Neue Beiträge verarbeiten
for entry in feed.entries:
    post_hash = generate_post_hash(entry)

    # Überspringe bereits gepostete Inhalte
    if post_hash in already_posted:
        continue

    # Beitragstext erstellen
    title = entry.get("title", "Kein Titel")
    link = entry.get("link", "#")
    summary = entry.get("summary", "")
    image_tag = ""

    # Suche nach Bildern im Content
    if "content" in entry:
        for content in entry.content:
            if content["type"].startswith("image"):
                image_tag = f"<img src=\"{content['value']}\" />"
                break

    post_content = (
        f"{title}\n\n"
        f"{summary}\n\n"
        f"{link}\n"
        f"{image_tag}\n\n"
        f"<!--hash:{post_hash}--> #rss"
    )

    # Beitrag auf Mastodon veröffentlichen
    try:
        mastodon.status_post(post_content, visibility="public")
        print(f"Beitrag veröffentlicht: {title}")
    except Exception as e:
        print(f"Fehler beim Veröffentlichen des Beitrags: {e}")
