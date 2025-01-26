def scrape_twitter():
    """Scrapt die Twitter-Seite nach Tweets, Medien und Zeitstempeln."""
    driver = get_driver()
    driver.get(twitter_url)
    time.sleep(5)  # Warte, bis die Seite geladen ist

    tweets = []
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_attempts = 0

    while True:
        # Extrahiere den HTML-Quellcode
        soup = BeautifulSoup(driver.page_source, "html.parser")

        for article in soup.find_all("article", {"role": "article"}):
            try:
                # Extrahiere den Text und behalte Emojis und Struktur bei
                text_div = article.find("div", {"data-testid": "tweetText"})
                tweet_text = ""
                if text_div:
                    tweet_html = "".join(str(tag) for tag in text_div.contents)
                    tweet_text = BeautifulSoup(tweet_html, "html.parser").get_text(separator="\n")

                # Extrahiere Medien-URLs
                media_urls = []
                for img in article.find_all("img", {"src": True}):
                    if "twimg.com" in img["src"]:
                        media_urls.append(img["src"])

                for video in article.find_all("video"):
                    source = video.find("source", {"src": True})
                    if source and "twimg.com" in source["src"]:
                        media_urls.append(source["src"])

                # Verwerfe das Profilbild explizit anhand seiner Position oder URL
                if media_urls:
                    profile_image_url = media_urls[0]
                    if "profile_images" in profile_image_url:
                        print(f"DEBUG: Entferne das Profilbild: {profile_image_url}")
                        media_urls = media_urls[1:]

                # Extrahiere den Zeitstempel
                time_tag = article.find("time")
                tweet_time = (
                    datetime.strptime(time_tag["datetime"], "%Y-%m-%dT%H:%M:%S.%fZ")
                    if time_tag and time_tag.get("datetime")
                    else None
                )
                if not tweet_time:
                    continue

                # Duplikate vermeiden
                if any(tweet["time"] == tweet_time for tweet in tweets):
                    continue

                tweets.append({"text": tweet_text, "media": media_urls, "time": tweet_time})
            except Exception as e:
                print(f"ERROR: Fehler beim Verarbeiten eines Tweets: {e}")
                continue

        # Scrolle nach unten
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(5)  # Wartezeit zwischen Scrolls erhöht

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            scroll_attempts += 1
            if scroll_attempts > 4:  # Mehr Scroll-Wiederholungen
                break
        else:
            scroll_attempts = 0
            last_height = new_height

    driver.quit()
    print(f"DEBUG: Insgesamt {len(tweets)} Tweets gefunden.")
    return sorted(tweets, key=lambda x: x["time"])  # Tweets nach Zeit sortieren
