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

# Ein Post wird nur gesendet, wenn die Positionsbezeichnung aus der CSV im
# Beitrag vorkommt UND mindestens ein Fantasy-relevanter Auslöser vorkommt.
ALERT_KEYWORDS = [
    r"\bbreaking\b",
    r"\bbreaking news\b",
    r"\binjur(?:y|ies|ed)\b",
    r"\bhurt\b",
    r"\bsuffered\b",
    r"\bdiagnosed\b",
    r"\bmedical\b",
    r"\bconcussion\b",
    r"\bacl\b",
    r"\bmcl\b",
    r"\bachilles\b",
    r"\bhamstring\b",
    r"\bgroin\b",
    r"\bankle\b",
    r"\bknee\b",
    r"\bshoulder\b",
    r"\bwrist\b",
    r"\bfoot\b",
    r"\bback\b",
    r"\bneck\b",
    r"\brib(?:s)?\b",
    r"\bfracture(?:d)?\b",
    r"\btorn\b",
    r"\bsprain(?:ed)?\b",
    r"\bstrain(?:ed)?\b",
    r"\bout\b",
    r"\bquestionable\b",
    r"\bdoubtful\b",
    r"\bactive\b",
    r"\binactive\b",
    r"\bwill not play\b",
    r"\bwon'?t play\b",
    r"\bsidelined\b",
    r"\bmiss(?:es|ed|ing)?\b",
    r"\breturn(?:s|ed|ing)?\b",
    r"\bplaced on (?:the )?(?:injured reserve|ir)\b",
    r"\bdesignated to return\b",
    r"\binjured reserve\b",
    r"\b\bir\b",
    r"\bpup\b",
    r"\bnfi\b",
    r"\bsuspend(?:ed|sion)?\b",
    r"\bsigned\b",
    r"\bsigning\b",
    r"\bagreed(?: to)?\b",
    r"\bcontract\b",
    r"\bextension\b",
    r"\btrade(?:d)?\b",
    r"\btraded\b",
    r"\bacquired\b",
    r"\bsent to\b",
    r"\breleased\b",
    r"\bwaived\b",
    r"\bcut\b",
    r"\bwaiver(?:s)?\b",
    r"\bactivated\b",
    r"\belevated\b",
    r"\bpromoted\b",
]
ALERT_PATTERN = re.compile("|".join(ALERT_KEYWORDS), re.IGNORECASE)


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
                players.append({
                    "name": name,
                    "position": position,
                    "team": team,
                    "normalized": normalize_name(name),
                })
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


def caption_has_position(caption, position):
    # Q kann in Football-Captions auch als Teil anderer Wörter auftauchen;
    # daher ausschließlich als einzelne Abkürzung akzeptieren.
    return bool(re.search(rf"(?<![A-Za-z]){re.escape(position)}(?![A-Za-z])", caption, re.IGNORECASE))


def find_matching_players(caption, players):
    caption_normalized = normalize_name(caption)
    matches = []
    matched_names = set()

    for player in players:
        if not caption_has_position(caption, player["position"]):
            continue
        for alias in player_aliases(player):
            normalized_alias = normalize_name(alias)
            if len(normalized_alias) >= 6 and normalized_alias in caption_normalized:
                if player["name"] not in matched_names:
                    matches.append(player)
                    matched_names.add(player["name"])
                break

    if matches:
        return matches

    words = re.findall(r"[A-Za-zÀ-ÿ]+(?:['.-][A-Za-zÀ-ÿ]+)*", caption)
    candidates = []
    for size in (2, 3, 4):
        for index in range(len(words) - size + 1):
            candidates.append(" ".join(words[index:index + size]))

    normalized_candidates = {normalize_name(candidate): candidate for candidate in candidates}
    for player in players:
        if not caption_has_position(caption, player["position"]):
            continue
        close = difflib.get_close_matches(
            player["normalized"], normalized_candidates.keys(), n=1, cutoff=FUZZY_CUTOFF
        )
        if close and player["name"] not in matched_names:
            matches.append(player)
            matched_names.add(player["name"])

    return matches


def is_fantasy_relevant(caption):
    return bool(ALERT_PATTERN.search(caption))


def first_complete_sentences(text, max_length=900):
    if len(text) <= max_length:
        return text
    shortened = text[:max_length]
    ending = max(shortened.rfind("."), shortened.rfind("!"), shortened.rfind("?"))
    return shortened[:ending + 1] if ending > max_length * 0.45 else shortened.rstrip() + "…"


def escape_html(value):
    return html.escape(str(value), quote=False)


def format_message(player, news, post_link):
    lines = [
        "🏈 <b>NFL Update</b>",
        "",
        f"- <b>Spieler:</b> {escape_html(player['name'])}",
        f"- <b>Position:</b> {escape_html(player['position'])}",
    ]
    if player["team"]:
        lines.append(f"- <b>Team:</b> {escape_html(player['team'])}")
    lines.extend([
        f"- <b>News:</b> {escape_html(news)}",
        "",
        f'🔗 <a href="{escape_html(post_link)}">Quelle</a>',
    ])
    return "\n".join(lines)


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    if not response.ok:
        print(f"Telegram API-Antwort: {response.text}")
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

        # Jeder Beitrag wird gespeichert, auch wenn er keine Meldung auslöst.
        # So wird derselbe allgemeine Post nie erneut geprüft.
        if not is_fantasy_relevant(caption):
            print(f"Nicht fantasy-relevant: {post_link}")
            seen_posts.add(post_id)
            continue

        matches = find_matching_players(caption, players)
        if matches:
            news = first_complete_sentences(caption)
            for player in matches:
                message = format_message(player, news, post_link)
                send_telegram_message(message)
                notifications += 1
                print(f"Telegram gesendet: {player['name']} ({player['position']}, {player['team'] or 'ohne Team'})")
        else:
            print(f"Kein passender Spieler mit Positionskürzel: {post_link}")

        seen_posts.add(post_id)

    save_seen_posts(seen_posts)
    print(f"Fertig! {notifications} Benachrichtigungen gesendet.")


if __name__ == "__main__":
    main()
