# First-reveal discount: 8 coins for a user's first REVEAL (backend plan)

Status: PLAN ONLY (no code). 2026-11-01. Frontend changes follow separately.

Goal: a user's VERY FIRST full reveal costs 8 coins instead of 10. Every
subsequent reveal is the normal 10. Per-user, not per-chat.

## 1. How pricing works today (grounding)

- Coin prices are config-driven (`apps/configuration`):
  `COIN_COST_REVEAL = 10`, `COIN_COST_SAFE_REVEAL_MALE = 8`,
  `COIN_COST_SAFE_REVEAL_FEMALE = 16`, `COIN_COST_EXTEND = 6`.
- Resolver: `ConfigurationService.get_coin_cost(purpose, gender)`.
- Coin charge (single site): `PaymentService.pay_with_coin` -> `get_coin_cost`
  -> `CreditService.spend(...)` -> `RevealService.record_payment`.
- Reveal executes in `RevealService._execute_final_call` (FinalCall.REVEAL ->
  `mark_revealed`) once BOTH sides have paid.
- Refund (partner bails / round cancelled): `_credit_unmatched_payments`
  RECOMPUTES each side's cost via `get_coin_cost` and credits it back.
- There is also a cash path (`_resolve_amount` -> `REVEAL_PRICE_PAISE`) for
  Google Play. Out of scope here (request is about COINS).

## 2. Scope / decisions to confirm

- **D1 - which action:** apply only to the full **REVEAL** (the 10-coin one).
  SAFE_REVEAL (already 8/16 by gender) and EXTEND unchanged. [recommended]
- **D2 - when "used":** the discount is consumed only on a **successful** reveal
  (chat actually REVEALED), not merely on paying. So if a user pays 8, the
  partner bails, and coins are refunded, the user KEEPS the 8-coin price for
  their next reveal. [recommended - matches "first reveal" intent]
- **D3 - existing users:** users who already completed a reveal before this ships
  should NOT get a fresh discount -> backfill them as "already revealed". [recommended]
- **D4 - cash price:** leave `REVEAL_PRICE_PAISE` unchanged (coins only). [recommended]

## 3. Config additions (source of truth)

- `AppConfigKey.COIN_COST_REVEAL_FIRST` default **8**.
- `FeatureFlagKey.FIRST_REVEAL_DISCOUNT_ENABLED` default **True** (kill-switch so
  the promo can be turned off at runtime without a deploy).
- Wire into `APP_CONFIG_DEFAULTS`, `seed_runtime_config`, and `validators`
  (int >= 0 AND `COIN_COST_REVEAL_FIRST <= COIN_COST_REVEAL`).

## 4. "First reveal" detector (per user)

Recommended: add an explicit boolean **`User.has_completed_reveal`** (default
False; migration). Set True for each REVEAL participant inside
`_execute_final_call` (FinalCall.REVEAL branch), in the same transaction as
`mark_revealed`. Helper:

```
is_first_reveal(user) = FIRST_REVEAL_DISCOUNT_ENABLED and not user.has_completed_reveal
```

Why a flag (not derived): O(1) read at charge time, unambiguous, robust to future
reveal-mechanic changes, and makes the "consumed on success" rule explicit.
Alternative (no migration): derive from `ParticipantDecision` where
`choice=REVEAL and round.final_call=REVEAL and round.phase=RESOLVED`. Mention only.

Setting the flag in `_execute_final_call` also covers the dev payment-bypass path
(it runs the same execute), so a bypassed reveal still consumes the discount.

## 5. Price resolution - make REVEAL user-aware at BOTH charge and refund

Extend the resolver: `get_coin_cost(purpose, gender=None, *, first_reveal=False)`.
For `purpose == REVEAL` and `first_reveal` true (and flag on), return
`COIN_COST_REVEAL_FIRST`; otherwise unchanged. Callers compute the bool so the
config layer never reaches into reveal state.

- **Charge** (`pay_with_coin`): for REVEAL pass `first_reveal=is_first_reveal(user)`.
  SAFE_REVEAL / EXTEND unchanged.
- **Refund** (`_credit_unmatched_payments`) - the landmine: charge and refund
  MUST agree. Two safe options:
  - (a) Preferred: refund the amount ACTUALLY charged, read from the
    `CoinLedger` ACTION_CONSUME entry for this (chat, user, purpose) / round,
    instead of recomputing. Immune to any pricing drift.
  - (b) Acceptable: recompute with `first_reveal=is_first_reveal(user)`. Because
    the flag is set only on SUCCESS and a refund only happens when the reveal did
    NOT execute, `is_first_reveal` is still true, so it recomputes 8 = what was
    charged. Works, but is implicitly coupled to the success-only invariant.

  Recommend (a); document the invariant if (b) is chosen.

## 6. Display (backend side now; FE consumes later)

`RevealService._state_payload` currently returns NO coin cost; the FE shows the
price from the user-agnostic config snapshot (always 10). Add to the per-user
reveal state:
- `coin_cost_reveal`: effective price for THIS user (8 if first, else 10).
- `first_reveal`: bool (lets FE show a "first reveal" discount badge).

The global config pricing snapshot stays generic (10). The decision screen reads
the user-aware value from the reveal state. This is the FE contract delta to
coordinate when we do the frontend.

## 7. Edge cases / invariants

- **Per-user independence:** in a mutual reveal each side is priced on its own
  flag; both first-timers pay 8 each.
- **Consume on success only** (D2): paid-then-refunded keeps the discount.
- **Concurrency:** a user at the reveal step in two chats at once could see the
  flag unset in both and get 8 twice. Mitigate with `select_for_update` on the
  user row at charge, or accept (rare). Note.
- **Backfill (D3):** data migration sets `has_completed_reveal=True` for users
  with an existing completed REVEAL (final_call=REVEAL, phase=RESOLVED), so
  veterans are not re-granted the promo.

## 8. Tests

- First REVEAL charges 8; second charges 10.
- Mutual reveal: both first-timers charged 8 independently; one veteran + one
  first-timer -> 10 and 8.
- Refund equals charge (8) when partner bails on a first reveal, and the user's
  flag stays unset (keeps the discount).
- Successful reveal sets the flag for both REVEAL participants.
- Flag off -> always 10.
- `_state_payload` shows 8 + first_reveal=true for a fresh user, 10 + false after.
- Backfill migration marks pre-existing revealers.

## 9. Rollout

- Additive config + a defaulted boolean column -> safe migration.
- Seed `coin_cost_reveal_first` + the flag in prod; run the backfill.
- No cash-price change. Bump nothing in Veil (unrelated).

## 10. Touch list (backend)

- `apps/configuration/constants.py` - new key + flag + defaults.
- `apps/configuration/services/configuration_service.py` - `get_coin_cost`
  gains `first_reveal`; pricing snapshot unchanged.
- `apps/configuration/validators.py` - validate new key (and first <= regular).
- `apps/configuration/management/commands/seed_runtime_config.py` - seed.
- `apps/users/models.py` (+migration) - `has_completed_reveal` flag.
- `apps/reveal/services/reveal_service.py` - set flag on REVEAL execute;
  make `_credit_unmatched_payments` consistent; add fields to `_state_payload`;
  `is_first_reveal` helper.
- `apps/payments/services/payment_service.py` - pass `first_reveal` for REVEAL
  in `pay_with_coin`.
- Data migration - backfill `has_completed_reveal`.
- Tests across reveal + payments + configuration.
