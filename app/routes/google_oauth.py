"""Google OAuth 2.0 flow for Google Calendar access.

Supports both global tokens (person_id=0) and per-person tokens.
/google/authorize?person_id=X starts the flow for a specific person.
"""

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from flask import Blueprint, redirect, request, flash, url_for, current_app, session

from app.helpers import get_config
from db.connection import get_db_connection

bp = Blueprint("google_oauth", __name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/calendar.readonly"
CALLBACK_URL = "http://localhost:8080/google/callback"


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/google/authorize")
def authorize():
    """Start the Google OAuth flow. Pass ?person_id=X for per-person tokens."""
    db = _db_path()
    client_id = get_config("google.client_id", "", db)

    if not client_id:
        flash("Google Client ID not configured. Set it on the Availability page first.", "error")
        return redirect(url_for("availability.index"))

    # Store person_id in session so we can retrieve it in the callback
    person_id = request.args.get("person_id", "0")
    session["google_oauth_person_id"] = person_id

    params = {
        "client_id": client_id,
        "redirect_uri": CALLBACK_URL,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }

    # Hint the user's email if we have it (makes Google pre-select the account)
    if person_id != "0":
        conn = get_db_connection(db)
        person = conn.execute("SELECT email FROM persons WHERE id = ?", (int(person_id),)).fetchone()
        conn.close()
        if person and person["email"]:
            params["login_hint"] = person["email"]

    auth_url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)


@bp.route("/google/callback")
def callback():
    """Handle the OAuth callback from Google — exchange code for tokens."""
    error = request.args.get("error")
    if error:
        flash(f"Google authorization failed: {error}", "error")
        return redirect(url_for("availability.index"))

    code = request.args.get("code")
    if not code:
        flash("No authorization code received from Google.", "error")
        return redirect(url_for("availability.index"))

    # Retrieve person_id from session
    person_id = int(session.pop("google_oauth_person_id", "0"))

    db = _db_path()
    client_id = get_config("google.client_id", "", db)
    client_secret = get_config("google.client_secret", "", db)

    # Exchange authorization code for tokens
    token_data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": CALLBACK_URL,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=token_data, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
    except Exception as e:
        flash(f"Failed to exchange code for tokens: {e}", "error")
        return _redirect_back(person_id)

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    if not access_token:
        flash("No access token in Google's response.", "error")
        return _redirect_back(person_id)

    # Store tokens in DB with person_id
    conn = get_db_connection(db)
    conn.execute(
        "INSERT OR REPLACE INTO oauth_tokens (provider, person_id, access_token, refresh_token, expires_at, scopes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("google", person_id, access_token, refresh_token, expires_at.isoformat(), SCOPES),
    )
    conn.commit()
    conn.close()

    if person_id > 0:
        flash("Google Calendar connected for this person!", "success")
    else:
        flash("Google Calendar connected successfully!", "success")
    return _redirect_back(person_id)


def _redirect_back(person_id):
    """Redirect to person edit page or availability page."""
    if person_id > 0:
        return redirect(url_for("persons.edit", person_id=person_id))
    return redirect(url_for("availability.index"))


def get_google_token(db_path=None, person_id=0):
    """Get a valid Google access token for a person, refreshing if expired.

    Falls back to the global token (person_id=0) if no per-person token exists.
    """
    conn = get_db_connection(db_path)

    # Try per-person token first, then global
    row = None
    if person_id > 0:
        row = conn.execute(
            "SELECT access_token, refresh_token, expires_at FROM oauth_tokens "
            "WHERE provider = 'google' AND person_id = ?",
            (person_id,),
        ).fetchone()

    if not row:
        row = conn.execute(
            "SELECT access_token, refresh_token, expires_at FROM oauth_tokens "
            "WHERE provider = 'google' AND person_id = 0",
        ).fetchone()
        person_id = 0  # Using global token

    conn.close()

    if not row:
        return None

    # Check if token is expired
    if row["expires_at"]:
        try:
            exp = datetime.fromisoformat(row["expires_at"])
            if datetime.utcnow() >= exp:
                return _refresh_token(db_path, person_id)
        except (ValueError, TypeError):
            pass

    return row["access_token"]


def _refresh_token(db_path, person_id):
    """Refresh an expired Google access token."""
    conn = get_db_connection(db_path)
    row = conn.execute(
        "SELECT refresh_token FROM oauth_tokens WHERE provider = 'google' AND person_id = ?",
        (person_id,),
    ).fetchone()

    if not row or not row["refresh_token"]:
        conn.close()
        return None

    client_id = get_config("google.client_id", "", db_path)
    client_secret = get_config("google.client_secret", "", db_path)

    if not client_id or not client_secret:
        conn.close()
        return None

    token_data = urllib.parse.urlencode({
        "refresh_token": row["refresh_token"],
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    }).encode()

    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=token_data, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
    except Exception:
        conn.close()
        return None

    access_token = tokens.get("access_token")
    expires_in = tokens.get("expires_in", 3600)
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    if access_token:
        conn.execute(
            "UPDATE oauth_tokens SET access_token = ?, expires_at = ? "
            "WHERE provider = 'google' AND person_id = ?",
            (access_token, expires_at.isoformat(), person_id),
        )
        conn.commit()

    conn.close()
    return access_token
