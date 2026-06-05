# app.py
import os
import re
import json
import time
import secrets
import hashlib
import base64
import smtplib
import sqlite3
import threading
import collections
import logging
import urllib.parse
import urllib.request
import urllib.error
from email.message import EmailMessage
from email.utils import parseaddr
from functools import wraps
import PyPDF2 as pdf
from dotenv import load_dotenv
import google.generativeai as genai
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask import render_template
from werkzeug.security import generate_password_hash, check_password_hash

# Initialize Flask app
app = Flask(__name__)


def _load_secret_key():
    """Return a stable, non-public secret key.

    Prefers FLASK_SECRET from the environment. Otherwise generates a random
    key once and persists it to a gitignored file so sessions survive restarts
    without ever falling back to a publicly-known constant.
    """
    env_secret = os.getenv("FLASK_SECRET")
    if env_secret:
        return env_secret
    secret_path = os.path.join(os.path.dirname(__file__), ".flask_secret")
    try:
        if os.path.exists(secret_path):
            with open(secret_path, "r") as fh:
                saved = fh.read().strip()
                if saved:
                    return saved
        generated = os.urandom(32).hex()
        with open(secret_path, "w") as fh:
            fh.write(generated)
        return generated
    except Exception:
        # Last resort (e.g. read-only FS): random per-process key.
        return os.urandom(32).hex()


app.secret_key = _load_secret_key()
# Session cookie hardening; SECURE is enabled automatically behind HTTPS.
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=bool(os.getenv("HTTPS")),
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # 10 MB upload cap (matches client)
)
# The SPA is served same-origin by this app, so restrict credentialed CORS to
# known origins instead of reflecting any origin.
CORS(app, supports_credentials=True, origins=[
    os.getenv("FRONTEND_ORIGIN", "http://localhost:5000"),
    "http://127.0.0.1:5000",
])


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "File too large. Please upload a file under 10MB."}), 413

# Load environment variables and configure the Gemini API
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise RuntimeError(
        "Missing GOOGLE_API_KEY in .env. Add your Google Gemini key to .env.")
genai.configure(api_key=GOOGLE_API_KEY)

# Model selection. Can be overridden in .env with GEMINI_MODEL=...
# We try these in order until one works (newer models first; older as fallback).
MODEL_CANDIDATES = [
    os.getenv("GEMINI_MODEL"),
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
]
MODEL_CANDIDATES = [m for m in MODEL_CANDIDATES if m]

# Deterministic decoding so the same resume always yields the same analysis.
# Without this, Gemini's default temperature (~1.0) makes every call random —
# the same PDF (or a PDF vs. its screenshot) would score differently each time.
# response_mime_type forces well-formed JSON (no markdown fences, no prose), and
# the generous max_output_tokens stops long reports from being cut off mid-JSON
# (the "Invalid JSON response from AI" error was truncated output).
GENERATION_CONFIG = {
    "temperature": 0,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 8192,
    "response_mime_type": "application/json",
}

# Database setup
DB_PATH = os.path.join(os.path.dirname(__file__), "ats.db")


def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            jd TEXT,
            filename TEXT,
            upload_type TEXT,
            extracted_text TEXT,
            response_json TEXT
        )"""
    )
    # Users table for authentication
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    # Unverified sign-ups awaiting OTP confirmation. The real users row is only
    # created once the emailed code is verified, so this holds the pending data.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pending_signups (
            email TEXT PRIMARY KEY,
            name TEXT,
            password_hash TEXT NOT NULL,
            otp_hash TEXT NOT NULL,
            expires_at REAL NOT NULL,
            attempts INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    # Single-use password-reset tokens (only the SHA-256 hash is stored).
    conn.execute(
        """CREATE TABLE IF NOT EXISTS password_resets (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at REAL NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    # Migration: add user_id column to evaluations if it doesn't exist yet
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(evaluations)").fetchall()]
    if "user_id" not in cols:
        conn.execute("ALTER TABLE evaluations ADD COLUMN user_id INTEGER")
    conn.commit()
    return conn


DB_CONN = init_db()
# The dev server is threaded and we share one SQLite connection, so serialize
# all access to avoid "recursive use of cursors" and interleaved commits.
DB_LOCK = threading.RLock()


def db_query(sql, params=(), one=False):
    """Thread-safe SELECT. Returns a list of rows, or a single row if one=True."""
    with DB_LOCK:
        rows = DB_CONN.execute(sql, params).fetchall()
    if one:
        return rows[0] if rows else None
    return rows


def db_execute(sql, params=()):
    """Thread-safe INSERT/UPDATE/DELETE. Returns lastrowid (captured under lock)."""
    with DB_LOCK:
        cur = DB_CONN.cursor()
        cur.execute(sql, params)
        DB_CONN.commit()
        return cur.lastrowid


def save_evaluation(jd, filename, upload_type, extracted_text, response_json, user_id=None):
    return db_execute(
        "INSERT INTO evaluations (jd, filename, upload_type, extracted_text, response_json, user_id) VALUES (?, ?, ?, ?, ?, ?)",
        (jd, filename, upload_type, extracted_text,
         json.dumps(response_json, ensure_ascii=False), user_id),
    )


# --- Authentication helpers ---
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Non-anchored variants for scanning inside resume text (ATS Health).
EMAIL_SEARCH_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}")
PHONE_SEARCH_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")


def current_user():
    """Return the logged-in user's row as a dict, or None."""
    uid = session.get("user_id")
    if not uid:
        return None
    row = db_query(
        "SELECT id, name, email, created_at FROM users WHERE id = ?", (uid,), one=True
    )
    return dict(row) if row else None


