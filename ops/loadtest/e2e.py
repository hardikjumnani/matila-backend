"""
Matila prod end-to-end validation — drives the frozen journey over real
HTTPS/wss with two Firebase-token'd users + the admin token. No Origin header on
the WS (exercises the Phase G step-0 native-socket fix).

Run: python e2e.py <tokens.json>
tokens.json = {email: {uid, idToken}} for e2e-a, e2e-b, and the admin.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import uuid

import aiohttp
import websockets

HOST = "matila-prod.centralindia.cloudapp.azure.com"
API = f"https://{HOST}/api/v1"
WS = f"wss://{HOST}/ws"

A_EMAIL = "e2e-a2@matilatest.local"
B_EMAIL = "e2e-b2@matilatest.local"
ADMIN_EMAIL = "hardik.jumnani123@gmail.com"

# Minimal valid 1x1 PNG (canonical).
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


async def api(session, method, path, token=None, json_body=None, data=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with session.request(method, API + path, headers=headers, json=json_body, data=data) as r:
        try:
            body = await r.json()
        except Exception:
            body = {"raw": await r.text()}
        return r.status, body


def data_of(body):
    return body.get("data") if isinstance(body, dict) else None


async def onboard_and_verify(session, tok, uid, gender, prefs, admin_tok, label):
    st, b = await api(session, "POST", "/auth/session", tok)
    check(f"{label}: bootstrap /auth/session", st in (200, 201), f"http={st}")
    st, b = await api(session, "PATCH", "/users/me", tok, json_body={
        "full_name": f"E2E {label}", "gender": gender, "intent": "RELATIONSHIP",
        "gender_preferences": prefs,
    })
    check(f"{label}: PATCH /users/me", st == 200, f"http={st}")
    st, b = await api(session, "POST", "/users/me/complete-onboarding", tok)
    check(f"{label}: complete-onboarding", st == 200, f"http={st}")
    st, b = await api(session, "GET", "/verification/gesture", tok)
    gesture = (data_of(b) or {}).get("gesture")
    check(f"{label}: get gesture", st == 200 and bool(gesture), f"gesture={gesture}")
    for ep in ("upload-college-id", "upload-gesture-selfie"):
        form = aiohttp.FormData()
        form.add_field("file", PNG, filename="x.png", content_type="image/png")
        st, b = await api(session, "POST", f"/verification/{ep}", tok, data=form)
        check(f"{label}: {ep}", st == 200, f"http={st}")
    st, b = await api(session, "POST", "/verification/submit", tok)
    check(f"{label}: verification submit", st == 200, f"http={st}")
    # find the request id and admin-approve
    st, b = await api(session, "GET", "/verification/status", tok)
    req = (data_of(b) or {}).get("latest_request") or {}
    req_id = req.get("id")
    st, b = await api(session, "POST", f"/admin/verifications/{req_id}/approve", admin_tok, json_body={})
    check(f"{label}: admin approve", st in (200, 201), f"http={st}")
    st, b = await api(session, "GET", "/verification/status", tok)
    vstat = (data_of(b) or {}).get("verification_status")
    check(f"{label}: status APPROVED", vstat == "APPROVED", f"status={vstat}")


async def ws_reader(sock, q):
    try:
        async for raw in sock:
            try:
                q.put_nowait(json.loads(raw))
            except Exception:
                pass
    except Exception:
        pass


async def wait_event(q, event, timeout=10):
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while True:
        remaining = end - loop.time()
        if remaining <= 0:
            return None
        try:
            frame = await asyncio.wait_for(q.get(), remaining)
        except (asyncio.TimeoutError, TimeoutError):
            return None
        if frame.get("event") == event:
            return frame


async def wait_message(q, text, timeout=12):
    """message.new can be delivered to the sender too, so match by text_content."""
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while True:
        remaining = end - loop.time()
        if remaining <= 0:
            return None
        try:
            frame = await asyncio.wait_for(q.get(), remaining)
        except (asyncio.TimeoutError, TimeoutError):
            return None
        if frame.get("event") == "message.new":
            msg = (frame.get("payload") or {}).get("message") or {}
            if msg.get("text_content") == text:
                return frame


async def main():
    toks = json.load(open(sys.argv[1]))
    a = toks[A_EMAIL]["idToken"]
    b = toks[B_EMAIL]["idToken"]
    admin = toks[ADMIN_EMAIL]["idToken"]

    async with aiohttp.ClientSession() as s:
        print("== onboarding + verification (real flow + admin approve) ==")
        await onboard_and_verify(s, a, toks[A_EMAIL]["uid"], "MALE", ["FEMALE"], admin, "A")
        await onboard_and_verify(s, b, toks[B_EMAIL]["uid"], "FEMALE", ["MALE"], admin, "B")

        print("== matchmaking ==")
        st, jb = await api(s, "POST", "/matchmaking/join", a)
        check("A join", st == 200, f"http={st} matched={data_of(jb)}")
        st, jb = await api(s, "POST", "/matchmaking/join", b)
        bdata = data_of(jb) or {}
        chat_id = bdata.get("chat_id")
        check("B join -> matched", st == 200 and bdata.get("matched") and chat_id, f"chat_id={chat_id}")
        # A discovers the match
        for _ in range(10):
            st, sb = await api(s, "GET", "/matchmaking/status", a)
            sdata = data_of(sb) or {}
            if sdata.get("state") == "MATCHED":
                chat_id = chat_id or sdata.get("chat_id")
                break
            await asyncio.sleep(1)
        check("A status MATCHED", bool(chat_id), f"chat_id={chat_id}")

        if not chat_id:
            print("!! no chat_id — skipping WS/reveal/report/rating")
            passed = sum(1 for _, ok, _ in results if ok)
            print(f"\n==== E2E: {passed}/{len(results)} passed (aborted early) ====")
            sys.exit(1)

        print("== websocket (no Origin header -> tests step-0 fix) ==")
        uri_a = f"{WS}/chat/{chat_id}/?token={a}"
        uri_b = f"{WS}/chat/{chat_id}/?token={b}"
        async with websockets.connect(uri_a, open_timeout=15) as wa, \
                   websockets.connect(uri_b, open_timeout=15) as wb:
            check("A ws connect (101)", True, "connected")
            check("B ws connect (101)", True, "connected")
            qa, qb = asyncio.Queue(), asyncio.Queue()
            ra = asyncio.create_task(ws_reader(wa, qa))
            rb = asyncio.create_task(ws_reader(wb, qb))

            # B -> A over WS
            await wb.send(json.dumps({"event": "message.send", "payload": {
                "content": "hello from B (ws)", "reply_to_message_id": None,
                "client_message_id": str(uuid.uuid4())}}))
            f = await wait_message(qa, "hello from B (ws)", 12)
            check("B->A live message.new", f is not None, "delivered" if f else "timeout")

            # A -> B over REST, delivered to B over WS
            st, mb = await api(s, "POST", f"/chats/{chat_id}/messages", a, json_body={"content": "hello from A (rest)"})
            check("A REST send 201", st == 201, f"http={st}")
            f = await wait_message(qb, "hello from A (rest)", 12)
            check("A->B REST->WS message.new", f is not None, "delivered" if f else "timeout")

            ra.cancel(); rb.cancel()

        print("== reveal eligibility ==")
        st, rb = await api(s, "GET", f"/chats/{chat_id}/reveal-eligibility", a)
        rd = data_of(rb) or {}
        check("reveal-eligibility endpoint", st == 200 and rd.get("eligibility_message_count") == 100,
              f"eligible={rd.get('eligible')} msgs={rd.get('message_count')}")

        print("== report -> ENDED ==")
        st, rb = await api(s, "POST", "/reports", a, json_body={
            "chat_id": chat_id, "category": "SPAM", "description": "e2e test"})
        check("report 201", st == 201, f"http={st}")
        st, cb = await api(s, "GET", f"/chats/{chat_id}", a)
        cstat = (data_of(cb) or {}).get("status")
        check("chat ENDED after report", cstat == "ENDED", f"status={cstat}")

        print("== rating ==")
        st, qb2 = await api(s, "GET", f"/chats/{chat_id}/rating-questionnaire", a)
        ver = (data_of(qb2) or {}).get("version")
        st, rb = await api(s, "POST", f"/chats/{chat_id}/ratings", a, json_body={
            "questionnaire_version": ver,
            "responses": {"would_chat_again": "YES", "felt_safe": "YES", "genuine": "YES"},
            "feedback_text": "e2e"})
        check("rating 201", st == 201, f"http={st} ver={ver}")

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n==== E2E: {passed}/{total} passed ====")
    print("chat_id=" + str(chat_id))
    sys.exit(0 if passed == total else 1)


asyncio.run(main())
