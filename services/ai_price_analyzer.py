"""
🤖 KI-PREISANALYSE mit Claude API
Analysiert Preise und gibt Empfehlungen
"""
import os
import logging
from typing import List, Dict, Optional
import statistics

log = logging.getLogger(__name__)


def analyze_prices_with_ai(
    results: List[Dict],
    query: str,
    user_budget: Optional[float] = None
) -> Dict:
    """
    🤖 Analysiert Suchergebnisse mit KI

    Features:
    - Durchschnittspreis berechnen
    - Schnäppchen erkennen (< -20% vom Durchschnitt)
    - Überteuert warnen (> +30% vom Durchschnitt)
    - Beste Zeit zum Kaufen
    - KI-Empfehlungen via Claude API

    Args:
        results: Suchergebnisse
        query: Suchbegriff
        user_budget: Budget des Users

    Returns:
        Dict mit Analyse-Ergebnissen
    """
    if not results:
        return {'error': 'Keine Ergebnisse zum Analysieren'}

    # Basis-Statistiken
    prices = [r['price'] for r in results if r.get('price')]

    if not prices:
        return {'error': 'Keine Preise gefunden'}

    analysis = {
        'total_items': len(results),
        'items_with_price': len(prices),
        'avg_price': statistics.mean(prices),
        'median_price': statistics.median(prices),
        'min_price': min(prices),
        'max_price': max(prices),
        'std_dev': statistics.stdev(prices) if len(prices) > 1 else 0,
        'price_range': max(prices) - min(prices),
    }

    # Kategorisierung
    analysis['bargains'] = _find_bargains(results, analysis['avg_price'])
    analysis['overpriced'] = _find_overpriced(results, analysis['avg_price'])
    analysis['fair_price'] = _find_fair_priced(results, analysis['avg_price'])

    # Marketplace Vergleich
    analysis['by_marketplace'] = _analyze_by_marketplace(results)

    # Budget-Check
    if user_budget:
        analysis['within_budget'] = len([p for p in prices if p <= user_budget])
        analysis['budget_percentage'] = (analysis['within_budget'] / len(prices)) * 100

    # Empfohlener Preis-Range
    analysis['recommended_range'] = {
        'min': analysis['avg_price'] * 0.85,  # -15%
        'max': analysis['avg_price'] * 1.10   # +10%
    }

    # KI-Analyse (optional, wenn Claude API Key vorhanden)
    if os.getenv('ANTHROPIC_API_KEY'):
        analysis['ai_insights'] = _get_ai_insights(query, analysis, results[:5])

    return analysis


def _find_bargains(results: List[Dict], avg_price: float, threshold: float = 0.80) -> List[Dict]:
    """Findet Schnäppchen (< 80% des Durchschnitts)"""
    bargains = []
    for item in results:
        if item.get('price') and item['price'] < avg_price * threshold:
            item['discount_percentage'] = ((avg_price - item['price']) / avg_price) * 100
            bargains.append(item)
    return sorted(bargains, key=lambda x: x['price'])


def _find_overpriced(results: List[Dict], avg_price: float, threshold: float = 1.30) -> List[Dict]:
    """Findet überteuerte Items (> 130% des Durchschnitts)"""
    overpriced = []
    for item in results:
        if item.get('price') and item['price'] > avg_price * threshold:
            item['overprice_percentage'] = ((item['price'] - avg_price) / avg_price) * 100
            overpriced.append(item)
    return sorted(overpriced, key=lambda x: x['price'], reverse=True)


def _find_fair_priced(results: List[Dict], avg_price: float) -> List[Dict]:
    """Findet fair-preiste Items (80-120% des Durchschnitts)"""
    fair = []
    for item in results:
        if item.get('price'):
            ratio = item['price'] / avg_price
            if 0.80 <= ratio <= 1.20:
                fair.append(item)
    return sorted(fair, key=lambda x: x['price'])


def _analyze_by_marketplace(results: List[Dict]) -> Dict:
    """Analysiert Preise pro Marketplace"""
    by_market = {}

    for item in results:
        if not item.get('price'):
            continue

        source = item.get('source', 'unknown')
        if source not in by_market:
            by_market[source] = {
                'prices': [],
                'count': 0
            }

        by_market[source]['prices'].append(item['price'])
        by_market[source]['count'] += 1

    # Statistiken berechnen
    for source, data in by_market.items():
        prices = data['prices']
        data['avg_price'] = statistics.mean(prices)
        data['min_price'] = min(prices)
        data['max_price'] = max(prices)
        data['median_price'] = statistics.median(prices)
        del data['prices']  # Nicht zurückgeben (zu groß)

    # Sortiere nach günstigstem Durchschnitt
    sorted_markets = sorted(
        by_market.items(),
        key=lambda x: x[1]['avg_price']
    )

    return dict(sorted_markets)


