# routes/ai_helper.py
from __future__ import annotations

import os
import json
from typing import Any, Dict, List

from flask import Blueprint, current_app, jsonify, request, render_template
from flask_login import login_required, current_user

from openai import OpenAI

# Blueprint für deinen KI-Helfer
bp_ai = Blueprint("ai", __name__, url_prefix="/ai")

# OpenAI-Client einmal global anlegen
client = OpenAI(
    api_key=(os.getenv("OPENAI_API_KEY") or "").strip()
)


def _has_api_key() -> bool:
    """Hilfsfunktion: Prüft, ob ein API-Key gesetzt ist."""
    return bool(os.getenv("OPENAI_API_KEY"))


def _get_completion(system_prompt: str, user_prompt: str, model: str = "gpt-4o-mini", temperature: float = 0.7) -> str:
    """Zentrale Funktion für OpenAI-Aufrufe."""
    if not _has_api_key():
        raise ValueError("OPENAI_API_KEY nicht gesetzt.")

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "developer", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return completion.choices[0].message.content.strip()


@bp_ai.route("/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True, "message": "AI helper is alive ✨"})


@bp_ai.route("/test", methods=["GET"])
def ai_test_page():
    return render_template("ai_test.html")


@bp_ai.route("/ask", methods=["POST"])
@login_required
def ask_ai():
    data: Dict[str, Any] = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()

    if not question:
        return jsonify({"ok": False, "error": "Feld 'question' fehlt oder ist leer."}), 400

    system_prompt = (
        "Du bist ein hilfreicher Assistent in einer Web-App namens 'eBay-Agent'. "
        "Du antwortest kurz, klar und auf Deutsch. "
        "Wenn der Nutzer nach Formulierungen für Titel/Anzeigen fragt, "
        "liefere direkt optimierte Vorschläge."
    )

    try:
        answer = _get_completion(system_prompt, f"Nutzer-ID: {current_user.id}. Frage: {question}")
        return jsonify({"ok": True, "answer": answer})
    except Exception as e:
        current_app.logger.error(f"[AI] Fehler bei OpenAI-Aufruf: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp_ai.route("/suggest-terms", methods=["POST"])
@login_required
def suggest_terms():
    """Schlägt optimierte eBay-Suchbegriffe vor."""
    data = request.get_json(silent=True) or {}
    base_term = data.get("base_term", "")
    description = data.get("description", "")

    if not base_term and not description:
        return jsonify({"ok": False, "error": "Kein Suchbegriff oder Beschreibung angegeben."}), 400

    system_prompt = (
        "Du bist Experte für eBay-Suchbegriffe. "
        "Erzeuge bis zu 3 kurze Suchbegriffe (max. 4 Wörter) für die eBay-Suche. "
        "Antworte NUR als JSON-Array von Strings, z.B. [\"iphone 12 64gb\",\"iphone 12 gebraucht\"]."
    )
    user_prompt = f"Grundlage: {description if description else base_term}"

    try:
        answer = _get_completion(system_prompt, user_prompt, temperature=0.5)
        # Säubere Antwort von Markdown-Code-Blöcken falls vorhanden
        if answer.startswith("```"):
            answer = answer.strip("`").replace("json\n", "", 1).strip()
        
        return jsonify({"ok": True, "suggestions": json.loads(answer)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp_ai.route("/suggest-strategy", methods=["POST"])
@login_required
def suggest_strategy():
    """Schlägt eine komplette Suchstrategie (Begriffe + Filter) vor."""
    data = request.get_json(silent=True) or {}
    terms = data.get("terms", [])
    description = data.get("description", "")

    system_prompt = """Du bist Experte für eBay-Suchstrategien.
Analysiere die Informationen und schlage eine passende Suchstrategie vor.
Antworte NUR als JSON im Format:
{
  "keywords": ["..."],
  "price_min": 0 oder null,
  "price_max": 0 oder null,
  "conditions": ["NEW","USED","CERTIFIED_REFURBISHED"],
  "listing_type": "buy_it_now" oder "auction" oder "all",
  "country": "DE" oder "AT" oder "CH" oder "US" oder "GB"
}"""
    user_prompt = f"Bestehende Begriffe: {', '.join(terms)}\nBeschreibung: {description}"

    try:
        answer = _get_completion(system_prompt, user_prompt, temperature=0.3)
        if answer.startswith("```"):
            answer = answer.strip("`").replace("json\n", "", 1).strip()
        
        return jsonify({"ok": True, "strategy": json.loads(answer)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp_ai.route("/generate-alert", methods=["POST"])
@login_required
def generate_alert():
    """Generiert einen kompletten Alert-Vorschlag."""
    data = request.get_json(silent=True) or {}
    description = data.get("description", "")
    base_term = data.get("base_term", "")

    system_prompt = """Du bist Experte für eBay-Suchalerts und Preis-Sniping.
Erzeuge einen konkreten Alert-Vorschlag, der sich auf das Hauptprodukt konzentriert und KEIN Zubehör/Reparatur enthält.
Antworte NUR als JSON im Format:
{
  "keywords": ["..."],
  "price_min": 0 oder null,
  "price_max": 0 oder null,
  "conditions": ["NEW","USED","CERTIFIED_REFURBISHED"],
  "listing_type": "buy_it_now" oder "auction" oder "all",
  "country": "DE" oder "AT" oder "CH" oder "US" oder "GB",
  "source": "ebay" oder "kleinanzeigen" oder "both",
  "channels": ["email","telegram"]
}"""
    user_prompt = f"Beschreibung: {description}\nBasis-Begriff: {base_term}"

    try:
        answer = _get_completion(system_prompt, user_prompt, temperature=0.3)
        if answer.startswith("```"):
            answer = answer.strip("`").replace("json\n", "", 1).strip()
        
        return jsonify({"ok": True, "alert": json.loads(answer)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
