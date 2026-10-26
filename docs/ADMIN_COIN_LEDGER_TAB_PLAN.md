# Admin panel - per-user coin ledger tab - plan

> Status: PLAN ONLY (2026-10-26). No code changed. A new AdminPanel tab where an
> admin selects a user and sees that user's wallet balance plus their complete coin
> transaction history: every credit (coin-pack purchase, cancellation refund, admin
> adjustment) and every spend (reveal, safe reveal, chat extension), with enough
> context to answer "how did this person get each coin and what did they spend it
> on."

## 0. What already exists (so we build only the gap)

- The production admin panel is a SEPARATE frontend ("AdminPanel", coordinated over
  EXTERNAL_BRIDGE) that consumes the backend JSON API under `/api/v1/admin/...`. So
  a new "tab" = a new JSON endpoint plus a handoff note to the AdminPanel FE. It is
  not a Django `/admin/` change (though `CoinLedgerAdmin` / `WalletAdmin` /
  `PaymentAdmin` already exist there as a dev fallback).
- Coins are already fully ledgered. `apps/payments/models.py`:
  - `Wallet` (coins, has_held_coins, updated_at).
  - `CoinLedger` (the history): `wallet` FK, `delta` (signed, +credit / -spend),
    `balance_after` (running balance IS stored per row), `reason`
    (BUNDLE_PURCHASE / CANCELLATION_CREDIT / ACTION_CONSUME / ADMIN_ADJUST), `chat`
    FK, `payment` FK, unique `idempotency_key`, `created_at`.
  - `Payment` (the cash side of a pack buy): `user`, `purpose`, `amount_in_paise`,
    `metadata` (holds `{product_id, coins}` for packs), provider ids, `status`.
- Credits link to their Payment: a coin-pack buy writes a `Payment` and a
  `CoinLedger` row linked by `CoinLedger.payment`, so "Rs 59 pack -> +10 coins" is
  fully traceable (rupees on `Payment.amount_in_paise`, coins on
  `Payment.metadata["coins"]` and `CoinLedger.delta`).
- There is NO admin coin endpoint today (the only admin coin surface is an aggregate
  revenue sum on the dashboard). The user-facing `GET /wallet` returns balance only,
  no ledger. So the tab is net-new.

## 1. The one real gap to decide on: spend context

`CoinLedger` stores `reason` but NOT `purpose`. A spend row (`ACTION_CONSUME`,
`-N`) records the `chat` but not whether it was REVEAL vs SAFE_REVEAL vs
CHAT_EXTENSION. The same is true of `CANCELLATION_CREDIT` refunds. So "what did this
coin buy" is not a first-class field today; it can only be derived by joining the
chat's `DecisionRound` (the round id is embedded in the `idempotency_key`, e.g.
`consume:<round>:<user>`).

Two ways to deliver the tab:

- **Option A - pure read-API, derive purpose at read time.** No migration. The
  ledger endpoint parses the `idempotency_key` / joins the chat's `DecisionRound` to
  label each spend. Pros: zero schema change, ships fastest. Cons: the derivation is
  brittle (depends on key format and the round still existing; a deleted chat, like
  the ones we delete to break re-match links, loses the join and the purpose becomes
  "unknown"), and refunds are even harder to label.
- **Option B (recommended) - add `purpose` + `note` to `CoinLedger`.** One migration:
  add `purpose` (nullable CharField, `PaymentPurpose` choices) and `note` (blank
  CharField) and optionally `actor_id` (for future admin adjustments). Populate going
  forward in `CreditService.spend` / `credit` and the refund path. Backfill existing
  rows with a data migration that derives purpose from the round join where possible,
  "unknown" otherwise. Pros: spend/refund context is first-class and survives chat
  deletion; the tab logic is trivial and robust; it also sets up an admin coin-adjust
  feature cleanly. Cons: one migration + a small change to the three write paths.

