"""
Matila prod load test. Each simulated user joins matchmaking, waits for a match,
opens a WebSocket (no Origin -> native path), then sends a message every few
seconds for the duration while draining inbound frames. Measures match rate, WS
connect rate, message send/ack success, and RTT percentiles.

Run: python loadtest.py <users.json> --users N --duration S --ramp S
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid

import aiohttp
import websockets

HOST = "matila-prod.centralindia.cloudapp.azure.com"
API = f"https://{HOST}/api/v1"
WS = f"wss://{HOST}/ws"

S = {
    "join_ok": 0, "join_err": 0, "matched": 0, "no_match": 0,
    "ws_ok": 0, "ws_err": 0, "msg_sent": 0, "msg_ack": 0, "msg_recv": 0,
    "send_err": 0, "errors": 0, "rtts": [], "err_samples": [],
}


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def get_chat(session, tok):
    async with session.post(API + "/matchmaking/join", headers=auth(tok)) as r:
        if r.status != 200:
            S["join_err"] += 1
            return None
        d = (await r.json()).get("data") or {}
    S["join_ok"] += 1
    if d.get("chat_id"):
        return d["chat_id"]
    # poll status
    for _ in range(30):
        await asyncio.sleep(1)
        async with session.get(API + "/matchmaking/status", headers=auth(tok)) as r:
            if r.status != 200:
                continue
            sd = (await r.json()).get("data") or {}
        if sd.get("state") == "MATCHED":
            return sd.get("chat_id")
    return None


async def run_user(user, session, duration):
    tok = user["idToken"]
    try:
        chat_id = await get_chat(session, tok)
        if not chat_id:
            S["no_match"] += 1
            return
        S["matched"] += 1
        uri = f"{WS}/chat/{chat_id}/?token={tok}"
        try:
            ws = await websockets.connect(uri, open_timeout=25, ping_interval=30, close_timeout=5)
        except Exception as e:
            S["ws_err"] += 1
            S["err_samples"].append("ws:" + repr(e)[:100])
            return
        S["ws_ok"] += 1
        pending = {}

        async def reader():
            try:
                async for raw in ws:
                    f = json.loads(raw)
                    ev = f.get("event")
                    if ev == "message.ack":
                        cid = (f.get("payload") or {}).get("client_message_id")
                        t0 = pending.pop(cid, None)
                        if t0 is not None:
                            S["rtts"].append(time.monotonic() - t0)
                            S["msg_ack"] += 1
                    elif ev == "message.new":
                        S["msg_recv"] += 1
            except Exception:
                pass

        rt = asyncio.create_task(reader())
        end = time.monotonic() + duration
        try:
            while time.monotonic() < end:
                cid = str(uuid.uuid4())
                pending[cid] = time.monotonic()
                await ws.send(json.dumps({"event": "message.send", "payload": {
                    "content": "load", "reply_to_message_id": None, "client_message_id": cid}}))
                S["msg_sent"] += 1
                await asyncio.sleep(4)
        except Exception as e:
            S["send_err"] += 1
            S["err_samples"].append("send:" + repr(e)[:100])
        finally:
            rt.cancel()
            try:
                await ws.close()
            except Exception:
                pass
    except Exception as e:
        S["errors"] += 1
        S["err_samples"].append("run:" + repr(e)[:100])


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("users_file")
    ap.add_argument("--users", type=int, default=100)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--ramp", type=float, default=15.0)
    a = ap.parse_args()

    users = json.load(open(a.users_file))[: a.users]
    n = len(users)
    print(f"== load test: {n} users, duration={a.duration}s, ramp={a.ramp}s ==")
    t0 = time.monotonic()
    connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for u in users:
            tasks.append(asyncio.create_task(run_user(u, session, a.duration)))
            if a.ramp and n > 1:
                await asyncio.sleep(a.ramp / n)
        await asyncio.gather(*tasks, return_exceptions=True)
    wall = time.monotonic() - t0

    rtts = S["rtts"]
    def pct(p):
        if not rtts:
            return None
        return round(sorted(rtts)[min(len(rtts) - 1, int(len(rtts) * p))] * 1000, 1)
    print("\n==== RESULTS ====")
    print(f"users={n} wall={wall:.1f}s")
    print(f"join_ok={S['join_ok']} join_err={S['join_err']}")
    print(f"matched={S['matched']} no_match={S['no_match']}  (match_rate={100*S['matched']//max(n,1)}%)")
    print(f"ws_ok={S['ws_ok']} ws_err={S['ws_err']}  (ws_connect_rate={100*S['ws_ok']//max(n,1)}%)")
    print(f"msg_sent={S['msg_sent']} msg_ack={S['msg_ack']} msg_recv={S['msg_recv']} send_err={S['send_err']}")
    if rtts:
        print(f"ack_rtt_ms p50={pct(0.5)} p95={pct(0.95)} p99={pct(0.99)} max={round(max(rtts)*1000,1)}")
    print(f"errors={S['errors']}")
    if S["err_samples"]:
        print("err_samples:")
        for e in S["err_samples"][:8]:
            print("  " + e)


asyncio.run(main())
