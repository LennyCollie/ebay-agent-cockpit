# image_analyzer.py - Google Vision API für Schadenerkennung
import logging
import os
from io import BytesIO
from typing import Dict, Optional

import requests

try:
    from google.cloud import vision
    from google.oauth2 import service_account

    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False
    print(
        "[VISION] google-cloud-vision nicht installiert. Installiere mit: pip install google-cloud-vision"
    )

logger = logging.getLogger(__name__)

# Konfiguration aus ENV
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
VISION_ENABLED = os.getenv("VISION_ANALYSIS_ENABLED", "0") == "1"
MAX_IMAGES_PER_ITEM = int(os.getenv("VISION_MAX_IMAGES", "3"))

# Damage-Keywords (Deutsch + Englisch)
DAMAGE_KEYWORDS = [
    # Englisch
    "crack",
    "cracked",
    "broken",
    "damaged",
    "scratch",
    "scratched",
    "dent",
    "dented",
    "shattered",
    "chipped",
    "worn",
    "defect",
    "defective",
    "bent",
    "cracked screen",
    "broken glass",
    "water damage",
    # Deutsch
    "riss",
    "gerissen",
    "kaputt",
    "beschädigt",
    "kratzer",
    "zerkratzt",
    "delle",
    "verbogen",
    "zerbrochen",
    "defekt",
    "abgenutzt",
    "schaden",
    "displaybruch",
    "glasbruch",
    "wasserschaden",
]

# Positive Keywords (kein Schaden)
GOOD_KEYWORDS = [
    "new",
    "mint",
    "pristine",
    "perfect",
    "excellent",
    "flawless",
    "neu",
    "neuwertig",
    "perfekt",
    "makellos",
    "einwandfrei",
]


class VisionAnalyzer:
    """Google Vision API Wrapper für Schadenerkennung"""

    def __init__(self):
        self.client = None
        self.enabled = VISION_ENABLED and VISION_AVAILABLE

        if self.enabled:
            try:
                if GOOGLE_CREDENTIALS_PATH and os.path.exists(GOOGLE_CREDENTIALS_PATH):
                    credentials = service_account.Credentials.from_service_account_file(
                        GOOGLE_CREDENTIALS_PATH
                    )
                    self.client = vision.ImageAnnotatorClient(credentials=credentials)
                else:
                    # Versuche Default Credentials (für Cloud-Umgebungen)
                    self.client = vision.ImageAnnotatorClient()

                logger.info("✅ Google Vision API initialisiert")
            except Exception as e:
                logger.error(f"❌ Vision API Init Fehler: {e}")
                self.enabled = False

    def is_available(self) -> bool:
        """Prüft ob Vision API verfügbar ist"""
        return self.enabled and self.client is not None

    def analyze_image(self, image_url: str) -> Dict:
        """
        Analysiert ein Bild auf Schäden

        Args:
            image_url: URL zum Bild

        Returns:
            {
                "has_damage": bool,
                "confidence": float (0-1),
                "labels": list,
                "damage_indicators": list,
                "description": str
            }
        """
        if not self.is_available():
            return {
                "has_damage": False,
                "confidence": 0.0,
                "labels": [],
                "damage_indicators": [],
                "description": "Vision API nicht verfügbar",
                "error": "API not configured",
            }

        try:
            # Bild von URL laden
            image = vision.Image()
            image.source.image_uri = image_url

            # Label Detection (erkennt Objekte/Zustände)
            response = self.client.label_detection(image=image)

            if response.error.message:
                raise Exception(response.error.message)

            labels = response.label_annotations

            # Labels extrahieren
            label_texts = [label.description.lower() for label in labels]
            label_scores = {label.description.lower(): label.score for label in labels}

            # Schaden-Keywords suchen
            damage_found = []
            good_indicators = []

            for label in label_texts:
                # Check Damage
                for damage_kw in DAMAGE_KEYWORDS:
                    if damage_kw in label:
                        damage_found.append(
                            {
                                "keyword": damage_kw,
                                "label": label,
                                "confidence": label_scores.get(label, 0.0),
                            }
                        )

                # Check Good Condition
                for good_kw in GOOD_KEYWORDS:
                    if good_kw in label:
                        good_indicators.append(label)

            # Entscheidung
            has_damage = len(damage_found) > 0

            # Wenn "good" indicators stark sind, override damage
            if len(good_indicators) > len(damage_found):
                has_damage = False

            # Confidence berechnen
            if damage_found:
                avg_confidence = sum(d["confidence"] for d in damage_found) / len(
                    damage_found
                )
            else:
                avg_confidence = 0.0

            # Beschreibung generieren
            if has_damage:
                damages = ", ".join(set(d["keyword"] for d in damage_found))
                description = f"Mögliche Schäden erkannt: {damages}"
            else:
                description = "Keine offensichtlichen Schäden erkannt"

            return {
                "has_damage": has_damage,
                "confidence": avg_confidence,
                "labels": label_texts[:10],  # Top 10 Labels
                "damage_indicators": damage_found,
                "description": description,
            }

        except Exception as e:
            logger.error(f"❌ Vision API Fehler für {image_url}: {e}")
            return {
                "has_damage": False,
                "confidence": 0.0,
                "labels": [],
                "damage_indicators": [],
                "description": f"Analyse fehlgeschlagen: {str(e)}",
                "error": str(e),
            }

    def analyze_item_images(self, item: Dict, max_images: int = None) -> Dict:
        """
        Analysiert alle Bilder eines Items

        Args:
            item: Dict mit 'img' (Haupt-Bild) und optional 'images' (Liste)
            max_images: Maximale Anzahl zu analysierender Bilder

        Returns:
            {
                "has_damage": bool,
                "overall_confidence": float,
                "images_analyzed": int,
                "damages_found": int,
                "details": [...]
            }
        """
        if max_images is None:
            max_images = MAX_IMAGES_PER_ITEM

        # Sammle alle Bild-URLs
        image_urls = []

        # Haupt-Bild
        main_img = item.get("img") or item.get("image_url")
        if main_img:
            image_urls.append(main_img)

        # Weitere Bilder (falls vorhanden)
        additional = item.get("images") or item.get("additional_images") or []
        image_urls.extend(additional[: max_images - 1])

        # Limitiere auf max_images
        image_urls = image_urls[:max_images]

        if not image_urls:
            return {
                "has_damage": False,
                "overall_confidence": 0.0,
                "images_analyzed": 0,
                "damages_found": 0,
                "details": [],
                "reason": "Keine Bilder vorhanden",
            }

        # Analysiere jedes Bild
        results = []
        damages_found = 0

        for idx, url in enumerate(image_urls):
            result = self.analyze_image(url)
            result["image_index"] = idx
            results.append(result)

            if result["has_damage"]:
                damages_found += 1

        # Overall Decision
        # Wenn mehr als 50% der Bilder Schäden zeigen → has_damage = True
        has_damage = damages_found > (len(results) / 2)

        # Average Confidence
        confidences = [r["confidence"] for r in results if r["confidence"] > 0]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return {
            "has_damage": has_damage,
            "overall_confidence": avg_confidence,
            "images_analyzed": len(results),
            "damages_found": damages_found,
            "details": results,
            "summary": f"{damages_found}/{len(results)} Bilder mit möglichen Schäden",
        }


