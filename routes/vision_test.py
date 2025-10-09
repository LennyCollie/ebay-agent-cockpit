from flask import Blueprint, current_app, jsonify, request

bp = Blueprint("visiontest", __name__)


@bp.get("/public/vision-test/google")
def vision_test_google():
    urls = request.args.getlist("img")
    if not urls:
        return (
            jsonify(error="usage: /public/vision-test/google?img=<url>&img=<url2>"),
            400,
        )
    from utils.vision_google import scan_google  # lazy import

    max_imgs = int(current_app.config.get("MAX_IMAGES_PER_ITEM", 2))
    return jsonify(scan_google(urls, max_images=max_imgs))


@bp.get("/public/vision-test/hybrid")
def vision_test_hybrid():
    urls = request.args.getlist("img")
    if not urls:
        return (
            jsonify(error="usage: /public/vision-test/hybrid?img=<url>&img=<url2>"),
            400,
        )
    try:
        from utils.vision_openai import analyze_image_hybrid  # <— NICHT inspect!
    except Exception as e:
        return jsonify(error="openai/hybrid not available", detail=str(e)), 503
    return jsonify(analyze_image_hybrid(urls))