Recommendation: **Option B.** The owner explicitly wants to see what each coin was
spent on (their example: "used it for safe revealing"), and we routinely delete
chats to break re-match links, which breaks Option A's derivation. The change is
small and low-risk (additive nullable columns), and it future-proofs the ledger.

The rest of this plan assumes B, but the endpoints are identical under A (only the
purpose source differs).

## 2. User selection (multiple identifiers)

Reuse the existing admin user search for the picker: `GET /api/v1/admin/users?q=...`
(`AdminUserListView`). Today `?q=` matches `college_email` and `full_name` only.

The owner wants to select by "name or etc. multiple identifiers," so extend `?q=` to
also match:
- `id` (exact UUID),
- `firebase_uid` (exact),
and keep the email/name `icontains`. Small change to the one `get_queryset` filter.
The picker lists matches (id, name, email, account_status); selecting one drives the
coin endpoints by `user_id`.

## 3. New endpoints

Follow the established admin pattern (base `AdminAPIView` for detail, `ListAPIView`
for the paginated ledger, `[IsAuthenticated, IsAdminUser]`, envelope renderer, cursor
pagination). Mirror `AdminUserSafetyDetailView` (the per-user safety detail) and
`AdminLeakEventListView` (the paginated per-user list).

### 3.1 `GET /api/v1/admin/users/<uuid:user_id>/coins` - overview

Composed detail payload:
```
{
  "user": { id, full_name, college_email, account_status },
  "wallet": { coins, has_held_coins, updated_at },
  "totals": {
    "purchased_coins": <sum of + BUNDLE_PURCHASE>,
    "refunded_coins": <sum of + CANCELLATION_CREDIT>,
    "admin_adjusted_coins": <sum of + / - ADMIN_ADJUST>,
    "spent_coins": <abs sum of - ACTION_CONSUME>,
    "lifetime_rupees_paise": <sum Payment.amount_in_paise where purpose=CREDIT_PURCHASE, status=SUCCESS>
  },
  "recent_ledger": [ <latest ~10 rows, same shape as 3.2> ]
}
```
404 (`RESOURCE_NOT_FOUND`) if the user does not exist. If the user never transacted
(no wallet), return a zeroed overview with an empty ledger rather than 404, because
"everybody starts at zero coins" is a valid, expected state.

### 3.2 `GET /api/v1/admin/users/<uuid:user_id>/coin-ledger` - full history

Cursor-paginated (`?limit=`, `?cursor=`), ordered `-created_at`. Each row:
```
{
  "id", "created_at",
  "direction": "credit" | "spend",   // from sign of delta
  "delta",                            // signed, e.g. +10, -8
  "balance_after",                    // running balance, already stored
  "reason",                           // BUNDLE_PURCHASE / CANCELLATION_CREDIT / ACTION_CONSUME / ADMIN_ADJUST
  "purpose",                          // REVEAL / SAFE_REVEAL / CHAT_EXTENSION / null  (Option B column, or derived)
  "label",                            // human line, composed server-side (see below)
  "chat_id",
  "payment": {                        // present only for pack buys
    "amount_in_paise", "product_id", "coins", "provider_payment_id", "status"
  } | null,
  "note"                              // admin adjust note, if any
}
```

`label` is a ready-to-show line so the FE does not re-derive it, e.g.:
- BUNDLE_PURCHASE: "Bought 10 coins (coin_pack_10, Rs 59)"
- ACTION_CONSUME + SAFE_REVEAL: "Spent 8 coins on safe reveal"
- CANCELLATION_CREDIT: "Refunded 10 coins (reveal cancelled)"
- ADMIN_ADJUST: "Admin added 5 coins (note: ...)"

This gives the exact timeline the owner described: starts at 0, "+10 (bought
Rs 59 pack)" -> balance 10, "-8 (safe reveal)" -> balance 2, and so on.

### 3.3 (Optional) cash payments section

