#!/usr/bin/env python3
"""
Gmail API One-Time Authorisation Setup
=======================================
Run this script ONCE to authorise your Google account for Gmail API access.
After that, accountcreator.py will read the saved token and work automatically.

Steps that will happen:
  1. Your browser opens a Google sign-in page.
  2. Sign in with the Gmail account that will receive Supercell verification codes.
  3. Click "Allow" when Google asks if this app may read your email.
  4. Return to this terminal — token.json will be saved automatically.
  5. This script then prints the 5 most recent inbox subjects to confirm
     that API access is working.

You can re-run this script at any time.  If token.json is already valid it
will skip the browser step and just print the recent subjects.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR))

# ---------------------------------------------------------------------------
# Import the Gmail helpers from accountcreator
# ---------------------------------------------------------------------------
try:
    from accountcreator import get_gmail_service, TOKEN_JSON, CREDENTIALS_JSON
except ImportError as exc:
    print(f"ERROR: Could not import from accountcreator.py — {exc}")
    print("Make sure accountcreator.py is in the same folder as this script.")
    sys.exit(1)


def main():
    print("=" * 60)
    print("  Gmail API Setup for Clash of Clans Account Creator")
    print("=" * 60)
    print()
    print("What is about to happen:")
    print("  1. This script checks whether token.json already exists and is valid.")
    print("  2. If not, your browser will open a Google OAuth2 consent page.")
    print("  3. Sign in with the Gmail account that receives Supercell codes.")
    print("  4. Click  Allow  when asked to grant read access to your email.")
    print("  5. Return here — token.json will be saved automatically.")
    print("  6. The 5 most recent inbox subject lines will be printed so you")
    print("     can confirm the API connection is working.")
    print()

    if not CREDENTIALS_JSON.exists():
        print("ERROR: credentials.json not found!")
        print(f"  Expected location: {CREDENTIALS_JSON}")
        print()
        print("To get credentials.json:")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Create a project (or select an existing one).")
        print("  3. Enable the Gmail API for the project.")
        print("  4. Go to APIs & Services → Credentials.")
        print("  5. Create an OAuth 2.0 Client ID (Desktop app).")
        print("  6. Download the JSON file and save it as 'credentials.json'")
        print(f"     in the folder:  {_SCRIPT_DIR}")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Check that required packages are installed before going further
    # -----------------------------------------------------------------------
    try:
        import google.oauth2.credentials  # noqa: F401
        import google_auth_oauthlib.flow  # noqa: F401
        import googleapiclient.discovery  # noqa: F401
    except ImportError:
        print("ERROR: Required Google API packages are not installed.")
        print()
        print("Install them with:")
        print()
        print("  pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
        print()
        print("Then re-run this script.")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Authorise (or re-use existing token)
    # -----------------------------------------------------------------------
    if TOKEN_JSON.exists():
        print("token.json already exists — checking if it is still valid...")
    else:
        print("No token.json found.  Opening browser for authorisation...")
        print("(The browser may take a moment to open.)")
        print()

    try:
        service = get_gmail_service()
    except Exception as exc:
        print(f"\nERROR during authorisation: {exc}")
        sys.exit(1)

    print()
    if TOKEN_JSON.exists():
        print(f"token.json is valid and saved at:  {TOKEN_JSON}")
    print("Gmail API authorisation successful!")
    print()

    # -----------------------------------------------------------------------
    # Test: list 5 most recent inbox subjects
    # -----------------------------------------------------------------------
    print("Fetching the 5 most recent inbox subjects to confirm access...")
    print()
    try:
        result = service.users().messages().list(
            userId="me",
            labelIds=["INBOX"],
            maxResults=5,
        ).execute()
        messages = result.get("messages", [])
        if not messages:
            print("  (No messages found in inbox — the API is working but inbox is empty.)")
        else:
            for i, msg in enumerate(messages, 1):
                full_msg = service.users().messages().get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From"],
                ).execute()
                headers = {
                    h["name"]: h["value"]
                    for h in full_msg.get("payload", {}).get("headers", [])
                }
                subject = headers.get("Subject", "(no subject)")
                sender = headers.get("From", "(unknown sender)")
                print(f"  {i}. Subject: {subject}")
                print(f"     From:    {sender}")
                print()
    except Exception as exc:
        print(f"  ERROR while fetching messages: {exc}")
        sys.exit(1)

    print("=" * 60)
    print("  Setup complete!")
    print()
    print("  Future runs of accountcreator.py will use token.json")
    print("  automatically — no browser will open again unless the")
    print("  token expires or is deleted.")
    print("=" * 60)


if __name__ == "__main__":
    main()
