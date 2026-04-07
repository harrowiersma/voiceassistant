"""Google OAuth 2.0 flow for Google Calendar access.

Provides /google/authorize (redirects to Google consent) and
/google/callback (receives auth code, exchanges for tokens, stores in DB).
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


def _db_path():
    return current_app.config.get("_DB_PATH") or current_app.config.get("DATABASE")


@bp.route("/google/authorize")
def authorize():
    """Start the Google OAuth flow — redirect user to Google's consent page."""
    db = _db_path()
    client_id = get_config("google.client_id", "", db)

    if not client_id:
        flash("Google Client ID not configured. Set it on the Availability page first.", "error")
        return redirect(url_for("availability.index"))

    # Google OAuth requires localhost for non-HTTPS redirect URIs.
    # Use explicit localhost URL since the Pi is accessed via local network.
    callback_url = "http://localhost:8080/google/callback"

    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }

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

    db = _db_path()
    client_id = get_config("google.client_id", "", db)
    client_secret = get_config("google.client_secret", "", db)
    callback_url = "http://localhost:8080/google/callback"

    # Exchange authorization code for tokens
    token_data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": callback_url,
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
        return redirect(url_for("availability.index"))

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    if not access_token:
        flash("No access token in Google's response.", "error")
        return redirect(url_for("availability.index"))

    # Store tokens in DB
    conn = get_db_connection(db)
    conn.execute(
        "INSERT OR REPLACE INTO oauth_tokens (provider, access_token, refresh_token, expires_at, scopes) "
        "VALUES (?, ?, ?, ?, ?)",
        ("google", access_token, refresh_token, expires_at.isoformat(), SCOPES),
    )
    conn.commit()
    conn.close()

    flash("Google Calendar connected successfully!", "success")
    return redirect(url_for("availability.index"))


def refresh_google_token(db_path=None):
    """Refresh an expired Google access token using the stored refresh token.

    Returns the new access token, or None if refresh failed.
    """
    conn = get_db_connection(db_path)
    row = conn.execute(
        "SELECT refresh_token FROM oauth_tokens WHERE provider = 'google'"
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
            "UPDATE oauth_tokens SET access_token = ?, expires_at = ? WHERE provider = 'google'",
            (access_token, expires_at.isoformat()),
        )
        conn.commit()

    conn.close()
    return access_token
