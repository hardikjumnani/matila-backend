# Unified Coin + two-tier pricing — Backend implementation plan

> Status: PLAN (BE first, FE after). 2026-10-10.
> Supersedes the pricing in `REVEAL_FLOW_SPEC.md` §5-§7 and the values in
> `PRICING_SOURCE_OF_TRUTH.md` / AI_BRIDGE [50061].

## 0. Goal (target model)

One wallet currency, **Coin**, replaces the two coin types (`reveal_coins` +
`safe_reveal_coins`). Every paid action is redeemable with coins at a fixed coin cost,
OR bought directly with cash. Coins are sold in a store as packs.

Coin costs (per user):
- Reveal: **10**
- Safe reveal: **8** (man) / **16** (woman)
- Extend: **6**

Direct cash prices (per user), NEW values:
- Reveal: ₹70 (7000 paise)
- Extend: ₹50 (5000)
- Safe reveal: ₹50 man (5000) / ₹100 woman (10000)

Coin packs (store), SKUs `coin_pack_10/30/50/100`:
- 10 coins: ₹59 (5900), cut ₹70 (7000)
- 30 coins: ₹149 (14900), cut ₹210 (21000)
- 50 coins: ₹224 (22400), cut ₹350 (35000)
- 100 coins: ₹429 (42900), cut ₹700 (70000)

UX (FE later): low/new users see the direct cash price and are nudged to the store; a
user with coins (or short on coins) is offered "top up" or "buy directly". Both paths
stay available per action.

## 1. Open inputs (confirm before/within impl)

1. 50-coin pack: RESOLVED -> ₹224 (cut ₹350).
2. Confirm both paths per action stay (coins OR direct cash). Assumed yes.
3. Wallet data migration: new `coins = reveal_coins + safe_reveal_coins`. Assumed yes.
4. Cancellation refund: credit the action's coin cost (10/8/16/6) to a lone payer,
   regardless of whether they paid by coin or cash. (Today it credits exactly 1 coin.)
   Confirm this "refund in coins at action cost" rule.
5. Google Play: both the 4 coin packs AND the direct per-action purchases are Play
   managed products; ops creates/prices them in Play Console. Confirm.
6. This supersedes AI_BRIDGE [50061]; FE will be re-notified after BE lands.

## 2. Data model + migration (`apps/payments/`)

- `Wallet` (`models.py` L94-114): add `coins` PositiveIntegerField(default=0); remove
  `reveal_coins` and `safe_reveal_coins` after data copy.
- `CoinType` enum (`enums.py` L32-38): collapse to a single member `COIN = "COIN"`
  (keep the enum so `CoinLedger.coin_type` and the credit API stay valid with minimal
  churn).
- `CoinLedger` (`models.py` L117-162): keep the table; new rows use `coin_type="COIN"`;
  data-migrate existing rows' `coin_type` to `"COIN"`. `balance_after` on old rows is
  historical; leave as recorded.
- `CoinLedgerReason`: rename `REVEAL_CONSUME` -> `ACTION_CONSUME` (generic spend);
  `BUNDLE_PURCHASE` stays (coin-pack purchase) or rename to `PACK_PURCHASE`; keep
  `CANCELLATION_CREDIT`, `ADMIN_ADJUST`.
- Migrations (3 steps): (a) add `coins` column; (b) data migration
  `coins = reveal_coins + safe_reveal_coins` and `coin_ledger.coin_type = "COIN"`;
  (c) drop the two old columns + AlterField for enum choice changes. Pre-launch prod has
  flags off and little real wallet data, so a clean drop is acceptable.

## 3. CreditService (`services/credit_service.py`)

- Remove `_FIELD_BY_COIN`; operate on the single `coins` field.
- `get_balances(user)` -> **`{"coins": N}`** (was `{reveal_coins, safe_reveal_coins}`).
  BREAKING shape change; all consumers below + FE must follow.
