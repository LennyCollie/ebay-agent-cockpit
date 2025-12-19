# smart_filters.py - Intelligente Filterung für eBay-Ergebnisse
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ==========================================
# BLACKLIST-KEYWORDS (Automatisch filtern)
# ==========================================

# Allgemeine Zubehör-Keywords
ACCESSORY_KEYWORDS = [
    "hülle",
    "case",
    "cover",
    "etui",
    "tasche",
    "schutzhülle",
    "schutzfolie",
    "displayschutz",
    "panzerglas",
    "panzerfolie",
    "ladekabel",
    "kabel",
    "netzteil",
    "adapter",
    "stecker",
    "charger",
    "kopfhörer",
    "headset",
    "airpods",
    "earpods",
    "ohrhörer",
    "halterung",
    "ständer",
    "halter",
    "mount",
    "dummy",
    "attrappe",
    "display-dummy",
    "fake",
    "verpackung",
    "karton",
    "box",
    "ovp leer",
    "verpackung leer",
    "anleitung",
    "manual",
    "bedienungsanleitung",
    "ersatzteil",
    "platine",
    "motherboard",
    "mainboard",
    "reparatur",
    "defekt",
    "bastler",
    "für teile",
    "teileträger",
    "sim-werkzeug",
    "sim-tool",
    "nadel",
    "aufkleber",
    "sticker",
    "skin",
    "folie",
    "werkzeug",
    "schraubenzieher",
    "öffnungswerkzeug",
]

# Englische Varianten
ACCESSORY_KEYWORDS_EN = [
    "case",
    "cover",
    "shell",
    "pouch",
    "screen protector",
    "tempered glass",
    "film",
    "cable",
    "charger",
    "adapter",
    "cord",
    "earbuds",
    "earphones",
    "headphones",
    "holder",
    "stand",
    "mount",
    "dummy",
    "fake",
    "replica",
    "packaging",
    "box only",
    "empty box",
    "manual",
    "guide",
    "instructions",
    "parts",
    "board",
    "motherboard",
    "repair",
    "broken",
    "for parts",
    "defect",
    "sim tool",
    "ejector",
    "sticker",
    "decal",
    "skin",
]

# Verdächtige Beschreibungen
SUSPICIOUS_KEYWORDS = [
    "nachbau",
    "kopie",
    "imitat",
    "fake",
    "replica",
    "simlock",
    "netlock",
    "gesperrt",
    "locked",
    "icloud locked",
    "ohne garantie",
    "no warranty",
    "as is",
    "wie besehen",
    "wasserschaden",
    "water damage",
    "sturzschaden",
    "nicht getestet",
    "not tested",
    "untested",
    "nur zum anschauen",
    "for display only",
]

# Positive Keywords (sollten BEHALTEN werden)
POSITIVE_KEYWORDS = [
    "neu",
    "new",
    "ovp",
    "sealed",
    "versiegelt",
    "neuwertig",
    "mint",
    "wie neu",
    "like new",
    "unbenutzt",
    "unused",
    "unopened",
    "garantie",
    "warranty",
    "apple care",
    "applecare",
    "rechnung",
    "invoice",
    "kvp",
    "receipt",
]


# ==========================================
# FILTER-KLASSE
# ==========================================