def login_required(view):
    """Reject API calls from logged-out visitors so the AI features are usable
    only after sign-in. The UI also hides them; this enforces it server-side."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({
                "error": "Please log in or create an account to use this feature.",
                "auth_required": True,
            }), 401
        return view(*args, **kwargs)
    return wrapped


# --- One-time-password (OTP) email verification for sign-up ---
OTP_TTL_SECONDS = 600          # codes are valid for 10 minutes
OTP_MAX_ATTEMPTS = 5           # wrong tries before a code is burned
RESET_TTL_SECONDS = 1800       # password-reset links valid for 30 minutes


def _generate_otp():
    """Cryptographically-random 6-digit code as a zero-padded string."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_token(token):
    """SHA-256 of a reset token. The token itself is high-entropy random, so a
    fast deterministic hash is fine (and lets us look rows up by it)."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _smtp_configured(host, user, password):
    """True only when real SMTP creds are present. Blank values, or the .env
    placeholder like '<16-char app password>', count as 'not configured' so we
    skip a slow, doomed Gmail login and fall straight back to the console."""
    if not (host and user and password):
        return False
    if "<" in password or ">" in password:   # leftover placeholder text in .env
        return False
    return True


def _gmail_access_token(client_id, client_secret, refresh_token):
    """Exchange a long-lived refresh token for a short-lived Gmail access token."""
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:500]
        raise RuntimeError(f"Gmail token refresh failed HTTP {e.code}: {detail}") from e
    token = body.get("access_token")
    if not token:
        raise RuntimeError("Gmail token refresh returned no access_token")
    return token


def _send_via_gmail_api(to_email, subject, text_body, html_body):
    """Send one email through the Gmail API over HTTPS, authenticated with a
    stored OAuth refresh token.

    Google itself sends the mail from the authorized account, so deliverability
    is excellent and it works on hosts that block SMTP (e.g. Render). Raises on
    failure so the caller can log it and fall back.
    """
    client_id = os.getenv("GMAIL_CLIENT_ID")
    client_secret = os.getenv("GMAIL_CLIENT_SECRET")
    refresh_token = os.getenv("GMAIL_REFRESH_TOKEN")
    sender = os.getenv("GMAIL_SENDER") or os.getenv("SMTP_USER") or ""

    access_token = _gmail_access_token(client_id, client_secret, refresh_token)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    payload = json.dumps({"raw": raw}).encode("utf-8")
    req = urllib.request.Request(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        data=payload,
        headers={"Authorization": f"Bearer {access_token}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:500]
        raise RuntimeError(f"Gmail send failed HTTP {e.code}: {detail}") from e


def _send_via_brevo(api_key, to_email, subject, text_body, html_body):
    """Send one transactional email through the Brevo HTTPS API.

    Works on hosts that block outbound SMTP (e.g. Render, which can't even
    resolve smtp.gmail.com). Raises on failure so the caller can log it and
    fall back. The sender address must be a *verified sender* in Brevo.
    """
    raw_sender = (os.getenv("BREVO_SENDER") or os.getenv("SMTP_FROM")
                  or os.getenv("SMTP_USER") or "")
    sender_name, sender_addr = parseaddr(raw_sender)
    payload = {
        "sender": {"name": sender_name or "Smart ATS", "email": sender_addr},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text_body,
    }
    if html_body:
        payload["htmlContent"] = html_body
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:500]
        raise RuntimeError(f"Brevo HTTP {e.code}: {detail}") from e


def _deliver_email(to_email, subject, text_body, html_body, console_line):
    """Deliver one email, preferring the Brevo HTTPS API (works where SMTP is
    blocked), then SMTP (local dev), then printing to the console as a last
    resort so the flow stays testable.

    Returns "email" if it was actually sent, otherwise "console".
    """
    # Preferred path: Gmail API over HTTPS — Google sends from the authorized
    # account itself, so it delivers reliably and works where SMTP is blocked.
    if os.getenv("GMAIL_REFRESH_TOKEN"):
        try:
            _send_via_gmail_api(to_email, subject, text_body, html_body)
            print(f"[EMAIL SENT via Gmail API] '{subject}' -> {to_email}", flush=True)
            app.logger.info("Email '%s' delivered to %s via Gmail API", subject, to_email)
            return "email"
        except Exception:
            app.logger.exception("Gmail API send failed for %s", to_email)
            # Fall through to Brevo / SMTP / console below.

    # Next: Brevo over HTTPS. SMTP ports (25/465/587) are blocked on many hosts
    # (Render included), so an HTTP API is the reliable way to send.
    brevo_key = os.getenv("BREVO_API_KEY")
    if brevo_key:
        try:
            _send_via_brevo(brevo_key, to_email, subject, text_body, html_body)
            print(f"[EMAIL SENT via Brevo] '{subject}' -> {to_email}", flush=True)
            app.logger.info("Email '%s' delivered to %s via Brevo", subject, to_email)
            return "email"
        except Exception:
            app.logger.exception("Brevo API send failed for %s", to_email)
            # Fall through to SMTP / console below.

    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    # Gmail shows app passwords as 4 space-separated groups; SMTP wants them joined.
    password = (os.getenv("SMTP_PASS") or "").replace(" ", "")
    port = int(os.getenv("SMTP_PORT") or 587)
    sender = os.getenv("SMTP_FROM") or user

    if not _smtp_configured(host, user, password):
        print(f"\n{console_line}\n", flush=True)
        app.logger.warning("SMTP not configured — email to %s printed to console.", to_email)
        return "console"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    if to_email.strip().lower() == (user or "").strip().lower():
        # The recipient is the sending account itself — Gmail files it under
        # "Sent"/"All Mail", which can look like the code "went to the project
        # inbox". Flag it so it's clear during testing.
        app.logger.warning(
            "OTP/reset recipient (%s) is the SMTP sender account — it will appear "
            "in that account's Sent/All Mail. Register with a different email to test "
            "real delivery.", to_email)

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(user, password)
            # Be explicit about the envelope recipient so it can never be confused
            # with the authenticated sender account.
            server.send_message(msg, from_addr=sender, to_addrs=[to_email])
        # Visible confirmation of exactly who received each email.
        print(f"[EMAIL SENT] '{subject}' -> {to_email}", flush=True)
        app.logger.info("Email '%s' delivered to %s", subject, to_email)
        return "email"
    except Exception:
        app.logger.exception("Failed to send email to %s", to_email)
        print(f"\n{console_line}\n", flush=True)
        return "console"


def send_otp_email(to_email, otp, name=None):
    """Email a sign-up verification code (console fallback in dev)."""
    greeting = f"Hi {name}," if name else "Hi,"
    text = (
        f"{greeting}\n\nYour Smart ATS verification code is: {otp}\n\n"
        "It expires in 10 minutes. If you didn't request this, you can ignore this email."
    )
    html = f"""\
