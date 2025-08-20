try:
    from .amazon import amazon_search_simple, AMZ_ENABLED  # re-export
except Exception:
    AMZ_ENABLED = False
    def amazon_search_simple(keyword: str, limit: int = 10, sort: str | None = None):
        # Fallback: keine Amazon-Ergebnisse liefern
        return []