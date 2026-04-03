import functools
import sqlite3

import bcrypt
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

bp = Blueprint("auth", __name__)


def login_required_hook():
    """before_request hook: check session, skip for auth routes and TESTING mode."""
    if current_app.config.get("TESTING"):
        return None

    # Allow access to auth-related routes without login
    if request.endpoint and request.endpoint.startswith("auth."):
        return None

    # Allow static files
    if request.endpoint == "static":
        return None

    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    return None


def _get_db():
    return sqlite3.connect(current_app.config["DATABASE"])


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        db = _get_db()
        try:
            row = db.execute(
                "SELECT id, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        finally:
            db.close()

        if row and bcrypt.checkpw(password.encode(), row[1].encode()):
            session.clear()
            session["user_id"] = row[0]
            session["username"] = username
            return redirect(url_for("dashboard.home"))

        flash("Invalid username or password.", "error")

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/auth/change-password", methods=["POST"])
def change_password():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")

    if not new_password or len(new_password) < 6:
        flash("New password must be at least 6 characters.", "error")
        return redirect(request.referrer or url_for("dashboard.home"))

    db = _get_db()
    try:
        row = db.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (session["user_id"],),
        ).fetchone()

        if not row or not bcrypt.checkpw(current_password.encode(), row[0].encode()):
            flash("Current password is incorrect.", "error")
            return redirect(request.referrer or url_for("dashboard.home"))

        new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (new_hash, session["user_id"]),
        )
        db.commit()
    finally:
        db.close()

    flash("Password changed successfully.", "success")
    return redirect(request.referrer or url_for("dashboard.home"))