<div style="font-family:Inter,Arial,sans-serif;max-width:460px;margin:auto;color:#14122b">
  <h2 style="color:#7c3aed;margin:0 0 12px">Smart ATS</h2>
  <p>{greeting}</p>
  <p>Your verification code is:</p>
  <p style="font-size:34px;font-weight:800;letter-spacing:8px;margin:8px 0">{otp}</p>
  <p style="color:#6b6a85">This code expires in 10 minutes. If you didn't request it, you can ignore this email.</p>
</div>"""
    return _deliver_email(to_email, "Your Smart ATS verification code", text, html,
                          f"[DEV OTP] Verification code for {to_email}: {otp}")


def send_reset_email(to_email, reset_url, name=None):
    """Email a password-reset link (console fallback in dev)."""
    greeting = f"Hi {name}," if name else "Hi,"
    text = (
        f"{greeting}\n\nWe received a request to reset your Smart ATS password.\n\n"
        f"Reset it here (the link is valid for 30 minutes):\n{reset_url}\n\n"
        "If you didn't request this, you can safely ignore this email — your password won't change."
    )
    html = f"""\
<div style="font-family:Inter,Arial,sans-serif;max-width:460px;margin:auto;color:#14122b">
  <h2 style="color:#7c3aed;margin:0 0 12px">Smart ATS</h2>
  <p>{greeting}</p>
  <p>We received a request to reset your password. Click the button below (valid for 30 minutes):</p>
  <p style="margin:18px 0">
    <a href="{reset_url}" style="background:#7c3aed;color:#fff;text-decoration:none;padding:12px 22px;border-radius:10px;font-weight:700;display:inline-block">Reset password</a>
  </p>
  <p style="color:#6b6a85;font-size:13px">Or paste this link into your browser:<br>{reset_url}</p>
  <p style="color:#6b6a85">If you didn't request this, you can safely ignore this email — your password won't change.</p>
