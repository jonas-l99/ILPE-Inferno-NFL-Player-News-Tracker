"""
Instagram NFL Monitor - Adam Schefter
Liest RSS-Feed, filtert nach Spieler-Positionen (WR, RB, TE, QB, K),
sendet formatierte Telegram-Nachrichten bei neuen Posts.
"""

import os
import re
import feedparser
import requests
from datetime import datetime
import hashlib

# Konfiguration
POSITIONS = ['WR', 'RB', 'TE', 'QB', 'K']  # Hier kannst du Positionen hinzufügen/entfernen
RSS_FEED_URL = os.environ.get('RSS_FEED_URL')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# Datei zum Speichern bereits verarbeiteter Posts (verhindert Duplikate)
SEEN_POSTS_FILE = 'seen_posts.txt'


def load_seen_posts():
    """Lade bereits verarbeitete Post-IDs aus Datei."""
    if os.path.exists(SEEN_POSTS_FILE):
        with open(SEEN_POSTS_FILE, 'r') as f:
            return set(line.strip() for line in f)
    return set()


def save_seen_posts(seen_posts):
    """Speichere verarbeitete Post-IDs in Datei."""
    with open(SEEN_POSTS_FILE, 'w') as f:
        for post_id in seen_posts:
            f.write(post_id + '\n')


def extract_player_info(caption):
    """
    Extrahiere Spielername, Position und News aus der Caption.
    Erwartetes Format (Adam Schefter typisch):
    - "WR Puka Nacua (ankle) is questionable..."
    - "RB Derrick Henry has signed a 2-year deal..."
    - "TE Mark Andrews is out for Week 5..."
    - "QB Aaron Rodgers (Achilles) is progressing..."
    - "K Justin Tucker signed a 4-year extension..."
    
    Gibt zurück: (player_name, position, news) oder None wenn kein Spieler gefunden
    """
    if not caption:
        return None
    
    # Pattern: Position + Name + (optional: Verletzung/Status) + News
    # Beispiele:
    # "WR Puka Nacua (ankle) is questionable"
    # "RB Derrick Henry has signed"
    # "TE Mark Andrews is out"
    # "QB Aaron Rodgers (Achilles) is progressing"
    # "K Justin Tucker signed"
    
    # Pattern für Position am Anfang oder im Text
    position_pattern = r'\b(' + '|'.join(POSITIONS) + r')\b'
    
    # Suche nach Position im Text
    position_match = re.search(position_pattern, caption, re.IGNORECASE)
    
    if not position_match:
        # Kein Position gefunden → wahrscheinlich kein Spieler-Post
        return None
    
    position = position_match.group(1).upper()
    
    # Versuche, Spielernamen zu extrahieren
    # Typisches Muster: "POSITION NAME (optional: Verletzung) ..."
    # Name ist meist 2-3 Wörter nach der Position
    
    # Pattern: Position gefolgt von 2-3 W örtern (Name) + optional (Verletzung) + Rest
    name_pattern = rf'{position}\s+([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)'
    name_match = re.search(name_pattern, caption, re.IGNORECASE)
    
    if not name_match:
        # Alternative: Suche nach Namen mit Großbuchstaben nach Position
        # Pattern: "POSITION FirstName LastName"
        alt_name_pattern = rf'{position}\s+([A-Z][a-z]+\s+[A-Z][a-z]+)'
        name_match = re.search(alt_name_pattern, caption)
    
    player_name = None
    if name_match:
        player_name = name_match.group(1).strip()
    else:
        # Wenn kein Name gefunden, versuche allgemeinen Namen-Extraktor
        # Suche nach 2 aufeinanderfolgenden W örtern mit Großbuchstaben
        general_name_pattern = r'([A-Z][a-z]+\s+[A-Z][a-z]+)'
        name_matches = re.findall(general_name_pattern, caption)
        
        # Filtere häufige Nicht-Namen-W örter
        exclude_words = {'Adam', 'Schefter', 'ESPN', 'NFL', 'Report', 'Source', 'Team', 'The', 'And', 'But', 'With', 'From', 'For', 'Has', 'Have', 'Is', 'Are', 'Was', 'Were', 'Be', 'Been', 'Being'}
        
        for match in name_matches:
            first_name = match.split()[0]
            if first_name not in exclude_words:
                player_name = match
                break
    
    if not player_name:
        # Immer noch kein Name → wahrscheinlich kein Spieler-Post
        return None
    
    # Extrahiere News-Teil (alles nach dem Namen, aber nicht zu lang)
    # Suche den Teil der Caption nach dem Namen
    name_end_pos = caption.find(player_name)
    if name_end_pos != -1:
        news_start = name_end_pos + len(player_name)
        news_text = caption[news_start:].strip()
        
        # Entferne führende Sonderzeichen/W örter
        news_text = re.sub(r'^[\s\-\(\):,]+', '', news_text)
        
        # Begrenze auf sinnvolle Länge (max 200 Zeichen)
        if len(news_text) > 200:
            # Suche nach Satzende
            sentence_end = news_text[:200].rfind('.')
            if sentence_end != -1:
                news_text = news_text[:sentence_end + 1]
            else:
                news_text = news_text[:200] + '...'
    else:
        news_text = caption[:200] + '...' if len(caption) > 200 else caption
    
    # Entferne überfl üssige Leerzeichen und Zeilenumbr üche
    news_text = ' '.join(news_text.split())
    
    return (player_name, position, news_text)


