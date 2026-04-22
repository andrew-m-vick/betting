"""Main blueprint: index, methodology, PWA plumbing."""
from flask import Blueprint, current_app, redirect, render_template, send_from_directory, url_for

main_bp = Blueprint("main", __name__, template_folder="../templates/main")


@main_bp.route("/")
def index():
    return redirect(url_for("odds.live_odds"))


@main_bp.route("/methodology")
def methodology():
    return render_template("main/methodology.html")


# -------- PWA plumbing --------
#
# A service worker's scope is capped at the path it's served from. Serving
# it at /static/service-worker.js would limit it to /static/* — useless.
# We serve the same file at /service-worker.js so it controls the whole
# origin. The manifest is served at /manifest.json for the same "clean URL"
# reason (some tools look there by convention).


@main_bp.route("/service-worker.js")
def service_worker():
    response = send_from_directory(current_app.static_folder, "service-worker.js")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@main_bp.route("/manifest.json")
def manifest():
    return send_from_directory(current_app.static_folder, "manifest.json")


@main_bp.route("/offline")
def offline():
    return render_template("offline.html")
