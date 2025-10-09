def analyze_image_hybrid(urls):
    # 1. Erst Google Vision (kostenlos, schnell)
    google_result = scan_google(urls)

    # 2. Nur bei Verdacht OpenAI nutzen (kostet Geld)
    if google_result["score"] > 0.3 or "suspicious" in google_result["verdict"]:
        openai_result = scan_openai(urls)
        return openai_result

    return google_result