def send_telegram_message(message):
    """Sende Nachricht an Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Fehler: Telegram Token oder Chat ID fehlt!")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    
    try:
        response = requests.post(url, json=data, timeout=10)
        response.raise_for_status()
        print(f"Telegram-Nachricht gesendet: {message[:50]}...")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Fehler beim Senden der Telegram-Nachricht: {e}")
        return False


def format_message(player_name, position, news, post_link):
    """Formatiere die Nachricht für Telegram."""
    message = f"""🏈 **NFL Update**

- **Spieler**: {player_name}
- **Position**: {position}
- **News**: {news}

🔗 [Quelle]({post_link})
"""
    return message


def main():
    """Hauptfunktion."""
    print(f"Starte Instagram Monitor um {datetime.now().isoformat()}")
    
    # Überpr üfe Konfiguration
    if not RSS_FEED_URL:
        print("Fehler: RSS_FEED_URL nicht gesetzt!")
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Fehler: Telegram Token oder Chat ID nicht gesetzt!")
        return
    
    # Lade bereits verarbeitete Posts
    seen_posts = load_seen_posts()
    print(f"Bereits verarbeitete Posts: {len(seen_posts)}")
    
    # Parse RSS-Feed
    try:
        feed = feedparser.parse(RSS_FEED_URL)
    except Exception as e:
        print(f"Fehler beim Laden des RSS-Feeds: {e}")
        return
    
    print(f"Feed geladen: {len(feed.entries)} Eintr äge")
    
    # Verarbeite Eintr äge (neueste zuerst)
    new_posts_count = 0
    for entry in reversed(feed.entries):  # reversed, um älteste zuerst zu verarbeiten
        # Generiere eindeutige ID f ür den Post
        post_id = hashlib.md5(entry.link.encode()).hexdigest()
        
        # Ü berspringe bereits verarbeitete Posts
        if post_id in seen_posts:
            continue
        
        # Extrahiere Caption/Description
        caption = entry.get('description', '') or entry.get('summary', '') or entry.get('title', '')
        
        # Extrahiere Spieler-Info
        player_info = extract_player_info(caption)
        
        if player_info:
            player_name, position, news = player_info
            
            # Formatieren und senden
            message = format_message(player_name, position, news, entry.link)
            
            if send_telegram_message(message):
                seen_posts.add(post_id)
                new_posts_count += 1
                print(f"Neuer Post verarbeitet: {player_name} ({position})")
        else:
            print(f"Kein Spieler gefunden in Post: {entry.link[:50]}...")
            # Auch Posts ohne Spieler als "gesehen" markieren (verhindert Duplikate)
            seen_posts.add(post_id)
    
    # Speichere verarbeitete Posts
    save_seen_posts(seen_posts)
    
    print(f"Fertig! {new_posts_count} neue Spieler-Posts verarbeitet.")


if __name__ == '__main__':
    main()