</div>"""
    return _deliver_email(to_email, "Reset your Smart ATS password", text, html,
                          f"[DEV PASSWORD RESET] Link for {to_email}: {reset_url}")


def _save_pending_signup(name, email, password_hash, otp):
    """Stash an unverified sign-up keyed by email until its OTP is confirmed.
    INSERT OR REPLACE resets the attempt counter whenever a fresh code is issued."""
    db_execute(
        "INSERT OR REPLACE INTO pending_signups "
        "(email, name, password_hash, otp_hash, expires_at, attempts) VALUES (?, ?, ?, ?, ?, 0)",
        (email, name, password_hash, generate_password_hash(otp), time.time() + OTP_TTL_SECONDS),
    )


def _get_pending_signup(email):
    return db_query("SELECT * FROM pending_signups WHERE email = ?", (email,), one=True)


def _delete_pending_signup(email):
    db_execute("DELETE FROM pending_signups WHERE email = ?", (email,))


# --- Your existing helper functions ---


class AIRateLimitError(RuntimeError):
    """Raised when Gemini rejects a call due to quota / rate limits (HTTP 429)."""


def _is_rate_limit(msg):
    m = msg.lower()
    return ("429" in m or "quota" in m or "rate limit" in m
            or "resource_exhausted" in m or "exceeded your current quota" in m)


def _retry_seconds(msg):
    """Pull a 'retry after N seconds' hint out of the Gemini error text, if any."""
    m = (re.search(r"retry in ([\d.]+)\s*s", msg, re.I)
         or re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", msg)
         or re.search(r"seconds:\s*(\d+)", msg))
    return int(float(m.group(1))) if m else None


def _response_text(response):
    """Safely extract text from a Gemini response. response.text raises when the
    model returns no text part (e.g. a blocked/empty/MAX_TOKENS finish), so fall
    back to reading the parts directly instead of crashing the whole request."""
    try:
        return response.text
    except Exception:
        try:
            parts = response.candidates[0].content.parts
            return "".join(getattr(p, "text", "") for p in parts)
        except Exception:
            return ""


def get_gemini_repsonse(input_text, image_part=None):
    """Calls the Gemini model to get the evaluation.

    If image_part is given, the resume image is sent to Gemini's vision model
    so it can read the resume directly (no local OCR / Tesseract needed).

    Tries each candidate model until one succeeds. Fails fast (no pointless
    model retries) on auth or rate-limit errors, with a clear, user-friendly
    message.
    """
    content = [input_text] if image_part is None else [input_text, image_part]
    last_err = None
    for model_name in MODEL_CANDIDATES:
        try:
            model = genai.GenerativeModel(
                model_name, generation_config=GENERATION_CONFIG)
            response = model.generate_content(content)
            text = _response_text(response)
            if text.strip():
                return text
            # Empty response (blocked/over-budget): treat as failure, try next model.
            last_err = RuntimeError(f"{model_name} returned an empty response.")
            continue
        except Exception as e:
            last_err = e
            msg = str(e)
            low = msg.lower()
            # Rate-limit / quota: the candidate models share the same free-tier
            # daily quota, so trying the others just burns more of it and adds
            # latency. Fail fast with an actionable message.
            if _is_rate_limit(low):
                wait = _retry_seconds(msg)
                hint = (f" Please wait about {wait} seconds and try again."
                        if wait else " Please wait a minute and try again.")
                raise AIRateLimitError(
                    "The AI service is rate-limited — your Google API key's free-tier "
                    "daily quota is used up." + hint +
                    " To remove the ~20-requests/day cap, enable billing on your key at "
                    "https://aistudio.google.com/app/apikey."
                ) from e
            # Auth / key problems won't be fixed by trying another model — fail fast.
            if any(s in low for s in ("api key", "permission_denied", "leaked",
                                      "api_key_invalid", "unauthenticated", "403")):
                raise RuntimeError(
                    "Google API key was rejected (it may be invalid, disabled, or reported as "
                    "leaked). Generate a new key at https://aistudio.google.com/app/apikey and "
                    "put it in your .env as GOOGLE_API_KEY."
                ) from e
            # Otherwise (e.g. model not found / 404) fall through and try the next model.
    raise RuntimeError(
        f"Could not get a response from any Gemini model ({', '.join(MODEL_CANDIDATES)}). "
        f"Last error: {last_err}"
    )


def input_pdf_text(uploaded_file):
    """Extracts text from the uploaded PDF file."""
    # Note: uploaded_file is now a file stream from Flask
    reader = pdf.PdfReader(uploaded_file)
    text = ""
    for page in reader.pages:
        # extract_text() returns None for textless pages — skip, don't stringify
        # (str(None) -> "None" would defeat the scanned-PDF / ATS-Health checks).
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


def build_media_part(uploaded_file, fallback_mime='image/png'):
    """Read an uploaded file into a Gemini-compatible inline media part.

    Uses Gemini's multimodal understanding (images AND PDFs) instead of local
    OCR, so no Tesseract install is required and scanned PDFs work too.
    """
    uploaded_file.stream.seek(0)
    data = uploaded_file.stream.read()
    if not data:
        raise RuntimeError("The uploaded file appears to be empty.")
    mime = uploaded_file.mimetype or ''
    if not (mime.startswith('image') or mime == 'application/pdf'):
        mime = fallback_mime
    return {"mime_type": mime, "data": data}


def extract_json(text):
    """Strip markdown fences and parse the first JSON object out of model text.

    Returns the parsed object. Raises ValueError if no JSON can be parsed.
    """
    cleaned = (text or '').strip()
    if cleaned.startswith('```json'):
        cleaned = cleaned[7:]
    if cleaned.startswith('```'):
        cleaned = cleaned[3:]
    if cleaned.endswith('```'):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    start = cleaned.find('{')
    end = cleaned.rfind('}') + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in model response.")
    return json.loads(cleaned[start:end])


def compute_ats_health(resume_text, upload_type):
    """Deterministic, no-AI machine-readability check on the resume file.

    Catches the silent killers: scanned/image resumes with no text layer,
    missing contact info, no bullet points, and likely multi-column layouts
    that confuse ATS parsers.
    """
    text = resume_text or ''
    stripped = text.strip()
    char_count = len(stripped)
    lines = text.splitlines()
    is_scanned = (upload_type == 'image') or (char_count == 0)

    has_email = bool(EMAIL_SEARCH_RE.search(text))
    has_phone = bool(PHONE_SEARCH_RE.search(text))
    bullet_count = sum(1 for l in lines if l.strip()[:1] in ('•', '-', '*', '‣', '◦', '·'))
    # Multi-column heuristic: many lines split by 2+ runs of 3+ spaces.
    multi_col_lines = sum(1 for l in lines if len(re.findall(r' {3,}', l)) >= 2)
    likely_columns = multi_col_lines >= 5

    parse_ok = (not is_scanned) and char_count >= 200
    checks = []
    if is_scanned:
        checks.append({"ok": False, "label": "Selectable text",
                       "detail": "No text layer found — many ATS can't read this. Export a text-based PDF."})
    else:
        checks.append({"ok": parse_ok, "label": "Readable text layer",
                       "detail": f"{char_count} characters extracted." if parse_ok
                       else "Very little text extracted — check that your resume isn't image-based."})
        checks.append({"ok": has_email, "label": "Email address",
                       "detail": "Found a contact email." if has_email else "No email detected — add one to the header."})
        checks.append({"ok": has_phone, "label": "Phone number",
                       "detail": "Found a phone number." if has_phone else "No phone number detected — add one to the header."})
        checks.append({"ok": bullet_count >= 3, "label": "Bullet points",
                       "detail": f"{bullet_count} bullet lines." if bullet_count >= 3
                       else "Few/no bullets — use bullet points so parsers find achievements."})
        checks.append({"ok": not likely_columns, "label": "Single-column layout",
                       "detail": "Looks single-column (parser-friendly)." if not likely_columns
                       else "Looks multi-column — ATS often jumble columns. Prefer a single column."})

    passed = sum(1 for c in checks if c["ok"])
    total = len(checks)
    return {
        "parse_ok": parse_ok,
        "is_scanned": is_scanned,
        "passed": passed,
        "total": total,
        "checks": checks,
    }


# --- Prompt Template ---
# Refined prompt for better JSON output
input_prompt = """
You are an expert ATS (Application Tracking System) evaluator and career coach with 10+ years of experience in tech recruitment. Analyze the resume against the job description and provide ONLY a valid JSON response.

IMPORTANT: Return ONLY the JSON object, no other text, no explanations, no markdown formatting.

Required JSON format:
{{
  "JD Match": "85%",
  "MissingKeywords": ["keyword1", "keyword2"],
  "KeywordTriage": {{
    "must_have": ["core skills/keywords the JD clearly requires that are missing from the resume"],
    "nice_to_have": ["secondary or 'bonus' keywords that are missing"],
    "quick_wins": [{{"keyword": "a missing keyword that is easy to legitimately add", "how_to_add": "a one-line, honest suggestion for where/how to add it"}}]
  }},
  "entry_level_signal": false,
  "Profile Summary": "Provide a comprehensive 4-5 sentence analysis that: 1) Starts with a clear match percentage assessment and overall fit evaluation, 2) Highlights 2-3 specific strengths from the resume that directly align with the job requirements, 3) Identifies 2-3 specific gaps or areas for improvement with concrete examples, 4) Provides 2-3 actionable recommendations for resume enhancement (e.g., 'Add a project showcasing Python skills', 'Include specific metrics for achievements'), 5) Ends with a motivational note about the candidate's potential. Use specific examples from both the resume and JD to make feedback concrete and actionable."
}}

