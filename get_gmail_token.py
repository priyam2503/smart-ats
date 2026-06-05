#!/usr/bin/env python3
"""One-time helper to get a Gmail API refresh token for sending app email.

Run this ONCE on your own computer (NOT on Render):

    .venv\\Scripts\\python.exe get_gmail_token.py      (Windows)
    .venv/bin/python get_gmail_token.py               (Mac/Linux)

It asks for the OAuth Client ID and Client Secret you created in Google Cloud
Console (Credentials -> "Desktop app" OAuth client), opens your browser so you
can grant the Gmail "send" permission, then prints the environment variables to
paste into Render. Uses only the Python standard library.
"""
import json
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

SCOPE = "https://www.googleapis.com/auth/gmail.send"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/"

_received = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _received.update({k: v[0] for k, v in params.items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body style='font-family:sans-serif'>"
            b"<h2>Authorization complete.</h2>"
            b"<p>You can close this tab and return to the terminal.</p>"
            b"</body></html>")

    def log_message(self, *args):
        pass  # keep the terminal quiet


def main():
    print("=== Gmail API refresh-token helper ===\n")
    client_id = input("Paste your OAuth Client ID:     ").strip()
    client_secret = input("Paste your OAuth Client Secret: ").strip()
    if not client_id or not client_secret:
        print("\nBoth Client ID and Client Secret are required. Exiting.")
        sys.exit(1)

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    })
    print("\nOpening your browser to authorize...")
    print("(If it doesn't open, copy this URL into your browser:)\n")
    print(auth_url + "\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    server = HTTPServer(("localhost", REDIRECT_PORT), _Handler)
    print(f"Waiting for you to click 'Allow' (listening on {REDIRECT_URI}) ...")
    while "code" not in _received and "error" not in _received:
        server.handle_request()

    if "error" in _received:
        print("\nAuthorization failed:", _received.get("error"))
        sys.exit(1)

    data = urllib.parse.urlencode({
        "code": _received["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as resp:
        tokens = json.loads(resp.read().decode("utf-8"))

    refresh = tokens.get("refresh_token")
    if not refresh:
        print("\nNo refresh_token was returned. This usually means you've "
              "authorized this app before.\nRevoke it at "
              "https://myaccount.google.com/permissions and run this again.")
        sys.exit(1)

    print("\n\n========================================================")
    print(" SUCCESS - add these to Render (Environment tab):")
    print("========================================================\n")
    print(f"GMAIL_CLIENT_ID={client_id}")
    print(f"GMAIL_CLIENT_SECRET={client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={refresh}")
    print("GMAIL_SENDER=<the Gmail address you just authorized>")
    print("\n(Keep these secret - do not commit them or share them.)")


if __name__ == "__main__":
    main()