Under the coins-only config the direct cash-per-action path is gated OFF, so it
writes no `CoinLedger` rows (only a `Payment`). For a truly complete money history we
can add a `payments` list to the overview (all `Payment` rows for the user, incl. any
direct-action cash if the flag is ever on). Dormant today; include it as a small,
cheap addition so the tab is complete if the flag is ever flipped.

## 4. Serializer + service

- Serializer: add `CoinLedgerAdminSerializer` (and a small overview serializer) in
  `apps/admin_panel/api/serializers.py`, exposing the fields in 3.2. Pull payment
  context via `source="payment.amount_in_paise"`, `source="payment.metadata"`, etc.
  Compose `label` in the serializer or service.
- Service: add read methods to `CreditService`
  (`apps/payments/services/credit_service.py`) - `get_coin_overview(user)` and a
  `get_ledger_queryset(user)` - so the views stay thin (house style: aggregation in a
  service, as the T&S and dashboard views do). Reuse `get_balances(user)` for the
  balance block.

## 5. Files to touch

- `apps/payments/models.py` - add `CoinLedger.purpose` + `note` (+ optional
  `actor_id`) [Option B].
- `apps/payments/migrations/` - one additive migration + a backfill data migration
  [Option B].
- `apps/payments/services/credit_service.py` - populate the new fields in
  `spend`/`credit`; add the two read methods; (refund path in
  `apps/reveal/services/reveal_service.py` passes the purpose too) [Option B for the
  writes; read methods either way].
- `apps/admin_panel/api/serializers.py` - new serializers.
- `apps/admin_panel/api/management_views.py` (or a new `coin_views.py`) - the two
  views; and extend `AdminUserListView.get_queryset` for id / firebase_uid search.
- `apps/admin_panel/api/urls.py` - register the two routes (admin/... prefix, no
  trailing slash, `uuid:` converter).
- Tests (section 7).

## 6. Frontend handoff (AdminPanel, EXTERNAL_BRIDGE)

The tab is an AdminPanel FE build consuming these endpoints. Prepare an EXTERNAL_BRIDGE
note (do NOT post it until the owner says so, per standing policy) describing:
- The user picker (reuse `GET /admin/users?q=`, now matching id / firebase_uid / email
  / name).
- The two new endpoints and their exact response shapes (section 3).
- That every row carries a ready `label` and a `balance_after`, so the FE renders a
  running-balance timeline without its own math.

## 7. Tests

`apps/admin_panel/tests/` (house style: `@override_settings(ADMIN_EMAILS=[...])`,
`force_authenticate`, hit real `/api/v1/admin/...` paths, read
`response.json()["data"]`):
- Seed a user: `purchase_bundle` a pack (credit + Payment linked), `pay_with_coin` a
  REVEAL and a SAFE_REVEAL (spends), and a cancellation refund.
- Overview: asserts wallet balance, totals (purchased / spent / refunded), and the
  lifetime rupees.
- Ledger: asserts rows in order, signed `delta`, correct `balance_after` progression
  from 0, `purpose`/`label` on spends, and pack provenance (amount_in_paise + coins)
  on the buy.
- Access: non-admin -> 403; unknown user -> 404; a never-transacted user -> zeroed
  overview + empty ledger (not 404).
- User search: `?q=` finds the user by id, firebase_uid, email, and name.

## 8. Scope notes / decisions for the owner

1. **Option A vs B (section 1).** Recommend B (add `purpose`/`note` to `CoinLedger`)
   so spend context is first-class and survives chat deletion. Confirm.
2. **Read-only vs admin adjust.** This plan is read-only (view balance + history), as
   requested. A future "admin add/deduct coins" action is a natural extension and is
   why Option B also adds `note`/`actor_id`; say if you want the adjust button in
   this pass (it needs a new write endpoint + audit).
3. **Cash payments section (3.3).** Include the dormant cash-payment list for
   completeness, or leave it out until the direct-cash flag is ever used.