class SmartFilter:
    """Intelligente Filterung von eBay-Ergebnissen"""

    def __init__(self):
        self.accessory_keywords = ACCESSORY_KEYWORDS + ACCESSORY_KEYWORDS_EN
        self.suspicious_keywords = SUSPICIOUS_KEYWORDS
        self.positive_keywords = POSITIVE_KEYWORDS

    def normalize_text(self, text: str) -> str:
        """Normalisiert Text für Vergleich"""
        if not text:
            return ""
        return text.lower().strip()

    def is_accessory(self, title: str, description: str = "") -> Dict:
        """
        Prüft ob Item Zubehör ist

        Returns:
            {
                "is_accessory": bool,
                "matched_keywords": list,
                "confidence": float
            }
        """
        combined = f"{title} {description}".lower()
        matched = []

        for keyword in self.accessory_keywords:
            if keyword in combined:
                matched.append(keyword)

        # Confidence: Je mehr Keywords, desto sicherer
        confidence = min(len(matched) * 0.3, 1.0)

        return {
            "is_accessory": len(matched) > 0,
            "matched_keywords": matched,
            "confidence": confidence,
        }

    def is_suspicious(self, title: str, description: str = "") -> Dict:
        """
        Prüft auf verdächtige Begriffe (Schäden, Locks, etc.)

        Returns:
            {
                "is_suspicious": bool,
                "flags": list,
                "severity": float (0-1)
            }
        """
        combined = f"{title} {description}".lower()
        flags = []

        for keyword in self.suspicious_keywords:
            if keyword in combined:
                flags.append(keyword)

        # Severity
        severity = min(len(flags) * 0.4, 1.0)

        return {"is_suspicious": len(flags) > 0, "flags": flags, "severity": severity}

    def has_positive_indicators(self, title: str, description: str = "") -> Dict:
        """
        Prüft auf positive Qualitäts-Indikatoren

        Returns:
            {
                "has_positive": bool,
                "indicators": list,
                "score": float
            }
        """
        combined = f"{title} {description}".lower()
        indicators = []

        for keyword in self.positive_keywords:
            if keyword in combined:
                indicators.append(keyword)

        score = min(len(indicators) * 0.25, 1.0)

        return {
            "has_positive": len(indicators) > 0,
            "indicators": indicators,
            "score": score,
        }

    def check_title_relevance(self, search_terms: List[str], item_title: str) -> float:
        """
        Prüft wie relevant der Titel zur Suche ist

        Returns:
            Relevanz-Score 0-1 (1 = perfekt relevant)
        """
        title_lower = item_title.lower()

        # Zähle wie viele Suchbegriffe im Titel vorkommen
        matches = 0
        for term in search_terms:
            if term.lower() in title_lower:
                matches += 1

        if not search_terms:
            return 1.0

        relevance = matches / len(search_terms)
        return relevance

    def filter_item(
        self, item: Dict, search_terms: List[str] = None, user_preferences: Dict = None
    ) -> Dict:
        """
        Haupt-Filter-Funktion

        Args:
            item: eBay Item Dict (mit 'title', optional 'description')
            search_terms: Liste der Suchbegriffe des Users
            user_preferences: User-Einstellungen (z.B. {"filter_accessories": True})

        Returns:
            {
                "should_show": bool,
                "filter_reason": str,
                "scores": {...}
            }
        """
        title = item.get("title", "")
        description = item.get("description", "")

        # User Preferences
        if user_preferences is None:
            user_preferences = {
                "filter_accessories": True,
                "filter_suspicious": True,
                "require_relevance": 0.5,  # Min 50% Relevanz
            }

        # 1. Zubehör-Check
        accessory_check = self.is_accessory(title, description)
        if (
            user_preferences.get("filter_accessories")
            and accessory_check["is_accessory"]
        ):
            return {
                "should_show": False,
                "filter_reason": f"Zubehör erkannt: {', '.join(accessory_check['matched_keywords'][:3])}",
                "scores": {"accessory_confidence": accessory_check["confidence"]},
            }

        # 2. Verdächtig-Check
        suspicious_check = self.is_suspicious(title, description)
        if (
            user_preferences.get("filter_suspicious")
            and suspicious_check["is_suspicious"]
        ):
            if suspicious_check["severity"] > 0.5:  # Nur bei hoher Severity filtern
                return {
                    "should_show": False,
                    "filter_reason": f"Verdächtig: {', '.join(suspicious_check['flags'][:2])}",
                    "scores": {"suspicious_severity": suspicious_check["severity"]},
                }

        # 3. Relevanz-Check
        if search_terms:
            relevance = self.check_title_relevance(search_terms, title)
            min_relevance = user_preferences.get("require_relevance", 0.5)

            if relevance < min_relevance:
                return {
                    "should_show": False,
                    "filter_reason": f"Geringe Relevanz ({int(relevance*100)}%)",
                    "scores": {"relevance": relevance},
                }

        # 4. Positive Indikatoren (Bonus)
        positive_check = self.has_positive_indicators(title, description)

        # Item durchlässt alle Filter
        return {
            "should_show": True,
            "filter_reason": None,
            "scores": {
                "accessory_confidence": accessory_check["confidence"],
                "suspicious_severity": suspicious_check["severity"],
                "positive_score": positive_check["score"],
                "relevance": self.check_title_relevance(search_terms or [], title),
            },
            "quality_indicators": (
                positive_check["indicators"] if positive_check["has_positive"] else []
            ),
        }

    def filter_items(
        self,
        items: List[Dict],
        search_terms: List[str] = None,
        user_preferences: Dict = None,
    ) -> Dict:
        """
        Filtert eine Liste von Items

        Returns:
            {
                "filtered_items": [...],  # Items die durchkommen
                "removed_items": [...],   # Gefilterte Items
                "stats": {...}
            }
        """
        filtered = []
        removed = []

        stats = {
            "total": len(items),
            "removed_accessory": 0,
            "removed_suspicious": 0,
            "removed_irrelevant": 0,
            "passed": 0,
        }

        for item in items:
            result = self.filter_item(item, search_terms, user_preferences)

            if result["should_show"]:
                filtered.append(item)
                stats["passed"] += 1
            else:
                removed.append({"item": item, "reason": result["filter_reason"]})

                # Stats
                if "Zubehör" in result["filter_reason"]:
                    stats["removed_accessory"] += 1
                elif "Verdächtig" in result["filter_reason"]:
                    stats["removed_suspicious"] += 1
                elif "Relevanz" in result["filter_reason"]:
                    stats["removed_irrelevant"] += 1

        return {"filtered_items": filtered, "removed_items": removed, "stats": stats}


