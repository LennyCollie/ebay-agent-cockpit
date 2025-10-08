# utils/vision_router.py
import os
from typing import Dict, List

from utils.image_damage import analyze_images as opencv_scan
from utils.vision_google import scan_google as _scan_google


def scan_opencv(urls: List[str]) -> Dict:  # gratis
    return opencv_scan(urls)


def scan_google(urls: List[str]) -> Dict:
    # Pseudocode: rufe Vision API (Label/Object Localization) auf,
    # mappe Resultate -> {score, verdict}
    ...


def scan_openai(urls: List[str]) -> Dict:
    # Pseudocode: sende 1–2 Bilder + kurze Instruktion an Vision-Modell,
    # mappe Antwort -> {score, verdict}
    ...


def hybrid_scan(urls: List[str], only_on_suspicious=True) -> Dict:
    base = scan_opencv(urls)
    if base["verdict"] == "ok" and only_on_suspicious:
        return base
    # zuerst günstig: Google
    g = scan_google(urls[:2])
    if g.get("verdict") in ("damaged", "ok"):
        return g
    # Premium-Fallback:
    return scan_openai(urls[:1])

    # utils/vision_router.py (ergänzen)


def hybrid_scan(urls, only_on_suspicious=True):
    from utils.image_damage import analyze_images as scan_opencv

    base = scan_opencv(urls)
    if os.getenv("ONLY_ON_SUSPICIOUS", "1") == "1" and base["verdict"] == "ok":
        return base
    if os.getenv("GOOGLE_VISION_ENABLED", "0") == "1":
        try:
            return _scan_google(
                urls, max_images=int(os.getenv("MAX_IMAGES_PER_ITEM", "2"))
            )
        except Exception as e:
            base.setdefault("errors", []).append(f"google:{e}")
            return base
    return base
