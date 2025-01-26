import requests
from bs4 import BeautifulSoup
from mastodon import Mastodon
from tempfile import NamedTemporaryFile
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
import os
import mimetypes
import time
from datetime import datetime
import re
import shutil

# Mastodon-Konfigurationsvariablen
api_base_url = os.getenv("MASTODON_API_URL")
access_token = os.getenv("MASTODON_ACCESS_TOKEN")
hashtags = os.getenv("HASHTAGS", "#Besiktas")  # Standard-Hashtags

# Twitter-URL aus Umgebungsvariablen
twitter_url = os.getenv("TWITTER_URL")  # Muss gesetzt werden

# Zeichenlimit pro Tröt
TROET_LIMIT = 500


def get_driver():
    """Erstelle und konfiguriere den Firefox WebDriver."""
    try:
        options = Options()
        options.headless = True  # Headless-Modus aktivieren

        # Dynamisch den Pfad zu GeckoDriver finden
        geckodriver_path = shutil.which("geckodriver")
        if not geckodriver_path:
            raise FileNotFoundError("GeckoDriver nicht im PATH gefunden.")
        print(f"DEBUG: Verwende GeckoDriver von: {geckodriver_path}")

        # WebDriver initialisieren
        service = Service(geckodriver_path)
        print("DEBUG: Initialisiere Firefox WebDriver...")
        driver = webdriver.Firefox(service=service, options=options)
        print("DEBUG: Firefox WebDriver erfolgreich initialisiert.")
        return driver
    except Exception as e:
        print(f"ERROR: WebDriver-Initialisierung fehlgeschlagen: {e}")
        raise


def scrape_twitter():
    """Scrapt die Twitter-Seite nach Tweets, Medien und Zeitstempeln."""
    if not twitter_url:
        raise ValueError("FEHLER: TWITTER_URL ist nicht gesetzt.")
    
    print(f"DEBUG: Scraping Twitter-Seite mit Firefox: {twitter_url}")
    try:
        driver = get_driver()
        driver.get(twitter_url)
        time.sleep(5)  # Warte, bis die Seite vollständig geladen ist

        # Extrahiere den HTML-Quellcode
        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()

        tweets = []
        for article in soup.find_all("article", {"role": "article"}):
            try:
                # Extrahiere den Text
                text_div = article.find("div", {"data-testid": "tweetText"})
                tweet_text = text_div.get_text(strip=True) if text_div else "Kein Text gefunden"

                # Extrahiere Medien-URLs (Bilder und Videos)
                media_urls = []
                for img in article.find_all("img", {"alt": "Bild"}):
                    media_urls.append(img["src"])

                for video in article.find_all("video"):
                    source = video.find("source")
                    if source and source.get("src"):
                        media_urls.append(source["src"])

                # Extrahiere den Zeitstempel
                time_tag = article.find("time")
                tweet_time = (
                    datetime.strptime(time_tag["datetime"], "%Y-%m-%dT%H:%M:%S.%fZ")
                    if time_tag and time_tag.get("datetime")
                    else datetime.now()
                )

                # Füge die Daten in die Tweets-Liste hinzu
                tweets.append({"text": tweet_text, "media": media_urls, "time": tweet_time})
                print(f"DEBUG: Gefundener Tweet: {tweet_text[:50]}... mit {len(media_urls)} Medien, Zeitstempel: {tweet_time}")
            except Exception as e:
                print(f"ERROR: Fehler beim Verarbeiten eines Tweets: {e}")
                continue

        print(f"DEBUG: Insgesamt {len(tweets)} Tweets gefunden.")
        return tweets
    except Exception as e:
        print(f"ERROR: Fehler beim Scraping der Twitter-Seite: {e}")
        return []


def main():
    mastodon = Mastodon(access_token=access_token, api_base_url=api_base_url)

    tweets = scrape_twitter()
    for tweet in tweets:
        print(f"DEBUG: Verarbeite Tweet mit Zeitstempel: {tweet['time']}")
        print(f"DEBUG: Poste auf Mastodon: {tweet['text']}")
        try:
            mastodon.status_post(tweet['text'], visibility="public")
        except Exception as e:
            print(f"ERROR: Fehler beim Posten des Tweets: {e}")


if __name__ == "__main__":
    main()
