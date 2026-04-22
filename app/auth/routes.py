"""Auth blueprint: signup, login, logout. Email + password with bcrypt."""
from __future__ import annotations

import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user

from ..extensions import bcrypt, db
from ..models import User

auth_bp = Blueprint("auth", __name__, template_folder="../templates/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8


def _validate_credentials(email: str, password: str) -> str | None:
    if not EMAIL_RE.match(email or ""):
        return "Please enter a valid email address."
    if len(password or "") < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    return None


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        error = _validate_credentials(email, password)
        if error:
            flash(error, "error")
            return render_template("auth/signup.html", email=email)
        if db.session.query(User).filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
            return render_template("auth/signup.html", email=email)
        user = User(
            email=email,
            password_hash=bcrypt.generate_password_hash(password).decode("utf-8"),
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for("main.index"))
    return render_template("auth/signup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = db.session.query(User).filter_by(email=email).first()
        if user is None or not bcrypt.check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "error")
            return render_template("auth/login.html", email=email)
        login_user(user)
        next_url = request.args.get("next") or url_for("main.index")
        return redirect(next_url)
    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.index"))
