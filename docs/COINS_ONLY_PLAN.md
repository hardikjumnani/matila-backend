# Coins-only monetization — plan

> Status: BACKEND SLICE DONE (2026-10-25); FE + ops pending. Builds on
> `COIN_REWORK_PLAN.md` (already implemented). This plan RETIRES the
> direct-cash-per-action path and makes coins the only internal currency, while
> the frontend keeps a "pay cash, get the action" feel by chaining
> buy-coin-pack + spend-coins behind one button.

## Implementation status (2026-10-25)

Owner decisions: 1 flag-gate; 2 leftover coins fine (balance already in the
Settings tab); 3 balance already shown, no work; 4 store screen left to FE; 5
price display + dropping cash prices deferred (owner deciding).

- **BE-1 DONE.** New feature flag `direct_action_purchase_enabled`, default
  **False** (`apps/configuration/constants.py`). `verify_google_play_purchase`
  now returns `DIRECT_PURCHASE_DISABLED` (HTTP 403, new code in
  `apps/common/responses.py`) for any chat-bound action purpose when the flag is
  off, so the direct cash-per-action endpoint is inert. `pay_with_coin`,
  `purchase_bundle` (`/store/purchase`), wallet and catalog are untouched. The
  flag auto-appears in `GET /config.feature_flags`. Tests updated; full suite
  green (627). Not yet committed/deployed at time of writing.
- **BE-2 SKIPPED (decision 5 deferred).** Per-action cash prices are still
  surfaced in `GET /store/catalog` (`actions.*.price_paise`) and
  `GET /config.pricing` (`*_price_paise`). They are now inert (no endpoint
  accepts a direct cash action purchase). Revisit once the owner settles the
  price-display approach.
- **BE-3 not done** (optional catalog topup hint).

## 0. Goal

Users never pay cash for an action directly. The only real-money product is a
**coin pack**. Every paid action (reveal, extend, safe reveal) is paid with
coins only. The app still presents a rupee price on the action button so the
user feels like a direct purchase, but under the hood that button:

1. buys the smallest coin pack that covers the action (Google Play), then
2. credits those coins, then
3. spends the action's coin cost.

If the user already holds enough coins, step 1-2 are skipped and the action is
an instant coin spend (no purchase, no Play dialog).

The coin system stays exactly as it is in the backend. We only switch off the
"pay direct cash for this one action" route and stop advertising per-action cash
prices.

## 1. What already exists (no work needed)

All implemented in the coin rework (`COIN_REWORK_PLAN.md`), verified live:

- `Wallet.coins` single unified balance; `has_held_coins` sticky flag.
- `CreditService.credit` / multi-unit `spend(amount=...)` / `has_coins` /
  `get_balances -> {coins, has_held_coins}`.
- `POST /payments/pay-with-coin` for `REVEAL` / `SAFE_REVEAL` / `CHAT_EXTENSION`,
  spends the configured per-action coin cost. (Does NOT check `payments_enabled`.)
- `POST /store/purchase` (`purchase_bundle`) buys a coin pack and credits
  `pack.coins`. (This is the funding path we KEEP.)
- `GET /store/catalog`, `GET /wallet`, `GET /chats/{id}/payments/status`.
- Config: `COIN_COST_*` (reveal 10, extend 6, safe male 8, safe female 16),
  `COIN_PACKS` (10 -> Rs 59, 30 -> Rs 149, 50 -> Rs 224, 100 -> Rs 429, each with
  a strikethrough `original_price_paise`).
- Cancellation refund credits the action's coin cost back to a lone payer
  (`RevealService._credit_unmatched_payments`). In a coins-only world this means
  a cancelled reveal returns the user's 10 coins so they can retry. No cash
  refunds, ever. Already correct.
- Reveal / decision / payment state machine. Unchanged by this plan: the payment
  phase still just needs both sides marked paid, and `pay-with-coin` already does
  that. No `RevealService` changes.

## 2. What permits direct cash per action today (the thing we switch off)

From the code map:

- **`POST /payments/verify-purchase`** (`VerifyPurchaseView` ->
  `PaymentService.verify_google_play_purchase`) accepts
  `purpose in {REVEAL, SAFE_REVEAL, CHAT_EXTENSION}` (the `_CHAT_BOUND` tuple) and
  records a cash `Payment` for that one action. This is THE direct-cash
  per-action endpoint.
- **Per-action Play SKUs** in `PLAY_PRODUCT_TO_PURPOSE` (`payments/constants.py`):
  `reveal`, `safe_reveal_female`, `safe_reveal_male`, `chat_extension`.
- **Cash prices surfaced** so the FE can draw a "pay directly" button:
  - `GET /store/catalog` returns `price_paise` per action.
  - `get_runtime_config().pricing` (the `/config` payload) exposes
    `reveal_price_paise`, `safe_reveal_*_price_paise`, `chat_extension_price_paise`.

Everything else (coins, pay-with-coin, coin packs, wallet) stays.

## 3. Backend changes (small)

No new models, no migrations.

### BE-1. Gate off the direct-cash-per-action path (reversible)

Add a feature flag `DIRECT_ACTION_PURCHASE_ENABLED`, default **False**
(config default only, no DB migration; toggleable at runtime via the admin
feature-flags surface, house style).

- In `verify_google_play_purchase`: if `purpose in _CHAT_BOUND` and the flag is
  off, reject with a clear error (e.g. `DIRECT_PURCHASE_DISABLED`, 400/409).
  With the flag off, `verify-purchase` effectively serves only `CREDIT_PURCHASE`
  (coin packs are bought via `/store/purchase` anyway, so in practice
  `verify-purchase` becomes inert for actions).
- Keep the code path intact so we can flip back if needed.

Why a flag and not a hard delete: reversible, runtime-operable, and lets us test
both models during the FE cutover. We can hard-remove the per-action SKUs and
dead accessors later in a cleanup pass.

### BE-2. Stop advertising per-action cash prices

Gate these behind the same flag (off by default) so the FE never shows a direct
cash price and cannot build a direct-cash button:

- `StoreCatalogView`: omit `price_paise` from each action entry; keep the coin
  cost per action and keep the `coin_packs` list (FE needs packs to know what to
  buy).
- `get_runtime_config().pricing`: omit the four `*_price_paise` keys; keep the
  four `coin_cost_*` values.

Leave the `get_*_price_paise` accessors and the `REVEAL_PRICE_PAISE`-family
config keys in place for now (dead but harmless, flag-reversible); remove in the
later cleanup.

### BE-3. (Optional) catalog convenience for the FE

So the FE does not re-implement "which pack covers this action," the catalog
could add per action a derived `topup` hint, e.g.
`{coins: 10, covering_pack_sku: "coins_10", covering_price_paise: 5900}`.
Pure derivation from `COIN_COST_*` + `COIN_PACKS`; optional, FE can compute it.

### BE-4. Tests

- `verify-purchase` rejects `REVEAL`/`SAFE_REVEAL`/`CHAT_EXTENSION` when the flag
  is off; still accepts `CREDIT_PURCHASE`.
- Catalog omits per-action `price_paise`; `/config` pricing omits the cash keys;
  both still carry coin costs + packs.
- Keep green: coin-pack purchase grants coins, `pay-with-coin` spends the cost,
  cancellation refunds the action's coin cost, insufficient-coins error.

### BE-5. Docs

- This file is the plan.
- Note in `COIN_REWORK_PLAN.md` / `REVEAL_FLOW_SPEC.md` /
  `PRICING_SOURCE_OF_TRUTH.md` that direct per-action cash is retired; coins are
  the only action currency; coin packs are the only real-money product.

## 4. Frontend work (the bulk)