def _get_ai_insights(query: str, analysis: Dict, sample_items: List[Dict]) -> Dict:
    """
    🤖 Holt KI-Insights von Claude API

    Benötigt: ANTHROPIC_API_KEY Environment Variable
    """
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

        # Erstelle Prompt
        prompt = f"""Analysiere diese Marktdaten für "{query}":

[*] STATISTIKEN:
- Durchschnittspreis: {analysis['avg_price']:.2f}€
- Median: {analysis['median_price']:.2f}€
- Spanne: {analysis['min_price']:.2f}€ - {analysis['max_price']:.2f}€
- Anzahl Angebote: {analysis['total_items']}

🏪 MARKETPLACE VERGLEICH:
{_format_marketplace_comparison(analysis['by_marketplace'])}

💎 BEISPIEL-ANGEBOTE:
{_format_sample_items(sample_items)}

Bitte gib eine kurze, prägnante Analyse (max 150 Wörter):
1. Ist der Markt gerade günstig oder teuer?
2. Welche Marketplace bietet beste Preise?
3. Gibt es auffällige Schnäppchen?
4. Empfehlung: Jetzt kaufen oder warten?
"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        insights_text = message.content[0].text

        return {
            'text': insights_text,
            'model': 'claude-sonnet-4',
            'generated_at': 'now'
        }

    except Exception as e:
        log.warning(f"AI Insights failed: {e}")
        return {
            'text': 'KI-Analyse nicht verfügbar. ANTHROPIC_API_KEY fehlt oder ungültig.',
            'error': str(e)
        }


def _format_marketplace_comparison(by_marketplace: Dict) -> str:
    """Formatiert Marketplace-Vergleich für Prompt"""
    lines = []
    for source, data in list(by_marketplace.items())[:5]:
        lines.append(
            f"- {source.capitalize()}: Ø {data['avg_price']:.2f}€ "
            f"(Min: {data['min_price']:.2f}€, Max: {data['max_price']:.2f}€, {data['count']} Angebote)"
        )
    return '\n'.join(lines)


def _format_sample_items(items: List[Dict]) -> str:
    """Formatiert Beispiel-Items für Prompt"""
    lines = []
    for item in items[:5]:
        if item.get('price'):
            lines.append(
                f"- {item['price']:.2f}€: {item['title'][:50]} ({item['source']})"
            )
    return '\n'.join(lines)


# ===================================================================
# PRICE PREDICTION (Machine Learning - Optional)
# ===================================================================

def predict_price_trend(query: str, historical_data: List[Dict]) -> Dict:
    """
    📈 Vorhersage von Preistrends

    Nutzt simple Linear Regression auf historische Daten.
    Für echtes ML: scikit-learn, Prophet, oder LSTM verwenden.

    Args:
        query: Produkt
        historical_data: Liste von {date, avg_price} Dicts

    Returns:
        Dict mit Trend-Analyse
    """
    if len(historical_data) < 3:
        return {'error': 'Nicht genug historische Daten'}

    # Simple Linear Regression
    n = len(historical_data)
    x_values = list(range(n))
    y_values = [d['avg_price'] for d in historical_data]

    # Berechne Slope
    x_mean = sum(x_values) / n
    y_mean = sum(y_values) / n

    numerator = sum((x_values[i] - x_mean) * (y_values[i] - y_mean) for i in range(n))
    denominator = sum((x_values[i] - x_mean) ** 2 for i in range(n))

    slope = numerator / denominator if denominator != 0 else 0
    intercept = y_mean - slope * x_mean

    # Vorhersage für nächste Periode
    next_x = n
    predicted_price = slope * next_x + intercept

    # Trend bestimmen
    if slope > 2:
        trend = 'steigend'
        recommendation = 'Jetzt kaufen - Preise steigen!'
    elif slope < -2:
        trend = 'fallend'
        recommendation = 'Warten lohnt sich - Preise fallen!'
    else:
        trend = 'stabil'
        recommendation = 'Preise stabil - kaufen wenn passendes Angebot'

    return {
        'trend': trend,
        'slope': slope,
        'current_avg': y_values[-1],
        'predicted_next': predicted_price,
        'change_percentage': ((predicted_price - y_values[-1]) / y_values[-1]) * 100,
        'recommendation': recommendation
    }


# ===================================================================
# SMART ALERTS mit KI
# ===================================================================

def should_trigger_alert(item: Dict, analysis: Dict, user_preferences: Dict) -> Dict:
    """
    🤖 Intelligente Alert-Entscheidung

    Entscheidet ob User benachrichtigt werden soll basierend auf:
    - Preis vs Durchschnitt
    - User-Budget
    - User-Präferenzen
    - Zustand des Artikels

    Args:
        item: Artikel
        analysis: Preis-Analyse
        user_preferences: User-Präferenzen

    Returns:
        Dict mit Entscheidung + Grund
    """
    reasons = []
    score = 0

    if not item.get('price'):
        return {'should_alert': False, 'reason': 'Kein Preis'}

    avg_price = analysis['avg_price']
    item_price = item['price']

    # Check 1: Preis
    if item_price < avg_price * 0.80:
        reasons.append(f"💎 Schnäppchen! {((avg_price - item_price) / avg_price * 100):.0f}% unter Durchschnitt")
        score += 3
    elif item_price < avg_price * 0.90:
        reasons.append(f"✨ Guter Preis! {((avg_price - item_price) / avg_price * 100):.0f}% unter Durchschnitt")
        score += 2

    # Check 2: Budget
    if user_preferences.get('max_budget'):
        if item_price <= user_preferences['max_budget']:
            reasons.append(f"💰 Im Budget! ({item_price:.2f}€ / {user_preferences['max_budget']:.2f}€)")
            score += 1

    # Check 3: Zustand
    if item.get('condition') == 'Neu' and item_price < avg_price:
        reasons.append("🆕 NEU und günstiger als Durchschnitt!")
        score += 2

    # Check 4: Marketplace Präferenz
    preferred_sources = user_preferences.get('preferred_sources', [])
    if item.get('source') in preferred_sources:
        reasons.append(f"⭐ Von bevorzugtem Portal: {item['source']}")
        score += 1

    # Entscheidung
    should_alert = score >= 2  # Mindestens 2 Punkte

    return {
        'should_alert': should_alert,
        'score': score,
        'reasons': reasons,
        'priority': 'high' if score >= 4 else 'medium' if score >= 2 else 'low'
    }


# ===================================================================
# TEST & EXAMPLES
# ===================================================================

def test_price_analysis():
    """Test der Preis-Analyse"""
    print("\n" + "="*70)
    print("🤖 KI-PREISANALYSE TEST")
    print("="*70 + "\n")

    # Mock-Daten
    results = [
        {'title': 'iPhone 13 Pro', 'price': 450.0, 'source': 'ebay', 'condition': 'Gebraucht'},
        {'title': 'iPhone 13', 'price': 380.0, 'source': 'kleinanzeigen', 'condition': 'Gebraucht'},
        {'title': 'iPhone 13 128GB', 'price': 420.0, 'source': 'quoka', 'condition': 'Neu'},
        {'title': 'iPhone 13 Pro Max', 'price': 550.0, 'source': 'ebay', 'condition': 'Neu'},
        {'title': 'iPhone 13 Mini', 'price': 350.0, 'source': 'shpock', 'condition': 'Gebraucht'},
        {'title': 'iPhone 13', 'price': 700.0, 'source': 'marktde', 'condition': 'Neu'},  # Überteuert!
        {'title': 'iPhone 13 64GB', 'price': 280.0, 'source': 'kleinanzeigen', 'condition': 'Gebraucht'},  # Schnäppchen!
    ]

    # Analyse
    analysis = analyze_prices_with_ai(results, "iPhone 13", user_budget=450.0)

    # Ausgabe
    print(f"[*] STATISTIKEN:")
    print(f"   Anzahl Angebote: {analysis['total_items']}")
    print(f"   Durchschnitt: {analysis['avg_price']:.2f}€")
    print(f"   Median: {analysis['median_price']:.2f}€")
    print(f"   Spanne: {analysis['min_price']:.2f}€ - {analysis['max_price']:.2f}€")
    print(f"   Standardabweichung: {analysis['std_dev']:.2f}€")

    print(f"\n💰 BUDGET-ANALYSE (Budget: 450€):")
    print(f"   Im Budget: {analysis['within_budget']} ({analysis['budget_percentage']:.0f}%)")

    print(f"\n💎 SCHNÄPPCHEN ({len(analysis['bargains'])} gefunden):")
    for item in analysis['bargains'][:3]:
        print(f"   • {item['price']:.2f}€ (-{item['discount_percentage']:.0f}%): {item['title'][:50]}")

    print(f"\n[!]  ÜBERTEUERT ({len(analysis['overpriced'])} gefunden):")
    for item in analysis['overpriced'][:3]:
        print(f"   • {item['price']:.2f}€ (+{item['overprice_percentage']:.0f}%): {item['title'][:50]}")

    print(f"\n🏪 MARKETPLACE VERGLEICH:")
    for source, data in analysis['by_marketplace'].items():
        print(f"   {source:15} Ø {data['avg_price']:6.2f}€  ({data['count']:2d} Angebote)")

    print(f"\n[OK] EMPFOHLENER PREIS-RANGE:")
    print(f"   {analysis['recommended_range']['min']:.2f}€ - {analysis['recommended_range']['max']:.2f}€")

    if 'ai_insights' in analysis and not analysis['ai_insights'].get('error'):
        print(f"\n🤖 KI-ANALYSE:")
        print(f"   {analysis['ai_insights']['text']}")

    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_price_analysis()
