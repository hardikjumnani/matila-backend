# Reveal / Decision / Payment Flow — Source of Truth

> Canonical spec for the anonymous-chat → decision → payment → reveal journey.
> Confirmed with the product owner 2026-09-27. Code and UI state transitions
> must follow this consistently. Where this conflicts with older frozen docs,
> **this wins**.

## 1. Genders, intent, avatars
- `User.gender ∈ {MALE, FEMALE}` — **required** at onboarding.
- Intent: `FRIENDSHIP` is hidden; only `RELATIONSHIP` / `CASUAL` are selectable.
  Matchmaking still hard-filters by intent.
- Anonymous avatars are **gender-colored**: MALE = blue, FEMALE = pink. Gender is
  exposed on `other_participant` in every phase (identity is not — name/photo
  appear only once `phase == REVEALED`).

## 2. Reveal eligibility
Reveal / Safe Reveal become enabled once **either**:
- ≥ 5 minutes have elapsed since the chat started, **OR**
- **each** user has sent ≥ 5 messages (per-user count, not total).

Before eligibility: the reveal panel opens, but Reveal (and Safe Reveal for the
female) are **disabled**; Exit is enabled; Extend is **not shown**.

## 3. Windows & timers (server-authoritative)
- Anonymous window: **48h** (`current_phase_ends_at`). On expiry → `EXPIRED`
  (read-only) and the decision popup opens.
- **Extend** is only offered after the 48h window has expired.
- **Decision grace: 24h** after expiry (`decision_deadline_at = expiry + 24h`).
  If nothing completes in that window (neither chose, or one chose/paid but the
  other didn't), the chat **auto-exits**: end chat, release both, → feedback.
- Each successful Extend grants a fresh 48h window; the next expiry re-arms the
  decision phase + a fresh 24h grace. Repeatable indefinitely.
- Revealed chats are **ongoing** (no expiry timer).

## 4. Decision phase (server-persisted)
Options by context:
- **Mid-chat (window live):** Reveal · Exit · (Safe Reveal — female only). No Extend.
- **At expiry:** Reveal · Extend · Exit · (Safe Reveal — female only).
- Safe Reveal is offered **only to the female in a MALE-FEMALE chat**. Never in
  B-B or G-G.

Both users choose; each choice is persisted and made visible to the other. The
outcome is computed **once, deterministically, under a row lock**, after both
decisions exist:

```
if either == EXIT:         finalCall = EXIT
elif either == EXTEND:     finalCall = EXTEND      # EXTEND wins over any reveal
elif either == SAFE_REVEAL:finalCall = SAFE_REVEAL
elif both == REVEAL:       finalCall = REVEAL
else:                      finalCall = REVIEW      # defensive terminal → feedback
```

`REVIEW` is unreachable with the four clean options; kept only as a safe
terminal that routes to feedback (same end-state as EXIT).

## 5. Payment phase (separate from decision)
- Decision phase decides *what*; payment phase makes *both* pay for it.
- The action executes only after the required payments complete. Idempotent.
- **Prices** (from `/config`, paise): standard reveal **3900** per side; extend
  **2900** per side; safe reveal — **female 6900**, **male 2900**.

### Payment cancellation → Reveal Coins (no cash refunds, ever)
- **Both pay** → execute finalCall (`REVEAL`/`EXTEND` complete; `SAFE_REVEAL`
  enters the safe decision phase).
- **One paid, other Exits (before execution)** → do not execute; **credit the
  payer with coins** (not a refund); end chat → feedback.
  - Standard reveal payment → `+1 reveal_coin`.
  - Extend payment → `+1 reveal_coin`.
  - Safe reveal, **girl** paid (₹69) → `+1 safe_reveal_coin`.
  - Safe reveal, **boy** paid (₹29) → `+1 reveal_coin` (a boy never spends a
    safe-reveal coin).
- Coin credits are transactional and **idempotent** (keyed on payment/token) so
  retries cannot double-credit.

## 6. Coin / credit wallet
Two per-user balances:
- **`reveal_coins`** — sold in the store (bundles) and credited on cancellation.
  Spent on: a standard-reveal side (1 coin ≡ ₹39), or the **boy's** safe-reveal
  side (1 coin ≡ ₹29). Unit-based: 1 coin = one action side regardless of the
  rupee gap.
- **`safe_reveal_coins`** — girl-only, **not sold in the store**; credited only
  when a girl's safe-reveal payment is cancelled. Spent on the girl's safe-reveal
  side (1 coin ≡ ₹69).

All wallet mutations go through an append-only, idempotent ledger.

## 7. Store
- `GET /store/catalog` — the four standard-reveal bundles only:
  1 = ₹39 · 3 = ₹99 (cut ₹120) · 5 = ₹149 (cut ₹200) · 10 = ₹299 (cut ₹400).
- Safe reveal is not in the store; its inline prices come from `/config`.
- Google Play SKUs: `standard_reveal_1/3/5/10`, `safe_reveal_female`,
  `safe_reveal_male`, `chat_extension`. `reveal_unlock` is retired.

## 8. Safe Reveal decision phase (post-payment)
Payment success ≠ reveal. After both pay for SAFE_REVEAL → `SAFE_REVEAL_DECISION`:
1. When the girl is online, the **boy's name+photo are revealed to the girl only**;
   the boy stays in a waiting state ("she's reviewing…").
2. Girl sees the boy, then chooses **"Reveal yourself"** or **"Exit chat"**.
3. **Reveal yourself** → girl's name+photo revealed to the boy → chat `REVEALED`,
   reopens → (eventually) feedback.
4. **Exit chat** → girl is not revealed; chat ends (`SAFE_REJECT`) → both to
   feedback. **The girl has already seen the boy, so both payments are consumed
   with NO refund and NO coin.** (This is the only forfeit case.)

The girl's safe decision is persisted server-side and survives refresh/reconnect;
the boy remains waiting until she decides.

## 9. Terminal & persistence rules
- Terminal reasons: `USER_EXIT`, `AUTO_EXIT` (24h grace), `SAFE_REJECT`, `REPORT`.
- On any terminal state: both users get exactly one rating+feedback opportunity
  (questionnaire + ≤500-char text).
- Chats are **never deleted** — the row persists and stays visible to both.
- Once terminal, no action can reopen or mutate the chat.

## 10. Successful reveal
A completed reveal (standard, or safe "Reveal yourself") sets `status=REVEALED`,
`phase=REVEALED`; the chat **reopens and continues** with names/photos shown.
Feedback/rating happens only when the chat later ends.

## 11. Non-functional requirements
Server-authoritative timers; deterministic single `finalCall` under lock;
idempotent payment/action/coin execution; correct state after refresh/reconnect;
race-safe simultaneous decisions/payments; terminal immutability; UI derived from
backend state + role.
