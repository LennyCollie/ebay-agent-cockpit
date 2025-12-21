import csv
from io import StringIO
from typing import List, Dict, Optional
from datetime import datetime


def export_search_results_to_csv(items: List[Dict], filename: Optional[str] = None) -> tuple:
    """Exportiert Suchergebnisse zu CSV"""

    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ebay_search_{timestamp}.csv"

    output = StringIO()

    fieldnames = [
        "Title", "Price", "Seller", "Seller Rating",
        "Portal", "Condition", "URL", "Found Date"
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for item in items:
        try:
            row = {
                "Title": item.get("title", ""),
                "Price": item.get("price", ""),
                "Seller": item.get("seller_name", item.get("seller", "")),
                "Seller Rating": item.get("seller_rating", ""),
                "Portal": item.get("source", item.get("portal", "")),
                "Condition": item.get("condition", ""),
                "URL": item.get("url", ""),
                "Found Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            writer.writerow(row)
        except Exception as e:
            print(f"[CSV Export] Error: {e}")
            continue

    csv_content = output.getvalue()
    output.close()

    return csv_content, filename