Rules:
- "MissingKeywords" MUST be the union of every keyword in must_have + nice_to_have + quick_wins (kept for compatibility).
- "entry_level_signal" = true ONLY if the job description implicitly demands ~3+ years of experience / seniority despite being framed broadly (helps warn junior applicants).
- Keep each triage list focused (max ~8 items). Be specific and honest; never suggest fabricating experience.
- Score strictly on the resume's CONTENT (skills, experience, keywords) versus the JD. IGNORE visual formatting, fonts, colors, and whether the resume was provided as text or as an image/screenshot — the same resume must receive the same JD Match either way.

Resume text: {text}

Job Description: {jd}

Remember: Return ONLY the JSON object, nothing else. Make the Profile Summary detailed, specific, and actionable with concrete examples.
"""


@app.route('/evaluate', methods=['POST'])
@login_required
def evaluate_resume():
    """The main API endpoint to handle resume evaluation."""
    if 'resume' not in request.files:
        return jsonify({"error": "No resume file part"}), 400

    resume_file = request.files['resume']
    jd = request.form.get('jd', '')

    if resume_file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if jd == '':
        return jsonify({"error": "No job description provided"}), 400

    try:
        # Decide how to handle the file depending on its type
        filename = resume_file.filename.lower()
        content_type = resume_file.mimetype or ''
        is_pdf = filename.endswith('.pdf') or 'pdf' in content_type
        is_image = content_type.startswith('image') or any(
            filename.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.webp', '.gif'])

        media_part = None
        resume_text = ''
        if is_pdf:
            upload_type = 'pdf'
            resume_text = (input_pdf_text(resume_file) or '').strip()
            # Scanned PDF (no extractable text): send the PDF itself to Gemini
            if not resume_text:
                media_part = build_media_part(resume_file, fallback_mime='application/pdf')
        elif is_image:
            upload_type = 'image'
        else:
            # Unknown type — try PDF text extraction, otherwise treat as image
            try:
                upload_type = 'pdf'
                resume_text = (input_pdf_text(resume_file) or '').strip()
                # Unknown-but-PDF with no text: route the file itself to Gemini
                if not resume_text:
                    media_part = build_media_part(resume_file, fallback_mime='application/pdf')
            except Exception:
                upload_type = 'image'

        if upload_type == 'image':
            # Use Gemini vision: send the image directly (no local OCR / Tesseract)
            media_part = build_media_part(resume_file, fallback_mime='image/png')

        if media_part is not None:
            prompt = input_prompt.format(
                text="(The resume is provided as the attached file. Read it carefully and "
                     "extract all relevant information from it.)",
                jd=jd)
        else:
            prompt = input_prompt.format(text=resume_text, jd=jd)

        response_text = get_gemini_repsonse(prompt, image_part=media_part)

        # Clean the response text
        cleaned_response = response_text.strip()

        # Remove any markdown code blocks if present
        if cleaned_response.startswith('```json'):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.startswith('```'):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith('```'):
            cleaned_response = cleaned_response[:-3]

        cleaned_response = cleaned_response.strip()

        # Find JSON object boundaries
        start_index = cleaned_response.find('{')
        end_index = cleaned_response.rfind('}') + 1

        if start_index == -1 or end_index == 0:
            # If '{' or '}' is not found, try to create a fallback response
            return jsonify({
                "error": "AI response format issue",
                "raw_response": cleaned_response[:200] + "..." if len(cleaned_response) > 200 else cleaned_response
            }), 500

        json_str = cleaned_response[start_index:end_index]

        # Try to parse the JSON
        try:
            response_json = json.loads(json_str)

            # Validate required fields
            required_fields = ["JD Match",
                               "MissingKeywords", "Profile Summary"]
            for field in required_fields:
                if field not in response_json:
                    response_json[field] = "Not available" if field == "Profile Summary" else [
                    ]

            # Derive MissingKeywords from the triage groups if the model omitted
            # it, so the UI (and history) always has a flat keyword list.
            triage = response_json.get("KeywordTriage") or {}
            if isinstance(triage, dict) and not response_json.get("MissingKeywords"):
                derived = []
                derived += [str(k) for k in (triage.get("must_have") or [])]
                derived += [str(k) for k in (triage.get("nice_to_have") or [])]
                for qw in (triage.get("quick_wins") or []):
                    if isinstance(qw, dict) and qw.get("keyword"):
                        derived.append(str(qw["keyword"]))
                # de-duplicate, preserve order
                response_json["MissingKeywords"] = list(dict.fromkeys(derived))

            # Save evaluation to database (linked to the logged-in user, if any)
            eval_id = None
            try:
                eval_id = save_evaluation(jd, resume_file.filename,
                                          upload_type, resume_text, response_json,
                                          user_id=session.get("user_id"))
            except Exception as db_err:
                # If DB save fails, keep processing but log the issue
                app.logger.exception("Database save failed: %s", db_err)

            # Extra metadata (underscore-prefixed → not part of the scored fields)
            response_json["_evaluation_id"] = eval_id
            response_json["_resume_text"] = resume_text
            response_json["_ats_health"] = compute_ats_health(resume_text, upload_type)
            return jsonify(response_json)

        except json.JSONDecodeError as json_err:
            # If JSON parsing fails, return a structured error with the raw response
            return jsonify({
                "error": "Invalid JSON response from AI",
                "raw_response": json_str[:200] + "..." if len(json_str) > 200 else json_str,
                "json_error": str(json_err)
            }), 500

    except AIRateLimitError as e:
        # Rate-limited / out of quota — show the actionable message, not "try again".
        return jsonify({"error": str(e)}), 429
    except Exception as e:
        # Log detail server-side; return a friendly message (no internal leakage).
        app.logger.exception("evaluate_resume failed")
        msg = str(e) if app.debug else "Something went wrong while analyzing your resume. Please try again."
        return jsonify({"error": msg}), 500


@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template('index.html')


@app.route('/history', methods=['GET'])
def history():
    uid = session.get("user_id")
    if uid:
        # Logged-in users see only their own analyses
        rows = db_query(
            "SELECT id, created_at, jd, filename, upload_type, response_json FROM evaluations "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (uid,),
        )
    else:
        # Guests see recent anonymous analyses
        rows = db_query(
            "SELECT id, created_at, jd, filename, upload_type, response_json FROM evaluations "
            "WHERE user_id IS NULL ORDER BY created_at DESC LIMIT 50"
        )
    results = []
    for row in rows:
        parsed = None
        try:
            parsed = json.loads(row['response_json']
                                ) if row['response_json'] else None
        except Exception:
            parsed = None
        results.append({
            'id': row['id'],
            'created_at': row['created_at'],
            'jd': row['jd'],
            'filename': row['filename'],
            'upload_type': row['upload_type'],
            'response': parsed,
        })
    return jsonify(results)


# --- AI Career Toolkit ---
toolkit_prompt = """
You are an elite career coach, professional resume writer, and technical interviewer.
Using the candidate's resume and the target job description below, produce a complete,
highly tailored job-application toolkit.

