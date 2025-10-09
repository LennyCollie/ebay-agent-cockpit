# routes/vision_test.py

from flask import Blueprint, current_app, jsonify, request

from utils.vision_google import scan_google
from utils.vision_openai import scan_openai  # NEU

bp = Blueprint("visiontest", __name__)


@bp.get("/public/vision-test")
def vision_test():
    urls = request.args.getlist("img")
    if not urls:
        return jsonify(error="usage: /public/vision-test?img=<url>&img=<url2>"), 400

    # Optional: provider parameter
    provider = request.args.get("provider", "openai")  # Default zu OpenAI
    max_imgs = int(current_app.config.get("MAX_IMAGES_PER_ITEM", 2))

    if provider == "google":
        return jsonify(scan_google(urls, max_images=max_imgs))
    else:
        return jsonify(scan_openai(urls, max_images=max_imgs))