# Globale Instanz
_analyzer = None


def get_analyzer() -> VisionAnalyzer:
    """Singleton-Pattern für Analyzer"""
    global _analyzer
    if _analyzer is None:
        _analyzer = VisionAnalyzer()
    return _analyzer


# Convenience Functions
def check_item_damage(item: Dict) -> Dict:
    """
    Hauptfunktion: Prüft Item auf Schäden

    Usage:
        result = check_item_damage(ebay_item)
        if result["has_damage"]:
            print(f"Schaden gefunden: {result['summary']}")
    """
    analyzer = get_analyzer()

    if not analyzer.is_available():
        return {
            "has_damage": False,
            "enabled": False,
            "reason": "Vision API nicht aktiviert",
        }

    return analyzer.analyze_item_images(item)


# Test-Funktion
def test_vision_api():
    """Test ob Vision API funktioniert"""
    analyzer = get_analyzer()

    print("=== Google Vision API Test ===")
    print(f"Verfügbar: {analyzer.is_available()}")
    print(f"Credentials: {GOOGLE_CREDENTIALS_PATH}")
    print(f"Enabled: {VISION_ENABLED}")

    if analyzer.is_available():
        # Test mit Beispiel-Bild
        test_url = "https://i.ebayimg.com/images/g/test/s-l500.jpg"
        print(f"\nTest-Analyse: {test_url}")

        result = analyzer.analyze_image(test_url)
        print(f"Ergebnis: {result}")
    else:
        print("\n❌ Vision API nicht verfügbar")
        print("Prüfe:")
        print("1. GOOGLE_APPLICATION_CREDENTIALS gesetzt?")
        print("2. google-cloud-vision installiert?")
        print("3. JSON-Key-Datei vorhanden?")


if __name__ == "__main__":
    test_vision_api()
