"""
Test-Skript: Sendet eine Test-Nachricht an Telegram
Nutze dies, um zu prüfen, ob Telegram korrekt eingerichtet ist.
"""

import os
import requests

# Konfiguration aus Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')


def send_test_message():
    """Sende eine Test-Nachricht."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Fehler: Telegram Token oder Chat ID fehlt!")
        print("Pr üfe die GitHub Secrets:")
        print("  - TELEGRAM_BOT_TOKEN")
        print("  - TELEGRAM_CHAT_ID")
        return False
    
    # Test-Nachricht
    message = """🏈 **NFL Monitor - Test erfolgreich!**

✅ Deine Telegram-Einrichtung funktioniert!

Ab jetzt bekommst du Benachrichtigungen, wenn Adam Schefter Posts über Spieler macht (WR, RB, TE, QB, K).

⏱️ Der Monitor läuft alle 5 Minuten automatisch.

🔧 Setup abgeschlossen!
"""
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    
    try:
        response = requests.post(url, json=data, timeout=10)
        response.raise_for_status()
        
        if response.json().get('ok'):
            print("✅ Test-Nachricht erfolgreich gesendet!")
            print(f"Chat-ID: {TELEGRAM_CHAT_ID}")
            return True
        else:
            print(f"❌ Telegram API Fehler: {response.json()}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Fehler beim Senden: {e}")
        return False


if __name__ == '__main__':
    print("🧪 Starte Telegram-Test...\n")
    success = send_test_message()
    
    if success:
        print("\n✅ Alles funktioniert! Du kannst den Monitor jetzt verwenden.")
    else:
        print("\n❌ Test fehlgeschlagen. Prüfe:")
        print("  1. Hast du dem Bot eine Nachricht geschrieben? (Schritt 2 in SETUP_ANLEITUNG)")
        print("  2. Sind die Secrets korrekt gesetzt? (Schritt 4)")
        print("  3. Ist die Chat-ID korrekt? (von @userinfobot)")