- `credit(*, user, amount, reason, idempotency_key, chat=None, payment=None)` -> drop the
  `coin_type` param.
- Replace 1-coin `consume` with **`spend(*, user, amount, reason, idempotency_key, chat=None)`**:
  multi-unit debit; `INSUFFICIENT_COINS` if `coins < amount`; idempotent replay is a
  no-op success; writes one ledger row with `delta = -amount`.
- `has_coins(user, amount) -> coins >= amount`.

## 4. Coin costs + pricing config (`apps/configuration/`)

- New `AppConfigKey`s: `COIN_COST_REVEAL`, `COIN_COST_SAFE_REVEAL_MALE`,
  `COIN_COST_SAFE_REVEAL_FEMALE`, `COIN_COST_EXTEND`.
- Replace `STANDARD_REVEAL_BUNDLES` -> `COIN_PACKS` (list of
  `{sku, coins, price_paise, original_price_paise}`), SKUs `coin_pack_10/30/50/100`.
- Update direct-cash defaults: `REVEAL_PRICE_PAISE=7000`, `CHAT_EXTENSION_PRICE_PAISE=5000`,
  `SAFE_REVEAL_MALE_PRICE_PAISE=5000`, `SAFE_REVEAL_FEMALE_PRICE_PAISE=10000`.
- `ConfigurationService`: add `get_coin_cost(purpose, gender)`, `get_coin_packs()`,
  `get_pack_by_sku()`; keep the cash-price accessors.
- `get_runtime_config()` pricing block: add the four coin costs alongside the four cash
  prices, so the decision/endgame screen can show "10 coins or ₹70".
- All of this is runtime-operable via admin app-config (per `PRICING_SOURCE_OF_TRUTH.md`).

## 5. PaymentService (`services/payment_service.py`) + SKU map (`payments/constants.py`)

- `pay_with_coin(*, user, chat_id, purpose)`:
  - Allow **REVEAL, SAFE_REVEAL, and EXTEND** (add EXTEND; remove the two-coin-type
    branch at L290-293).
  - Resolve the coin cost from config (per purpose + gender for safe reveal).
  - `credits.spend(amount=cost, reason=ACTION_CONSUME, idempotency_key=f"consume:{round_id}:{user.id}")`.
  - On success -> `reveal.record_payment(paid_with_coin=True)`.
- Direct cash via Google Play:
  - `verify_google_play_purchase`: add REVEAL as a chat-bound payable (today only
    SAFE_REVEAL/CHAT_EXTENSION). `_CHAT_BOUND` becomes all three.
  - Add a direct **reveal** Play SKU to `payments/constants.py` `PLAY_PRODUCT_TO_PURPOSE`
    (REVEAL has no cash SKU today). Keep `safe_reveal_male/female`, `chat_extension`.
  - `_resolve_amount` returns the new cash prices.
- Store: `purchase_bundle` -> `purchase_coin_pack`: credits the unified coin
  (`amount = pack.coins`, no coin_type), Payment `purpose=CREDIT_PURCHASE`,
  `metadata={product_id, coins}`. Map `coin_pack_*` SKUs -> `CREDIT_PURCHASE` in
  `payments/constants.py`.
- `PAYMENTS_DEV_BYPASS` token-skip and the `record_payment` wiring are unchanged.

## 6. RevealService (`services/reveal_service.py`)

- Remove `_cancellation_coin_type` (single coin).
- `_credit_unmatched_payments`: for each lone paid side, `credits.credit(amount = <action
  coin cost for that side>, reason=CANCELLATION_CREDIT, idempotency_key=f"cancel:{round}:{user}")`.
  Action cost by `final_call` + the user's gender for safe reveal. (Replaces the fixed +1
  coin.) Safe-reveal-after-boy-seen still forfeits (no credit), unchanged.
- `_PAYABLE`, `record_payment`, `_execute_final_call`, and the `ENDGAME_PAYMENT_BYPASS`
  hook are unchanged.

