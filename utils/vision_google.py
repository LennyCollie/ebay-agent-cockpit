# utils/vision_google.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from google.cloud import vision
from google.oauth2 import service_account

DAMAGE_KEYWORDS = {
    "crack",
    "cracked",
    "fracture",
    "broken",
    "shatter",
    "shattered",
    "scratch",
    "scratched",
    "scuff",
    "dent",
    "damage",
    "damaged",
    "chip",
    "spiderweb",
}
PHONE_KEYWORDS = {"mobile phone", "cellphone", "smartphone", "iphone", "android"}

_client = None


def _client_from_env() -> vision.ImageAnnotatorClient:
    global _client
    if _client:
        return _client
    creds_json = os.getenv("GCP_CREDENTIALS_JSON")
    if not creds_json:
        raise RuntimeError("GCP_CREDENTIALS_JSON missing")
    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(info)
    _client = vision.ImageAnnotatorClient(credentials=creds)
    return _client


def scan_google(urls: List[str], *, max_images: int = 2) -> Dict[str, Any]:
    """Ruft Label Detection + Object Localization auf und liefert {score, verdict, details[]}"""
    urls = [u for u in urls if u][:max_images]
    if not urls:
        return {"score": 0.0, "verdict": "unchecked", "details": []}

    client = _client_from_env()
    requests = []
    for u in urls:
        img = vision.Image()
        img.source.image_uri = u  # öffentliche HTTP/HTTPS-URL
        requests.append(
            vision.AnnotateImageRequest(
                image=img,
                features=[
                    vision.Feature(
                        type_=vision.Feature.Type.LABEL_DETECTION, max_results=15
                    ),
                    vision.Feature(
                        type_=vision.Feature.Type.OBJECT_LOCALIZATION, max_results=10
                    ),
                ],
            )
        )
    batch = client.batch_annotate_images(requests=requests)
    worst = 0.0
    verdict = "ok"
    details = []

    for u, resp in zip(urls, batch.responses):
        labels = [l.description.lower() for l in resp.label_annotations or []]
        objects = [o.name.lower() for o in resp.localized_object_annotations or []]
        # Heuristik: Schaden-Score aus Labels + Phone-Kontext
        has_phone = any(k in objects or k in " ".join(labels) for k in PHONE_KEYWORDS)
        dmg_hits = [w for w in DAMAGE_KEYWORDS if any(w in lab for lab in labels)]
        score = 0.0
        if dmg_hits:
            score += min(1.0, 0.6 + 0.1 * len(dmg_hits))  # klare Schadenslabels
        if has_phone:
            score += 0.15  # Kontext: es ist wirklich ein Phone
        score = min(1.0, score)
        local_verdict = "ok"
        if score >= 0.60:
            local_verdict = "damaged"
        elif score >= 0.40:
            local_verdict = "suspicious"

        details.append(
            {
                "url": u,
                "score": round(score, 3),
                "verdict": local_verdict,
                "labels": labels[:8],
                "objects": objects[:8],
            }
        )
        worst = max(worst, score)
        if local_verdict == "damaged":
            verdict = "damaged"
        elif local_verdict == "suspicious" and verdict != "damaged":
            verdict = "suspicious"

    return {"score": round(worst, 3), "verdict": verdict, "details": details}
