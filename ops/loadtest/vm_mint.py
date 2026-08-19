"""Mint Firebase ID tokens for test users (runs on the VM; uses the service account).

Usage: python vm_mint.py --api-key KEY --emails a@x,b@x --out /tmp/tokens.json
Creates the Firebase user if absent, mints a custom token, exchanges it for an
ID token via Identity Toolkit, and writes {email: {uid, idToken}} to --out.
"""
from __future__ import annotations

import argparse
import json

import firebase_admin
import requests
from firebase_admin import auth, credentials

ap = argparse.ArgumentParser()
ap.add_argument("--api-key", required=True)
ap.add_argument("--emails", required=True, help="comma-separated emails")
ap.add_argument("--out", required=True)
args = ap.parse_args()

app = firebase_admin.initialize_app(credentials.Certificate("/etc/matila/firebase.json"))
EXCHANGE = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key="
    + args.api_key
)

out: dict[str, dict] = {}
for email in [e.strip() for e in args.emails.split(",") if e.strip()]:
    try:
        u = auth.get_user_by_email(email, app=app)
    except Exception:
        u = auth.create_user(email=email, email_verified=True, app=app)
    custom = auth.create_custom_token(u.uid, app=app).decode()
    r = requests.post(EXCHANGE, json={"token": custom, "returnSecureToken": True}, timeout=30)
    r.raise_for_status()
    out[email] = {"uid": u.uid, "idToken": r.json()["idToken"]}

with open(args.out, "w") as fh:
    json.dump(out, fh)
print(f"minted {len(out)} tokens -> {args.out}")
