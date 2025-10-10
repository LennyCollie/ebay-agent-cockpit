# utils/vision_openai.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

DMG_THR = float(os.getenv("VISION_DMG_THR", "0.60"))
SUS_THR = float(os.getenv("VISION_SUS_THR", "0.40"))


def _verdict(score: float) -> str:
    if score >= DMG_THR:
        return "damaged"
    if score >= SUS_THR:
        return "suspicious"
    return "ok"


def _call_openai_on_image(url: str) -> Dict[str, Any]:
    """
    Fragt ein Vision-Modell an und erwartet striktes JSON mit {score: 0..1, verdict, notes[]}.
    Wenn OpenAI nicht konfiguriert/installiert ist, wird ein Hinweis zurückgegeben.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "score": 0.0,
            "verdict": "suspicious",
            "notes": ["OPENAI_API_KEY missing"],
            "openai_used": False,
        }

    try:
        from openai import OpenAI
    except Exception as e:
        return {
            "score": 0.0,
            "verdict": "suspicious",
            "notes": [f"openai lib not available: {e}"],
            "openai_used": False,
        }

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")

    # knapper, deterministischer Prompt → JSON erzwingen
    prompt = (
        "You are a damage detector for phone listings. "
        "Look ONLY for cracked/broken screen, deep scratches, shattered glass. "
        'Return compact JSON: {"score":0..1, "verdict":"ok|suspicious|damaged", '
        '"reasons":[...]} where score≈probability of visible damage.'
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }
            ],
        )
        content = resp.choices[0].message.content.strip()
        data = json.loads(content)
        score = float(max(0.0, min(1.0, data.get("score", 0.0))))
        v = data.get("verdict") or _verdict(score)
        reasons = data.get("reasons") or []
        return {"score": score, "verdict": v, "notes": reasons, "openai_used": True}
    except Exception as e:
        # Netz-/Parsing-Fehler => defensiv: suspicious mit Hinweis
        return {
            "score": 0.0,
            "verdict": "suspicious",
            "notes": [f"openai error: {e}"],
            "openai_used": False,
        }


def analyze_image_hybrid(urls: List[str]) -> Dict[str, Any]:
    """
    1) Google schnell scannen
    2) Nur wenn 'suspicious' oder 'damaged' → OpenAI pro Bild zur Verfeinerung
    3) Kombi: max(google_score, openai_scores)
    """
    from utils.vision_google import scan_google  # lazy import, vermeidet Zyklus

    urls = [u for u in urls if u][:2]  # konservativ: 2 Bilder

    google_res = scan_google(urls, max_images=len(urls))
    g_score = float(google_res.get("score", 0.0))
    g_verdict = str(google_res.get("verdict", "ok"))
    details = google_res.get("details", [])

    # wenn Google klar "ok" → OpenAI sparen
    if g_verdict == "ok":
        google_res["openai_used"] = False
        google_res.setdefault("notes", []).append("openai skipped: google verdict ok")
        return google_res

    # sonst: je Bild mit OpenAI prüfen und kombinieren
    o_scores: List[float] = []
    o_details: List[Dict[str, Any]] = []
    for d in details:
        url = d.get("url")
        if not url:
            continue
        o = _call_openai_on_image(url)
        o_scores.append(float(o.get("score", 0.0)))
        o_details.append({"url": url, "openai": o})

    worst = max([g_score] + o_scores) if o_scores else g_score
    final_verdict = _verdict(worst)

    return {
        "score": round(worst, 3),
        "verdict": final_verdict,
        "details": details,
        "openai_details": o_details,
        "openai_used": any(x.get("openai", {}).get("openai_used") for x in o_details),
    }


# Alias für alte Importe / Fallbacks
def scan_openai(urls: List[str]) -> Dict[str, Any]:
    return analyze_image_hybrid(urls)
