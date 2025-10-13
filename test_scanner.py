# test_scanner.py
import os

from dotenv import load_dotenv

# Lade ENV
load_dotenv(".env.local")
load_dotenv()

print("=== VISION SCANNER TEST ===\n")

# 1. Prüfe Konfiguration
print("1. Konfiguration:")
creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "nicht gesetzt")
vision_enabled = os.getenv("VISION_ANALYSIS_ENABLED", "0")
print(f"   GOOGLE_APPLICATION_CREDENTIALS: {creds_path}")
print(f"   VISION_ENABLED: {vision_enabled}")

# 2. Teste Image Analyzer
try:
    from image_analyzer import get_analyzer

    analyzer = get_analyzer()
    print(f"\n2. Image Analyzer:")
    print(f"   Verfügbar: {analyzer.is_available()}")

    if not analyzer.is_available():
        print("\n❌ FEHLER: Vision API nicht verfügbar!")
        print("   Mögliche Gründe:")
        print("   - JSON-Key-Datei existiert nicht")
        print("   - GOOGLE_APPLICATION_CREDENTIALS falsch")
        print("   - google-cloud-vision nicht installiert")
        exit(1)

    # 3. Teste mit echtem eBay-Bild
    print(f"\n3. Teste mit eBay-Bild:")

    # ÄNDERE DIESE URL zu einem echten eBay-Bild!
    test_url = "https://i.ebayimg.com/images/g/s2sAAeSwMf1oy8at/s-l1600.jpg"

    print(f"   URL: {test_url}")

    result = analyzer.analyze_image(test_url)

    print(f"\n4. Ergebnis:")
    print(f"   Schaden erkannt: {result.get('has_damage', False)}")
    print(f"   Confidence: {result.get('confidence', 0):.2%}")
    print(f"   Beschreibung: {result.get('description', 'N/A')}")

    labels = result.get("labels", [])
    if labels:
        print(f"   Labels: {', '.join(labels[:5])}")

    damages = result.get("damage_indicators", [])
    if damages:
        print(f"\n   Schaden-Indikatoren gefunden:")
        for damage in damages:
            print(f"   - {damage['keyword']} (Confidence: {damage['confidence']:.1%})")

    print("\n✅ TEST ABGESCHLOSSEN!")

except ImportError as e:
    print(f"\n❌ IMPORT-FEHLER: {e}")
    print("   Prüfe ob image_analyzer.py existiert")
    print("   Führe aus: pip install google-cloud-vision")

except Exception as e:
    print(f"\n❌ FEHLER: {e}")
    import traceback

    traceback.print_exc()
