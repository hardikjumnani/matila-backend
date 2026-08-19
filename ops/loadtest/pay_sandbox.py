"""
Phase H sandbox validation — drives Razorpay TEST-mode payments end-to-end on
prod. Reveal: one side pays via /payments/verify (client-verify signature), the
other via a signed webhook (payment.captured) -> chat REVEALED. Plus webhook
bad-signature (401) and replay-idempotency checks. Extension stage: same, on an
EXPIRED chat -> EXTENDED.

Signatures are constructed with the test secrets (Razorpay's verify is pure HMAC),
so no interactive checkout is needed.

  python pay_sandbox.py <tokens.json> reveal        # -> prints chat2 (left ACTIVE)
  python pay_sandbox.py <tokens.json> extend <chat2_id>
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys

import aiohttp

HOST = "matila-prod.centralindia.cloudapp.azure.com"
API = f"https://{HOST}/api/v1"

# Secrets from the environment — never hardcode them here.
#   RZP_KEY_SECRET=<razorpay key secret>  RZP_WEBHOOK_SECRET=<webhook secret>
KEY_SECRET = os.environ["RZP_KEY_SECRET"]
WEBHOOK_SECRET = os.environ["RZP_WEBHOOK_SECRET"]

EMAILS = {k: f"pay-{k}@matilatest.local" for k in ("a", "b", "c", "d")}
ADMIN_EMAIL = "hardik.jumnani123@gmail.com"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def pay_sig(order_id, payment_id):
    return hmac.new(KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def wh_sig(body):
    return hmac.new(WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


async def api(s, method, path, token=None, json_body=None, data=None, raw=None, headers_extra=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if headers_extra:
        headers.update(headers_extra)
    kw = {"headers": headers}
    if raw is not None:
        kw["data"] = raw
    elif data is not None:
        kw["data"] = data
    elif json_body is not None:
        kw["json"] = json_body
    async with s.request(method, API + path, **kw) as r:
        try:
            body = await r.json()
        except Exception:
            body = {"raw": await r.text()}
        return r.status, body


def d_(b):
    return b.get("data") if isinstance(b, dict) else None


async def onboard(s, tok, gender, prefs, admin, label):
    await api(s, "POST", "/auth/session", tok)
    await api(s, "PATCH", "/users/me", tok, json_body={
        "full_name": f"Pay {label}", "gender": gender, "intent": "RELATIONSHIP", "gender_preferences": prefs})
    await api(s, "POST", "/users/me/complete-onboarding", tok)
    await api(s, "GET", "/verification/gesture", tok)
    for ep in ("upload-college-id", "upload-gesture-selfie"):
        form = aiohttp.FormData()
        form.add_field("file", PNG, filename="x.png", content_type="image/png")
        await api(s, "POST", f"/verification/{ep}", tok, data=form)
    await api(s, "POST", "/verification/submit", tok)
    _, b = await api(s, "GET", "/verification/status", tok)
    rid = ((d_(b) or {}).get("latest_request") or {}).get("id")
    await api(s, "POST", f"/admin/verifications/{rid}/approve", admin, json_body={})
    _, b = await api(s, "GET", "/verification/status", tok)
    check(f"{label}: APPROVED", (d_(b) or {}).get("verification_status") == "APPROVED")


async def match(s, t1, t2):
    await api(s, "POST", "/matchmaking/join", t1)
    _, jb = await api(s, "POST", "/matchmaking/join", t2)
    cid = (d_(jb) or {}).get("chat_id")
    if not cid:
        for _ in range(10):
            await asyncio.sleep(1)
            _, sb = await api(s, "GET", "/matchmaking/status", t1)
            if (d_(sb) or {}).get("state") == "MATCHED":
                cid = (d_(sb) or {}).get("chat_id"); break
    return cid


async def pay_via_verify(s, tok, chat_id, purpose, initiated_from, label):
    st, ob = await api(s, "POST", "/payments/create-order", tok, json_body={
        "chat_id": chat_id, "purpose": purpose, "initiated_from": initiated_from})
    od = d_(ob) or {}
    order_id = od.get("order_id")
    check(f"{label}: create-order ({purpose})", st == 201 and bool(order_id) and od.get("dev_bypass") is False,
          f"order_id={order_id} dev_bypass={od.get('dev_bypass')}")
    pid = f"pay_test_{label}"
    st, vb = await api(s, "POST", "/payments/verify", tok, json_body={
        "razorpay_order_id": order_id, "razorpay_payment_id": pid, "razorpay_signature": pay_sig(order_id, pid)})
    check(f"{label}: verify (client-signature)", st == 200, f"http={st}")
    return order_id


async def pay_via_webhook(s, tok, chat_id, purpose, initiated_from, label, replay=False):
    st, ob = await api(s, "POST", "/payments/create-order", tok, json_body={
        "chat_id": chat_id, "purpose": purpose, "initiated_from": initiated_from})
    order_id = (d_(ob) or {}).get("order_id")
    check(f"{label}: create-order ({purpose})", st == 201 and bool(order_id), f"order_id={order_id}")
    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
        "order_id": order_id, "id": f"pay_test_{label}"}}}})
    st, wb = await api(s, "POST", "/payments/webhook", raw=body, headers_extra={"X-Razorpay-Signature": wh_sig(body)})
    check(f"{label}: webhook payment.captured", st == 200, f"http={st}")
    if replay:
        st2, _ = await api(s, "POST", "/payments/webhook", raw=body, headers_extra={"X-Razorpay-Signature": wh_sig(body)})
        check(f"{label}: webhook replay idempotent", st2 == 200, f"http={st2}")
    return order_id


async def reveal_stage(s, toks):
    admin = toks[ADMIN_EMAIL]["idToken"]
    a, b, c, d = (toks[EMAILS[k]]["idToken"] for k in ("a", "b", "c", "d"))
    print("== onboard 4 users ==")
    await onboard(s, a, "MALE", ["FEMALE"], admin, "a")
    await onboard(s, b, "FEMALE", ["MALE"], admin, "b")
    await onboard(s, c, "MALE", ["FEMALE"], admin, "c")
    await onboard(s, d, "FEMALE", ["MALE"], admin, "d")
    print("== match a-b (reveal) and c-d (extension, left ACTIVE) ==")
    chat1 = await match(s, a, b)
    chat2 = await match(s, c, d)
    check("chat1 matched", bool(chat1), chat1)
    check("chat2 matched", bool(chat2), chat2)
    print("== make chat1 reveal-eligible (send 105 messages) ==")
    for i in range(105):
        await api(s, "POST", f"/chats/{chat1}/messages", a, json_body={"content": f"m{i}"})
    _, eb = await api(s, "GET", f"/chats/{chat1}/reveal-eligibility", a)
    check("chat1 eligible", (d_(eb) or {}).get("eligible") is True, f"msgs={(d_(eb) or {}).get('message_count')}")
    print("== mutual reveal intent ==")
    await api(s, "POST", f"/chats/{chat1}/reveal-intent", a)
    _, ib = await api(s, "POST", f"/chats/{chat1}/reveal-intent", b)
    check("mutual reveal intent", (d_(ib) or {}).get("mutual") is True and (d_(ib) or {}).get("payment_required") is True)
    print("== pay: a via /verify, b via webhook ==")
    await pay_via_verify(s, a, chat1, "REVEAL", "CHAT_SCREEN", "a")
    await pay_via_webhook(s, b, chat1, "REVEAL", "CHAT_SCREEN", "b", replay=True)
    _, cb = await api(s, "GET", f"/chats/{chat1}", a)
    check("chat1 REVEALED", (d_(cb) or {}).get("status") == "REVEALED", f"status={(d_(cb) or {}).get('status')}")
    print("== webhook bad signature -> 401 ==")
    bad = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {"order_id": "x", "id": "y"}}}})
    st, _ = await api(s, "POST", "/payments/webhook", raw=bad, headers_extra={"X-Razorpay-Signature": "deadbeef"})
    check("webhook rejects bad signature", st == 401, f"http={st}")
    print(f"\nCHAT2_FOR_EXTENSION={chat2}")


async def extend_stage(s, toks, chat2):
    c, d = toks[EMAILS["c"]]["idToken"], toks[EMAILS["d"]]["idToken"]
    _, cb = await api(s, "GET", f"/chats/{chat2}", c)
    check("chat2 is EXPIRED (precondition)", (d_(cb) or {}).get("status") == "EXPIRED", f"status={(d_(cb) or {}).get('status')}")
    print("== extension: c via /verify, d via webhook ==")
    await pay_via_verify(s, c, chat2, "CHAT_EXTENSION", "CHAT_EXPIRED", "c")
    await pay_via_webhook(s, d, chat2, "CHAT_EXTENSION", "CHAT_EXPIRED", "d")
    _, cb = await api(s, "GET", f"/chats/{chat2}", c)
    check("chat2 EXTENDED", (d_(cb) or {}).get("status") == "EXTENDED", f"status={(d_(cb) or {}).get('status')}")


async def main():
    toks = json.load(open(sys.argv[1]))
    stage = sys.argv[2]
    async with aiohttp.ClientSession() as s:
        if stage == "reveal":
            await reveal_stage(s, toks)
        elif stage == "extend":
            await extend_stage(s, toks, sys.argv[3])
    p = sum(1 for _, ok in results if ok)
    print(f"\n==== {stage}: {p}/{len(results)} passed ====")
    sys.exit(0 if p == len(results) else 1)


asyncio.run(main())