## 7. API contract (`payments/api/`) — changes FE must follow

- `GET /wallet` -> `{"coins": N}`.
- `GET /chats/{id}/payments/status` -> `balances` becomes `{"coins": N}`.
- `GET /store/catalog` -> restructure to:
  `{ "coin_packs": [ {sku, coins, price_paise, original_price_paise} ],
     "actions": { "reveal": {coins, price_paise},
                  "safe_reveal_male": {coins, price_paise},
                  "safe_reveal_female": {coins, price_paise},
                  "extend": {coins, price_paise} } }`
  (so FE has coin cost + direct price per action in one place).
- `GET /config` pricing block: add the four coin costs next to the four cash prices.
- `PayWithCoinRequestSerializer`: add `EXTEND` to the allowed `purpose` choices.
- `VerifyPurchaseRequestSerializer`: `REVEAL` now valid (direct cash reveal).
- `StorePurchaseView`/`PayWithCoinView` responses: `balances` -> `{"coins": N}`.

## 8. Admin / revenue (`admin_panel/services/dashboard_service.py`)

- `_revenue_stats` keeps per-purpose sums; `reveal_paise` now becomes non-zero (direct
  reveal SKU exists). Optionally add a coin-economy stat (coins outstanding / sold)
  later. The admin pricing screen (EXTERNAL_BRIDGE B0001) should also edit the new
  coin-cost keys and `coin_packs`.

## 9. Docs to update

- `REVEAL_FLOW_SPEC.md` §5-§7: rewrite for the unified coin, per-action coin cost,
  extend-by-coin, new prices, coin packs, and the cancellation-refund rule.
- `PRICING_SOURCE_OF_TRUTH.md`: unified coin + coin costs + packs + two paths.
- This file is the implementation plan.

## 10. Test surface to rewrite (`apps/payments/tests`, `apps/reveal/tests`)

- Balances shape `{coins}` everywhere (wallet, store, chat status, reveal cancellation
  asserts) — today they assert `reveal_coins` / `safe_reveal_coins`.
- New prices (7000 / 5000 / 5000 / 10000) in `test_payment_api`, `test_payment_service`,
  `test_google_play`.
- Coin costs + multi-unit spend: pay reveal (10), safe reveal (8/16), **extend (6)** with
  coins; `INSUFFICIENT_COINS` when short of the multi-coin cost.
- Direct cash reveal SKU path (new).
- Coin pack purchase grants N coins to the single balance.
- Cancellation credits the action cost (not +1). Update
  `test_exit_during_payment_credits_payer_coin`, `test_safe_reveal_exit_before_both_pay_credits_correct_coins`,
  `test_auto_exit_credits_lone_payer`.
- `EndgamePaymentBypassTests` should still pass unchanged (bypass skips payment).

## 11. Sequencing

1. Config (coin costs, packs, new cash prices) + enums + Wallet model + 3-step data
   migration + CreditService (unified, multi-unit `spend`).
2. PaymentService (pay_with_coin all actions + multi-unit; direct reveal SKU;
   coin-pack purchase) + SKU map; RevealService cancellation refund.
3. API shapes (wallet / catalog / config / serializers / responses) + admin.
4. Docs + full test rewrite to green.
Then FE work (wallet shape, catalog shape, coin cost + direct price display, store,
top-up-or-buy-direct UX) and ops (Play Console SKUs + prices).

## 12. Risks / notes

- **Breaking API shape** (`balances`, catalog): BE and FE must land in lockstep, or gate
  the new shape behind a version. Since FE follows BE here, plan a short window.
- **Play Console SKUs**: coin packs + direct reveal are new managed products; the
  charged amount comes from Play, so ops must set prices to match. Backend owns
  coins-per-pack, coin costs, and the strikethrough original.
- **Historical CoinLedger** keeps old per-type rows; only the live balance is unified.
- Pre-launch: prod flags are off and wallet data is minimal, so the migration is low
  risk; still write it reversibly where possible.
