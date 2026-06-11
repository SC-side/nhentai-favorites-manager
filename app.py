#!/usr/bin/env python3
"""nhentai collection manager - Flask backend"""

import math
import os
import platform
import subprocess
import threading
import webbrowser

import requests as req_lib
from flask import Flask, request, jsonify, send_from_directory, Response

from config import load_config, get_browser_command
from database import init_db, get_doujinshi, update_rating, update_notes, get_tags, get_stats

app = Flask(__name__)

# Local cover cache directory
COVER_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cover_cache")
os.makedirs(COVER_CACHE_DIR, exist_ok=True)


@app.route("/")
def index():
    return send_from_directory("templates", "index.html")


@app.route("/api/doujinshi")
def api_doujinshi():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 24, type=int)
    search = request.args.get("search", "").strip()
    tags = request.args.get("tags", "")
    tag_type = request.args.get("tag_type", "").strip()
    sort_by = request.args.get("sort", "favorited_at")
    sort_order = request.args.get("order", "desc")
    rating = request.args.get("rating", None)

    tag_ids = [int(t) for t in tags.split(",") if t.strip()] if tags else None
    rating_filter = int(rating) if rating is not None and rating != "" else None

    items, total = get_doujinshi(
        page=page,
        per_page=per_page,
        search=search,
        tag_ids=tag_ids,
        tag_type=tag_type or None,
        sort_by=sort_by,
        sort_order=sort_order,
        rating_filter=rating_filter,
    )

    return jsonify({
        "items": items,
        "total": total,
        "page": page,
        "pages": math.ceil(total / per_page) if total > 0 else 1,
    })


@app.route("/api/doujinshi/<int:nhentai_id>/rating", methods=["PATCH"])
def api_update_rating(nhentai_id):
    data = request.get_json()
    rating = data.get("rating")
    if rating is not None and rating not in (1, 2, 3):
        rating = None
    update_rating(nhentai_id, rating)
    return jsonify({"status": "ok", "rating": rating})


@app.route("/api/doujinshi/<int:nhentai_id>/notes", methods=["PATCH"])
def api_update_notes(nhentai_id):
    data = request.get_json()
    notes = data.get("notes", "")
    update_notes(nhentai_id, notes)
    return jsonify({"status": "ok", "notes": notes})


@app.route("/api/tags")
def api_tags():
    tag_type = request.args.get("type", None)
    tags = get_tags(tag_type=tag_type)
    return jsonify({"tags": tags})


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


@app.route("/api/cover/<media_id>/<cover_type>")
def api_cover(media_id, cover_type):
    """Proxy nhentai cover images. Downloaded images are stored in cover_cache/ and served directly without hitting the CDN again."""
    ext_map = {"j": "jpg", "p": "png", "g": "gif", "w": "webp"}
    ext = ext_map.get(cover_type, "jpg")

    # Check the local cache first
    for cached_file in os.listdir(COVER_CACHE_DIR):
        if cached_file.startswith(f"{media_id}."):
            cached_path = os.path.join(COVER_CACHE_DIR, cached_file)
            cached_ext = cached_file.rsplit(".", 1)[-1]
            mime_map = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
            with open(cached_path, "rb") as f:
                return Response(f.read(), content_type=mime_map.get(cached_ext, "image/jpeg"))

    # Cache miss → download from the CDN
    config = load_config()
    cookies = config.get("cookies", {})
    headers = {
        "Referer": "https://nhentai.net/",
        "User-Agent": config.get("user_agent", "Mozilla/5.0"),
    }

    hosts = ["t.nhentai.net", "t1.nhentai.net", "t2.nhentai.net", "t3.nhentai.net"]
    filenames = [f"cover.{ext}", "cover.webp", "cover.jpg", "cover.png", "thumb.jpg", "thumb.webp"]
    candidates = [f"https://{host}/galleries/{media_id}/{fname}"
                  for fname in filenames
                  for host in hosts]

    for img_url in candidates:
        try:
            resp = req_lib.get(img_url, headers=headers, cookies=cookies, timeout=8)
            if resp.status_code == 200 and resp.content:
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                # Determine the file extension and store it in the cache
                file_ext = img_url.rsplit(".", 1)[-1].split("?")[0]
                cache_path = os.path.join(COVER_CACHE_DIR, f"{media_id}.{file_ext}")
                with open(cache_path, "wb") as f:
                    f.write(resp.content)
                return Response(resp.content, content_type=content_type)
            if resp.status_code != 404:
                print(f"[cover] {resp.status_code} {img_url}")
        except Exception as e:
            print(f"[cover] error {img_url}: {e}")

    print(f"[cover] all paths failed: media_id={media_id}")
    return Response(status=404)


@app.route("/api/open/<int:nhentai_id>")
def api_open(nhentai_id):
    url = f"https://nhentai.net/g/{nhentai_id}/"
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(
                ["open", "-na", "Google Chrome", "--args", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif platform.system() == "Windows":
            chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            subprocess.Popen([chrome, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["google-chrome", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"status": "opened"})
    except Exception as e:
        return jsonify({"status": "fallback", "url": url, "error": str(e)})


if __name__ == "__main__":
    init_db()
    config = load_config()
    port = config.get("port", 5001)
    url = f"http://localhost:{port}"
    print(f"\n nhentai collection manager")
    print(f" Open your browser at: {url}")
    print(f" Press Ctrl+C to stop the server\n")
    # Only open the browser in the reloader child process, to avoid debug mode opening two tabs
    def open_in_chrome(target_url):
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", "-na", "Google Chrome", "--args", target_url],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif platform.system() == "Windows":
                chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
                subprocess.Popen([chrome, target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["google-chrome", target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            webbrowser.open(target_url)  # fall back to the default browser

    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Timer(1.5, open_in_chrome, [url]).start()
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
