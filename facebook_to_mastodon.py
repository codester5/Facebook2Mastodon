import os
import feedparser
from mastodon import Mastodon
import hashlib
import html

def get_feed_entries(feed_url):
    feed = feedparser.parse(feed_url)
    return feed.entries

def generate_hash(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def get_existing_hashes(api, account_id):
    existing_hashes = set()
    posts = api.account_statuses(account_id, limit=100)
    for post in posts:
        if "<!--hash:" in post.content:
            start = post.content.find("<!--hash:") + 9
            end = post.content.find("-->", start)
            if end != -1:
                existing_hashes.add(post.content[start:end])
    return existing_hashes

def post_to_mastodon(api, title, content, image_url, hash_value):
    # Download and upload the image to Mastodon
    if image_url:
        image_path = '/tmp/temp_image.jpg'
        with open(image_path, 'wb') as img_file:
            img_file.write(requests.get(image_url).content)
        media = api.media_post(image_path)
        os.remove(image_path)
        api.status_post(f"{title}\n\n{content}\n<!--hash:{hash_value}-->", media_ids=[media['id']])
    else:
        api.status_post(f"{title}\n\n{content}\n<!--hash:{hash_value}-->")

def main():
    # Anpassbare Variablen
    api_base_url = os.getenv("MASTODON_API_URL")  # Die Basis-URL deiner Mastodon-Instanz
    access_token = os.getenv("MASTODON_ACCESS_TOKEN")  # Dein Access-Token
    feed_url = os.getenv("FEED_URL")  # URL des RSS-Feeds

    # Mastodon API-Client initialisieren
    mastodon = Mastodon(
        access_token=access_token,
        api_base_url=api_base_url
    )

    # Mastodon-Konto-ID abrufen
    account = mastodon.account_verify_credentials()
    account_id = account['id']

    # Bereits gepostete Hashes abrufen
    existing_hashes = get_existing_hashes(mastodon, account_id)

    # Feed-Einträge abrufen
    entries = get_feed_entries(feed_url)

    for entry in entries:
        title = entry.title if 'title' in entry else "(Kein Titel)"
        link = entry.link
        content = html.unescape(entry.summary)
        images = [img['src'] for img in entry.media_content] if 'media_content' in entry else []
        first_image = images[0] if images else None

        # Hash des Inhalts erstellen
        hash_value = generate_hash(title + content + link)

        if hash_value not in existing_hashes:
            # Link entfernen und Posten vorbereiten
            content_cleaned = content.replace(link, "").strip()
            post_to_mastodon(mastodon, title, content_cleaned, first_image, hash_value)

if __name__ == "__main__":
    main()
