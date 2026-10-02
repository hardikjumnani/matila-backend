# View-once image hardening — source of truth

> Goal: a view-once image is visible **exactly once**, only through our app, with
> no reusable URL that a rooted/proxied client could lift and re-download or save
> without tapping. Implemented 2026-09-30 (Option A: server-mediated delivery).

## Threat the old design had
`MessageSerializer` / `build_message_payload` returned a **1-hour Azure SAS URL**
for any `AVAILABLE` image — including un-viewed `VIEW_ONCE` — so the URL shipped in
`message.new` / `GET /messages` *before* the recipient tapped. A proxied/rooted
user could read it from the Drift DB or intercept the payload and download the
image without ever viewing it, and a captured SAS kept working after "viewing".

## The model now
1. **No URL is ever exposed for VIEW_ONCE.** For `media_visibility == VIEW_ONCE`,
   both the REST serializer and the WS payload return `media_url = null` and set
   **`media_pending = true`** (render the "tap to view" bubble). NORMAL images are
   unchanged (re-viewable → SAS is fine).
2. **Server-mediated, exactly-once delivery.** The recipient taps →
   **`POST /messages/{id}/view`**:
   - auth + chat participant + **must be the recipient** (sender is rejected) + is
     `IMAGE`/`VIEW_ONCE`;
   - the `AVAILABLE → VIEWED` transition is done under `select_for_update` in one
     transaction, so concurrent taps can't double-consume (true exactly-once);
   - the response body is the **raw image bytes** (`Cache-Control: no-store`), read
     from Blob by the backend — **no Azure URL leaves the server**;
   - the blob is **deleted immediately after** so a captured request can't be
     replayed; the sender gets the existing `message.viewed` WS event.
   - A second call → **`410 MEDIA_NOT_AVAILABLE`**.
3. **Cleanup unchanged** as a backstop: `cleanup_expired_media` still sweeps
   `VIEWED` / expired blobs.

## API contract (for the client)
- `message.new` / `GET /messages`: a VIEW_ONCE image has `media_url: null`,
  `media_pending: true`, `media_visibility: "VIEW_ONCE"`, `media_status: "AVAILABLE"`.
- On tap: `POST /messages/{id}/view` → `200` with the image **bytes** (content-type
  set); render once. On error: `410` (already viewed / consumed), `403` (not the
  recipient / sender), `404`, `410 MEDIA_NOT_AVAILABLE`.
- `message.viewed` WS event still fires to the sender when consumed.
- `POST /messages/{id}/viewed` (old JSON mark endpoint) is **removed**.

## Inherent limit (honest)
The bytes must reach the device to render once, so a fully-rooted device or a MITM
that defeats TLS can still capture that one legitimate render — no view-once
(Snapchat included) beats a fully-compromised client. This design removes the
**URL/API** attack surface and guarantees **server-enforced exactly-once**. Client
defense-in-depth: `FLAG_SECURE` during view, **TLS certificate pinning**, evict the
image from cache after showing.
