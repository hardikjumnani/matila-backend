"""Provision N approved load-test users (runs on the VM). Firebase user + minted
token + a pre-APPROVED, onboarded Django User row (so they can matchmake without
the image-upload verification flow). Alternating gender with complementary
preferences so they pair up. Writes [{email,uid,idToken,gender}] to --out.

Run with the prod env sourced (needs DATABASE_URL + firebase.json).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django.setup()

import firebase_admin  # noqa: E402
import requests  # noqa: E402
from django.utils import timezone  # noqa: E402
from firebase_admin import auth, credentials  # noqa: E402

from apps.users.models import User  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--api-key", required=True)
ap.add_argument("--count", type=int, required=True)
ap.add_argument("--prefix", default="loadtest")
ap.add_argument("--out", required=True)
ap.add_argument("--workers", type=int, default=16)
args = ap.parse_args()

app = firebase_admin.initialize_app(credentials.Certificate("/etc/matila/firebase.json"))
EXCHANGE = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key="
    + args.api_key
)


def net(i: int) -> dict:
    """Network-bound part (parallelised): ensure Firebase user + mint ID token."""
    email = f"{args.prefix}-{i}@matilatest.local"
    try:
        u = auth.get_user_by_email(email, app=app)
    except Exception:
        u = auth.create_user(email=email, email_verified=True, app=app)
    custom = auth.create_custom_token(u.uid, app=app).decode()
    r = requests.post(EXCHANGE, json={"token": custom, "returnSecureToken": True}, timeout=30)
    r.raise_for_status()
    return {"i": i, "email": email, "uid": u.uid, "idToken": r.json()["idToken"]}


minted: list[dict] = []
with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
    for res in ex.map(net, range(args.count)):
        minted.append(res)
        if len(minted) % 50 == 0:
            print(f"  minted {len(minted)}/{args.count}")

# ORM writes on the main thread (fast; DB is local).
out: list[dict] = []
now = timezone.now()
for res in minted:
    gender = "MALE" if res["i"] % 2 == 0 else "FEMALE"
    prefs = ["FEMALE"] if gender == "MALE" else ["MALE"]
    User.objects.update_or_create(
        firebase_uid=res["uid"],
        defaults=dict(
            college_email=res["email"],
            full_name=f"Load {res['i']}",
            gender=gender,
            intent="RELATIONSHIP",
            gender_preferences=prefs,
            onboarding_completed_at=now,
            verification_status="APPROVED",
            verified_at=now,
            account_status="ACTIVE",
        ),
    )
    out.append({"email": res["email"], "uid": res["uid"], "idToken": res["idToken"], "gender": gender})

with open(args.out, "w") as fh:
    json.dump(out, fh)
print(f"provisioned {len(out)} users -> {args.out}")