Return ONLY a valid JSON object (no markdown, no commentary) with EXACTLY these keys:

{{
  "cover_letter": "A compelling, personalized 3-4 paragraph cover letter addressed to the Hiring Manager. Reference specific strengths from the resume and the most important requirements from the job description. Confident and warm, not generic. Use \\n\\n between paragraphs.",
  "interview_questions": [
    {{"question": "A realistic interview question likely for THIS role", "tip": "A concrete 1-2 sentence tip on how this candidate should answer, referencing their background or gaps"}}
  ],
  "resume_tips": [
    "A specific, rewritten resume bullet point or improvement that weaves in a missing keyword and adds measurable impact (use numbers/metrics). Make each one copy-paste ready."
  ],
  "skill_roadmap": [
    {{"skill": "A missing or weak skill", "why": "1 sentence on why it matters for this role", "how": "A concrete, beginner-friendly way to learn or demonstrate it (free resources, a mini-project, or a certification)"}}
  ],
  "elevator_pitch": "A natural, spoken-style 60-90 word personal introduction the candidate can say when networking or when asked 'tell me about yourself', tailored to this role.",
  "linkedin": {{
    "headline": "A keyword-rich LinkedIn headline, <=120 characters, tailored to this target role.",
    "about": "A compelling LinkedIn 'About' section in 3 short paragraphs (use \\n\\n between paragraphs), first-person, weaving in strengths and target-role keywords."
  }},
  "pivot": {{
    "likely_concern": "If the candidate's background differs from the target role, the main doubt a recruiter might have (empty string if background already aligns).",
    "rebuttal": "A confident 2-3 sentence way to address that concern, reframing transferable strengths (empty string if not applicable)."
  }}
}}

Rules:
- interview_questions: 6 items, mixing behavioral and role-specific technical questions.
- resume_tips: 5 items, each actionable and quantified where possible.
- skill_roadmap: 4-6 items, prioritizing the missing keywords.
- elevator_pitch / linkedin / pivot: tailored, honest, never fabricate experience. Leave pivot fields as "" when the background already matches the target role.
- Be specific to this candidate and role. Avoid vague filler.

CANDIDATE ANALYSIS (from an earlier ATS scan):
JD Match: {match}
Missing keywords: {missing}
Profile summary: {summary}

RESUME TEXT (may be brief if the resume was an image):
{resume_text}

JOB DESCRIPTION:
{jd}

