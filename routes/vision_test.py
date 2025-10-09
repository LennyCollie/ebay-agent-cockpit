# routes/vision_test.py

from flask import Blueprint, current_app, jsonify, request

from utils.vision_google import scan_google

bp = Blueprint("visiontest", __name__)


@bp.get("/public/vision-test")
def vision_test():
    urls = request.args.getlist("img")
    if not urls:
        return jsonify(error="usage: /public/vision-test?img=<url>&img=<url2>"), 400
    max_imgs = int(current_app.config.get("MAX_IMAGES_PER_ITEM", 2))
    return jsonify(scan_google(urls, max_images=max_imgs))