- Remove the direct-cash-per-action flow (no more `verify-purchase` for actions).
- Action button (reveal / extend / safe reveal) orchestration, coins hidden:
  1. Read balance (`/wallet`) + coin cost (from `/config` or catalog).
  2. If `coins >= cost`: call `pay-with-coin` directly. No Play dialog. Present as
     a plain action (optionally "use your balance"); the illusion here is that it
     is effectively free because they topped up earlier.
  3. If `coins < cost`: show "Reveal for Rs X" where X is the covering pack price;
     on tap, run the Play purchase of that pack, then `/store/purchase` to credit,
     then `pay-with-coin` to spend. One button, three calls, hidden.
- Price shown on the button = the covering pack's price (what Play actually
  charges). This replaces the old per-action cash price. Must match Play exactly
  (Play policy: the displayed price has to equal the charged price).
- Decide how visible coins are (see decision 3) and whether there is an explicit
  store screen (decision 4).
- Handle leftover coins gracefully (see decision 2): after an action that leaves
  change, the next action is cheaper or free; surface that instead of hiding it.

## 5. Google Play Console / ops

- Deactivate / delist the 4 per-action managed products: `reveal`,
  `chat_extension`, `safe_reveal_male`, `safe_reveal_female`. (Pre-launch, so no
  real owned purchases to worry about.)
- Keep the 4 coin packs active and priced to match `COIN_PACKS` (Play is the
  charge authority; backend `price_paise` / `original_price_paise` are display
  only, so they must agree with Play).
- If we choose the "no leftover" route (decision 2), create the extra
  action-sized packs there too.
- `payments_enabled` must stay ON (coin-pack purchases need it). Leave
  `reveal_enabled` ON. The new `DIRECT_ACTION_PURCHASE_ENABLED` stays OFF.

## 6. The denomination problem (important, needs a decision)

The "pay exact cash for this action" illusion is clean only when an action's coin
cost maps to a single pack. It does not, everywhere:

| Action | Coin cost | Smallest covering pack | Price shown | Leftover coins |
|---|---|---|---|---|
| Reveal | 10 | coins_10 | Rs 59 | 0 (clean) |
| Safe reveal (male) | 8 | coins_10 | Rs 59 | 2 |
| Extend | 6 | coins_10 | Rs 59 | 4 |
| Safe reveal (female) | 16 | coins_30 | Rs 149 | 14 |

So female safe reveal would read Rs 149 (vs the old direct Rs 100) and leave 14
coins. Reveal is the only perfectly clean case. Options in decision 2.

## 7. Open decisions (confirm before implementation)

1. **Reversibility of the cutover**: flag-gate `DIRECT_ACTION_PURCHASE_ENABLED`
   (recommended, reversible, runtime-operable) vs hard-remove the per-action SKUs
   and dead code now.
2. **Leftover coins / denominations** (see section 6):
   a. Accept leftover + surface a subtle balance (recommended: least work,
      backend untouched, leftover acts as a built-in discount that nudges the
      next action). "Feel like direct pay" holds for reveal, softens elsewhere.
   b. Add action-sized coin packs (e.g. a 6, 8, 16 pack) so each action maps 1:1
      with zero change. More Play products + config, cleaner illusion.
   c. Retune coin costs so every action lands on a pack boundary.
3. **Coin visibility in FE**: fully hide the wallet, or show a subtle balance?
   (Drives whether leftover coins are discoverable.)
4. **Store screen**: keep an explicit "buy coins" store, or only implicit top-up
   through the action buttons?
5. **Price display**: confirm the button shows the covering pack price (reveal
   becomes Rs 59, replacing the old Rs 70), and we drop the old per-action cash
   prices from the APIs.
6. **Flags**: confirm `payments_enabled` stays ON (needed for coin-pack cash),
   `DIRECT_ACTION_PURCHASE_ENABLED` OFF.

## 8. Effort summary

- Backend: small. One flag, gate two read surfaces, reject one branch, tests,
  docs. No models, no migrations, no state-machine change.
- Frontend: the bulk. Remove direct-cash flow, build the hidden buy-then-spend
  orchestration per action, decide coin visibility.
- Ops / Play Console: delist 4 per-action products, keep 4 packs priced, (maybe)
  add action-sized packs.

Owner's read ("mostly FE + Play, little backend") is correct.
