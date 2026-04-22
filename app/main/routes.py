"""Main blueprint: index + methodology."""
from flask import Blueprint, redirect, render_template, url_for

main_bp = Blueprint("main", __name__, template_folder="../templates/main")


@main_bp.route("/")
def index():
    return redirect(url_for("odds.live_odds"))


@main_bp.route("/methodology")
def methodology():
    return render_template("main/methodology.html")
