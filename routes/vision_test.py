from flask import Blueprint, current_app, jsonify, request

bp = Blueprint("visiontest", __name__)


def _scan_google(urls, max_imgs):
    from utils.vision_google import scan_google  # lazy import

    return scan_google(urls, max_images=max_imgs)


def _scan_hybrid(urls):
    """
    Versucht zuerst die Hybrid-Funktion aus utils.vision_openai.
    Fallback: Google-Only, falls OpenAI/Hilfsfunktion nicht verfügbar ist.
    """
    try:
        # bevorzugt: neue Hybrid-Funktion
        from utils.vision_openai import analyze_image_hybrid as hybrid

        return hybrid(urls)
    except Exception:
        try:
            # fallback: falls jemand scan_openai implementiert hat
            from utils.vision_openai import scan_openai as hybrid

            return hybrid(urls)
        except Exception as e:
            return {"error": "openai/hybrid not available", "detail": str(e)}, 503


@bp.get("/public/vision-test")
def vision_test_default():
    """
    Rückwärtskompatibel: alter Pfad ruft Google-Scan auf.
    Wenn du Hybrid willst, nutze /public/vision-test/hybrid.
    """
    urls = request.args.getlist("img")
    if not urls:
        return jsonify(error="usage: /public/vision-test?img=<url>&img=<url2>"), 400
    max_imgs = int(current_app.config.get("MAX_IMAGES_PER_ITEM", 2))
    return jsonify(_scan_google(urls, max_imgs))


@bp.get("/public/vision-test/google")
def vision_test_google():
    urls = request.args.getlist("img")
    if not urls:
        return (
            jsonify(error="usage: /public/vision-test/google?img=<url>&img=<url2>"),
            400,
        )
    max_imgs = int(current_app.config.get("MAX_IMAGES_PER_ITEM", 2))
    return jsonify(_scan_google(urls, max_imgs))


@bp.get("/public/vision-test/hybrid")
def vision_test_hybrid():
    urls = request.args.getlist("img")
    if not urls:
        return (
            jsonify(error="usage: /public/vision-test/hybrid?img=<url>&img=<url2>"),
            400,
        )
    res = _scan_hybrid(urls)
    # _scan_hybrid kann schon (dict, statuscode) zurückgeben
    if isinstance(res, tuple):
        body, code = res
        return jsonify(body), code
    return jsonify(res)
