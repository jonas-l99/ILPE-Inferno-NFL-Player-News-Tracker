import csv
import difflib
import hashlib
import html
import os
import re
from datetime import datetime

import feedparser
import requests
from bs4 import BeautifulSoup

RSS_FEED_URL = os.environ.get("RSS_FEED_URL")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PLAYERS_FILE = "players.csv"
SEEN_POSTS_FILE = "seen_posts.txt"
FUZZY_CUTOFF = 0.90


def clean_text(value):
    if not value:
        return ""
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_name(name):
    name = name.lower()
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", name)
    return re.sub(r"[^a-z0-9]", "", name)


def load_players():
    if not os.path.exists(PLAYERS_FILE):
        raise FileNotFoundError(f"{PLAYERS_FILE} fehlt im Repository-Hauptordner.")

    players = []
    with open(PLAYERS_FILE, "r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            name = (row.get("name") or "").strip()
            position = (row.get("position") or "").strip().upper()
            team = (row.get("team") or "").strip().upper()
            if name and position:
                players.append(
                    {
                        "name": name,
                        "position": position,
                        "team": team,
                        "normalized": normalize_name(name),
                    }
                )
    return players


def load_seen_posts():
    if not os.path.exists(SEEN_POSTS_FILE):
        return set()
    with open(SEEN_POSTS_FILE, "r", encoding="utf-8") as file:
        return {line.strip() for line in file if line.strip()}


def save_seen_posts(seen_posts):
    with open(SEEN_POSTS_FILE, "w", encoding="utf-8") as file:
        for post_id in sorted(seen_posts):
            file.write(f"{post_id}\n")


def player_aliases(player):
    name = player["name"]
    aliases = {name, re.sub(r"\s+(Jr\.|Sr\.|II|III|IV)$", "", name, flags=re.I)}
    return {alias for alias in aliases if alias}


def find_matching_players(caption, players):
    caption_normalized = normalize_name(caption)
    matches = []
    matched_names = set()

    for player in players:
        found = False
        for alias in player_aliases(player):
            normalized_alias = normalize_name(alias)
            if len(normalized_alias) >= 6 and normalized_alias in caption_normalized:
                found = True
                break

        if found and player["name"] not in matched_names:
            matches.append(player)
            matched_names.add(player["name"])

    if matches:
        return matches

    # Vorsichtiger Fallback für kleine Schreibabweichungen: nur Namen, die als
    # Zwei- bis Vier-Wort-Folge in der Caption erscheinen, werden verglichen.
    words = re.findall(r"[A-Za-zÀ-ÿ]+(?:['.-][A-Za-zÀ-ÿ]+)*", caption)
    candidates = []
    for size in (2, 3, 4):
        for index in range(len(words) - size + 1):
            candidates.append(" ".join(words[index:index + size]))

    normalized_candidates = {normalize_name(candidate): candidate for candidate in candidates}
    all_normalized_names = [player["normalized"] for player in players]

    for player in players:
        close = difflib.get_close_matches(player["normalized"], normalized_candidates.keys(), n=1, cutoff=FUZZY_CUTOFF)
        if close and player["name"] not in matched_names:
            matches.append(player)
            matched_names.add(player["name"])

    return matches


def first_complete_sentences(text, max_length=900):
    if len(text) <= max_length:
        return text

    shortened = text[:max_length]
    sentence_endings = [shortened.rfind("."), shortened.rfind("!"), shortened.rfind("?")]
    ending = max(sentence_endings)
    if ending > max_length * 0.45:
        return shortened[:ending + 1]
    return shortened.rstrip() + "…"


def escape_markdown(value):
    return re.sub(r"([_\[\]()~`>#+\-=|{}.!])", r"\\\1", value)


def format_message(player, news, post_link):
    lines = [
        "🏈 *NFL Update*",
        "",
        f"- *Spieler:* {escape_markdown(player['name'])}",
        f"- *Position:* {escape_markdown(player['position'])}",
    ]
    if player["team"]:
        lines.append(f"- *Team:* {escape_markdown(player['team'])}")
    lines.extend(
        [
            f"- *News:* {escape_markdown(news)}",
            "",
            f"🔗 [Quelle]({post_link})",
        ]
    )
    return "\n".join(lines)


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()


def entry_post_id(entry):
    guid = entry.get("id") or entry.get("guid")
    if guid:
        return str(guid)
    return hashlib.sha256(entry.get("link", "").encode("utf-8")).hexdigest()


def main():
    print(f"Starte Instagram Monitor um {datetime.now().isoformat()}")

    if not RSS_FEED_URL:
        raise ValueError("RSS_FEED_URL fehlt in den GitHub Secrets.")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("Telegram-Secrets fehlen in den GitHub Secrets.")

    players = load_players()
    seen_posts = load_seen_posts()
    print(f"Spieler aus CSV geladen: {len(players)}")
    print(f"Bereits verarbeitete Posts: {len(seen_posts)}")

    feed = feedparser.parse(RSS_FEED_URL)
    if getattr(feed, "bozo", False):
        print(f"RSS-Hinweis: {feed.bozo_exception}")
    print(f"Feed geladen: {len(feed.entries)} Einträge")

    notifications = 0
    for entry in reversed(feed.entries):
        post_id = entry_post_id(entry)
        if post_id in seen_posts:
            continue

        raw_caption = entry.get("description") or entry.get("summary") or entry.get("title") or ""
        caption = clean_text(raw_caption)
        post_link = entry.get("link", "")
        matches = find_matching_players(caption, players)

        if matches:
            news = first_complete_sentences(caption)
            for player in matches:
                message = format_message(player, news, post_link)
                send_telegram_message(message)
                notifications += 1
                print(f"Telegram gesendet: {player['name']} ({player['position']}, {player['team'] or 'ohne Team'})")
        else:
            print(f"Kein CSV-Spieler-Match: {post_link}")

        seen_posts.add(post_id)

    save_seen_posts(seen_posts)
    print(f"Fertig! {notifications} Benachrichtigungen gesendet.")


if __name__ == "__main__":
    main()