Return ONLY the JSON object.
"""


def fetch_owned_evaluation(eid):
    """Fetch an evaluation by id, scoped strictly to the logged-in owner.

    Guests get nothing by id (they can't be securely tied to an anonymous row),
    so the client falls back to the jd/resume_text/analysis it already holds.
    This prevents any cross-user / cross-visitor read of stored resume text.
    """
    uid = session.get("user_id")
    if not uid:
        return None
    return db_query(
        "SELECT jd, extracted_text, response_json FROM evaluations "
        "WHERE id = ? AND user_id = ?", (eid, uid), one=True)


@app.route('/toolkit', methods=['POST'])
@login_required
def toolkit():
    """Generate a tailored career toolkit from a prior analysis."""
    data = request.get_json(silent=True) or {}
    jd = (data.get('jd') or '').strip()
    resume_text = (data.get('resume_text') or '').strip()
    analysis = data.get('analysis') or {}

    # If an evaluation_id is supplied, prefer the stored record (ownership-scoped)
    eid = data.get('evaluation_id')
    if eid:
        row = fetch_owned_evaluation(eid)
        if row:
            jd = jd or (row['jd'] or '')
            resume_text = resume_text or (row['extracted_text'] or '')
            if not analysis and row['response_json']:
                try:
                    analysis = json.loads(row['response_json'])
                except Exception:
                    analysis = {}

    if not jd:
        return jsonify({"error": "No job description available to build the toolkit."}), 400

    missing = analysis.get('MissingKeywords') or []
    if isinstance(missing, list):
        missing = ", ".join(str(m) for m in missing) or "None identified"

    prompt = toolkit_prompt.format(
        match=analysis.get('JD Match', 'N/A'),
        missing=missing,
        summary=analysis.get('Profile Summary', 'N/A'),
        resume_text=(resume_text or '(Resume text not available — infer from the analysis above.)')[:6000],
        jd=jd[:6000],
    )

    try:
        raw = get_gemini_repsonse(prompt)
        result = extract_json(raw)
        # Normalize / guard the shape
        result.setdefault("cover_letter", "")
        result.setdefault("interview_questions", [])
        result.setdefault("resume_tips", [])
        result.setdefault("skill_roadmap", [])
        result.setdefault("elevator_pitch", "")
        result.setdefault("linkedin", {})
        result.setdefault("pivot", {})
        return jsonify(result)
    except AIRateLimitError as e:
        return jsonify({"error": str(e)}), 429
    except ValueError:
        return jsonify({"error": "The AI returned an unexpected format. Please try again."}), 502
    except Exception:
        app.logger.exception("toolkit failed")
        return jsonify({"error": "Could not generate your toolkit right now. Please try again."}), 500


# --- Experience & Keyword Coach ---
experience_prompt = """
You are an expert resume writer and career coach. Generate strong, ATS-friendly resume
bullet points for the candidate, tailored to the target job description.

Return ONLY a valid JSON object (no markdown) with EXACTLY these keys:
{{
  "bullets": [
    {{
      "source": "the raw experience/project/coursework this bullet is based on (echo a short label)",
      "polished_bullet": "A single, polished resume bullet in strong XYZ/STAR form that weaves in a relevant JD keyword and uses measurable impact. Use bracketed placeholders like [X]% or [N] for numbers the candidate must fill in.",
      "jd_keywords_covered": ["keywords from the JD this bullet demonstrates"],
      "plausibility": "strong | partial | none"
    }}
  ],
  "note": "One short, encouraging line of guidance."
}}

CRITICAL GUARDRAILS:
- NEVER invent employers, job titles, dates, or specific metrics. Use bracketed [X] placeholders for any unknown number.
- Set plausibility to 'none' and DO NOT fabricate a bullet for skills the candidate has no basis for.
- Prefer 5-7 bullets. Be specific and honest.

CANDIDATE'S RAW INPUT (projects / internships / coursework / experience, may be empty):
{raw_input}

EXISTING RESUME TEXT (may be brief if the resume was an image):
{resume_text}

TARGET FIELD / ROLE (optional): {target_field}

JOB DESCRIPTION:
{jd}

Return ONLY the JSON object.
"""


@app.route('/experience-coach', methods=['POST'])
@login_required
def experience_coach():
    """Generate tailored, honest resume bullets (great for freshers & pivots)."""
    data = request.get_json(silent=True) or {}
    jd = (data.get('jd') or '').strip()
    resume_text = (data.get('resume_text') or '').strip()
    raw_input = (data.get('raw_input') or '').strip()
    target_field = (data.get('target_field') or '').strip()

    eid = data.get('evaluation_id')
    if eid:
        row = fetch_owned_evaluation(eid)
        if row:
            jd = jd or (row['jd'] or '')
            resume_text = resume_text or (row['extracted_text'] or '')

    if not jd:
        return jsonify({"error": "No job description available."}), 400
    if not raw_input and not resume_text:
        return jsonify({"error": "Add a short description of a project, internship, or experience to build bullets from."}), 400

    prompt = experience_prompt.format(
        raw_input=(raw_input or '(none provided — base bullets on the resume text below)')[:4000],
        resume_text=(resume_text or '(not available)')[:4000],
        target_field=target_field or 'the target role',
        jd=jd[:4000],
    )

    try:
        raw = get_gemini_repsonse(prompt)
        result = extract_json(raw)
        result.setdefault("bullets", [])
        result.setdefault("note", "")
        return jsonify(result)
    except AIRateLimitError as e:
        return jsonify({"error": str(e)}), 429
    except ValueError:
        return jsonify({"error": "The AI returned an unexpected format. Please try again."}), 502
    except Exception:
        app.logger.exception("experience_coach failed")
        return jsonify({"error": "Could not generate bullets right now. Please try again."}), 500


# --- Progress stats (dashboard) ---
def _score_from_response(response_json):
    """Pull an integer 0-100 score out of a stored response_json string."""
    try:
        obj = json.loads(response_json) if response_json else {}
    except Exception:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(obj.get("JD Match", "")))
    if not m:
        return None
    return max(0, min(100, round(float(m.group()))))


@app.route('/api/stats', methods=['GET'])
def api_stats():
    """Aggregate the logged-in user's evaluations into dashboard stats."""
    uid = session.get("user_id")
    if not uid:
        return jsonify({"count": 0})

    rows = db_query(
        "SELECT created_at, response_json FROM evaluations WHERE user_id = ? ORDER BY created_at ASC",
        (uid,),
    )
    scores, last10, missing_counter = [], [], collections.Counter()
    for row in rows:
        score = _score_from_response(row["response_json"])
        if score is None:
            continue
        scores.append(score)
        last10.append({"date": row["created_at"], "score": score})
        try:
            obj = json.loads(row["response_json"]) if row["response_json"] else {}
            for kw in (obj.get("MissingKeywords") or []):
                if isinstance(kw, str) and kw.strip():
                    missing_counter[kw.strip()] += 1
        except Exception:
            pass

    if not scores:
        return jsonify({"count": 0})

    top_missing = [{"keyword": k, "count": c} for k, c in missing_counter.most_common(6)]
    return jsonify({
        "count": len(scores),
        "avg": round(sum(scores) / len(scores)),
        "best": max(scores),
        "worst": min(scores),
        "last10": last10[-10:],
        "top_missing": top_missing,
    })


# --- Authentication routes ---
# Lightweight in-memory brute-force throttle (per IP+email), best-effort.
_LOGIN_ATTEMPTS = collections.defaultdict(list)
_LOGIN_WINDOW = 300      # seconds
_LOGIN_MAX = 8           # attempts per window


def _throttled(key):
    now = time.time()
    attempts = [t for t in _LOGIN_ATTEMPTS[key] if now - t < _LOGIN_WINDOW]
    attempts.append(now)
    _LOGIN_ATTEMPTS[key] = attempts
    return len(attempts) > _LOGIN_MAX


@app.route('/api/register', methods=['POST'])
def register():
    """Step 1 of sign-up: validate the details, then email a one-time code.
    The account is NOT created until the code is verified at /api/verify-otp."""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not name:
        return jsonify({"error": "Please enter your name."}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"error": "Please enter a valid email address."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    existing = db_query("SELECT id FROM users WHERE email = ?", (email,), one=True)
    if existing:
        return jsonify({"error": "An account with this email already exists. Please sign in."}), 409

    if _throttled(f"otp-send:{request.remote_addr}:{email}"):
        return jsonify({"error": "Too many code requests. Please wait a few minutes."}), 429

    otp = _generate_otp()
    _save_pending_signup(name, email, generate_password_hash(password), otp)
    delivery = send_otp_email(email, otp, name)
    return jsonify({"ok": True, "needs_otp": True, "email": email, "delivery": delivery}), 200


@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    """Step 2 of sign-up: check the emailed code, then create + log in the user."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    otp = (data.get('otp') or '').strip()

    if _throttled(f"otp-verify:{request.remote_addr}:{email}"):
        return jsonify({"error": "Too many attempts. Please wait a few minutes."}), 429

    row = _get_pending_signup(email)
    if not row:
        return jsonify({"error": "No pending sign-up found. Please start again."}), 400
    if time.time() > row["expires_at"]:
        _delete_pending_signup(email)
        return jsonify({"error": "That code has expired. Please request a new one."}), 400
    if row["attempts"] >= OTP_MAX_ATTEMPTS:
        _delete_pending_signup(email)
        return jsonify({"error": "Too many incorrect tries. Please start sign-up again."}), 429
    if not otp or not check_password_hash(row["otp_hash"], otp):
        db_execute("UPDATE pending_signups SET attempts = attempts + 1 WHERE email = ?", (email,))
        return jsonify({"error": "Incorrect code. Please check and try again."}), 400

    # Code is valid — guard against the email being taken in the meantime, then create the account.
    existing = db_query("SELECT id FROM users WHERE email = ?", (email,), one=True)
    if existing:
        _delete_pending_signup(email)
        return jsonify({"error": "An account with this email already exists. Please sign in."}), 409

    new_id = db_execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (row["name"], email, row["password_hash"]),
    )
    _delete_pending_signup(email)
    session.permanent = True
    session["user_id"] = new_id
    return jsonify({"user": {"id": new_id, "name": row["name"], "email": email}}), 201


@app.route('/api/resend-otp', methods=['POST'])
def resend_otp():
    """Re-issue a fresh code for an in-progress sign-up."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()

    if _throttled(f"otp-send:{request.remote_addr}:{email}"):
        return jsonify({"error": "Too many code requests. Please wait a few minutes."}), 429

    row = _get_pending_signup(email)
    if not row:
        return jsonify({"error": "No pending sign-up found. Please start again."}), 400

    otp = _generate_otp()
    db_execute(
        "UPDATE pending_signups SET otp_hash = ?, expires_at = ?, attempts = 0 WHERE email = ?",
        (generate_password_hash(otp), time.time() + OTP_TTL_SECONDS, email),
    )
    delivery = send_otp_email(email, otp, row["name"])
    return jsonify({"ok": True, "delivery": delivery}), 200


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if _throttled(f"{request.remote_addr}:{email}"):
        return jsonify({"error": "Too many attempts. Please wait a few minutes and try again."}), 429

    row = db_query(
        "SELECT id, name, email, password_hash FROM users WHERE email = ?", (email,), one=True)
    if not row or not check_password_hash(row['password_hash'], password):
        return jsonify({"error": "Invalid email or password."}), 401

    session.permanent = True
    session['user_id'] = row['id']
    return jsonify({"user": {"id": row['id'], "name": row['name'], "email": row['email']}})


@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    """Email a single-use reset link if the address belongs to an account.
    Always returns the same response so attackers can't probe which emails exist."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    generic = jsonify({
        "ok": True,
        "message": "If that email is registered, a reset link is on its way.",
    })

    if not EMAIL_RE.match(email):
        return generic, 200
    if _throttled(f"reset-send:{request.remote_addr}:{email}"):
        return generic, 200

    row = db_query("SELECT id, name FROM users WHERE email = ?", (email,), one=True)
    if row:
        raw_token = secrets.token_urlsafe(32)
        db_execute(
            "INSERT INTO password_resets (token_hash, user_id, expires_at, used) VALUES (?, ?, ?, 0)",
            (_hash_token(raw_token), row["id"], time.time() + RESET_TTL_SECONDS),
        )
        reset_url = request.host_url.rstrip('/') + '/?reset_token=' + raw_token
        send_reset_email(email, reset_url, row["name"])
    return generic, 200


@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    """Set a new password using a valid, unused, unexpired reset token."""
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    password = data.get('password') or ''

    if not token:
        return jsonify({"error": "This reset link is invalid. Please request a new one."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    row = db_query(
        "SELECT token_hash, user_id, expires_at, used FROM password_resets WHERE token_hash = ?",
        (_hash_token(token),), one=True)
    if not row or row["used"]:
        return jsonify({"error": "This reset link is invalid or has already been used."}), 400
    if time.time() > row["expires_at"]:
        return jsonify({"error": "This reset link has expired. Please request a new one."}), 400

    db_execute("UPDATE users SET password_hash = ? WHERE id = ?",
               (generate_password_hash(password), row["user_id"]))
    # Burn every outstanding reset token for this user (including the one just used).
    db_execute("UPDATE password_resets SET used = 1 WHERE user_id = ?", (row["user_id"],))
    return jsonify({"ok": True, "message": "Your password has been reset. Please sign in."}), 200


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route('/api/me', methods=['GET'])
def me():
    return jsonify({"user": current_user()})


# --- Main execution ---
if __name__ == '__main__':
    # Show the email mode at startup so it's obvious whether codes get emailed or
    # only printed here. (.env is read once at startup — restart after editing it.)
    if os.getenv("GMAIL_REFRESH_TOKEN"):
        _sender = os.getenv("GMAIL_SENDER") or os.getenv("SMTP_USER")
        print(f"[startup] Email: Gmail API READY — mail sent over HTTPS from {_sender}.", flush=True)
    elif os.getenv("BREVO_API_KEY"):
        _sender = (os.getenv("BREVO_SENDER") or os.getenv("SMTP_FROM")
                   or os.getenv("SMTP_USER"))
        print(f"[startup] Email: Brevo API READY — mail sent over HTTPS from {_sender}.", flush=True)
    else:
        _h = os.getenv("SMTP_HOST")
        _u = os.getenv("SMTP_USER")
        _p = (os.getenv("SMTP_PASS") or "").replace(" ", "")
        if _smtp_configured(_h, _u, _p):
            print(f"[startup] Email: SMTP READY — verification codes will be emailed via {_u}.", flush=True)
        else:
            print("[startup] Email: CONSOLE MODE — codes are printed in this terminal, NOT emailed. "
                  "Set BREVO_API_KEY (recommended) or Gmail SMTP creds in .env and restart.", flush=True)

    # Debug is OFF by default (prevents internal-error leakage and the Werkzeug
    # debugger RCE surface). Enable locally with FLASK_DEBUG=1.
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", port=5000)