# ==========================================
# CONVENIENCE FUNCTIONS
# ==========================================

_filter_instance = None


def get_filter() -> SmartFilter:
    """Singleton Pattern"""
    global _filter_instance
    if _filter_instance is None:
        _filter_instance = SmartFilter()
    return _filter_instance


def apply_smart_filters(
    items: List[Dict], search_terms: List[str] = None
) -> List[Dict]:
    """
    Schnell-Funktion: Filtert Items und gibt nur gefilterte zurück

    Usage:
        clean_items = apply_smart_filters(ebay_results, ["iPhone 15 Pro"])
    """
    filter_obj = get_filter()
    result = filter_obj.filter_items(items, search_terms)

    logger.info(
        f"[FILTER] {result['stats']['total']} Items -> "
        f"{result['stats']['passed']} durchgelassen, "
        f"{result['stats']['removed_accessory']} Zubehör, "
        f"{result['stats']['removed_suspicious']} verdächtig, "
        f"{result['stats']['removed_irrelevant']} irrelevant"
    )

    return result["filtered_items"]


# ==========================================
# TEST
# ==========================================


def test_filters():
    """Test der Filter-Funktionen"""
    print("=== Smart Filter Test ===\n")

    test_items = [
        {"title": "iPhone 15 Pro 256GB Neu OVP Versiegelt"},
        {"title": "iPhone 15 Pro Hülle Case Silikon"},
        {"title": "iPhone 15 Pro Ladekabel USB-C"},
        {"title": "iPhone 15 Pro 128GB Simlock defekt"},
        {"title": "iPhone 15 Dummy Attrappe für Auslage"},
        {"title": "Samsung Galaxy S23 Ultra"},
        {"title": "iPhone 15 Pro Max 512GB wie neu"},
    ]

    result = apply_smart_filters(test_items, ["iPhone 15 Pro"])

    print("\n[OK] Durchgelassene Items:")
    for item in result:
        print(f"  - {item['title']}")

    print(f"\n[*] Stats:")
    filter_obj = get_filter()
    full_result = filter_obj.filter_items(test_items, ["iPhone 15 Pro"])
    print(f"  Total: {full_result['stats']['total']}")
    print(f"  Passed: {full_result['stats']['passed']}")
    print(f"  Zubehör: {full_result['stats']['removed_accessory']}")
    print(f"  Verdächtig: {full_result['stats']['removed_suspicious']}")
    print(f"  Irrelevant: {full_result['stats']['removed_irrelevant']}")

    print("\n[!] Gefilterte Items:")
    for removed in full_result["removed_items"]:
        print(f"  - {removed['item']['title']}")
        print(f"    Grund: {removed['reason']}")


if __name__ == "__main__":
    test_filters()
