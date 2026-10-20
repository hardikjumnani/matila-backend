# Pricing: backend-owned, operated, FE fetches and shows

> Status: plan / contract. 2026-10-10.
> UPDATE 2026-10-10: the product now uses a single unified **Coin** plus a direct
> cash price per action, and the store sells coin packs. See `COIN_REWORK_PLAN.md`
> for the model and the final numbers. The ownership and delivery principles here
> (backend owns prices, runtime-operable, FE fetches and never hardcodes) are
> unchanged and now also cover the coin costs (`/config` pricing includes them) and
> the coin packs (`/store/catalog`).

Goal: the backend is the single source of truth for all prices. Prices are operated
(changed) server-side at runtime with no deploy. The frontend never hardcodes a price;
it fetches and renders what the backend serves.

## 1. Single source of truth
All prices live in backend `app_config` (keys in `apps/configuration/constants.py`):
- `reveal_price_paise` (standard reveal, 1 coin)
- `chat_extension_price_paise` (extend)
- `safe_reveal_female_price_paise`, `safe_reveal_male_price_paise`
- `standard_reveal_bundles` (list of `{sku, coins, price_paise, original_price_paise}`)

All amounts are integers in paise. No price is hardcoded anywhere, on the backend or
the client. The code defaults are only the fallback for a fresh database; the DB rows
are the live values.

## 2. Operated at runtime (no deploy)
Prices are changed through the admin config API, which invalidates the cache and writes
an audit entry (`ConfigurationService.set_config`):
- `PUT /api/v1/admin/app-config/{key}` with `{ "value": <int or list> }`
- `GET /api/v1/admin/app-config` to read the effective values
A change takes effect on the next client fetch. A pricing screen in the admin panel
(future, built on these endpoints) lets non-engineers operate prices.

## 3. Delivery to the frontend (fetch and show only)
Two read endpoints, both already live:
- `GET /api/v1/config` -> `pricing`:
  `reveal_price_paise`, `chat_extension_price_paise`,
  `safe_reveal_female_price_paise`, `safe_reveal_male_price_paise`.
  Used on the decision / endgame screens.
- `GET /api/v1/store/catalog`:
  `standard_reveal_bundles[]` (each `{sku, coins, price_paise, original_price_paise}`)
  and `safe_reveal.female_price_paise` / `male_price_paise`.
  Used on the store screen.

FE contract:
- Fetch on app launch and when opening the store or endgame screens; cache with a short
  TTL; always render from the fetched values.
- Format paise to rupees for display. Use `original_price_paise` for the struck-through
  price; when it equals `price_paise`, show no cut.
- Never hardcode a price. If the backend changes a price, the client shows it on the
  next fetch with no app update.

## 4. Flow-to-price map
- Standard reveal: `reveal_price_paise` (or spend 1 reveal coin). Coins are bought from
  `standard_reveal_bundles`.
- Safe reveal: `safe_reveal_female_price_paise` / `safe_reveal_male_price_paise`.
- Extend: `chat_extension_price_paise`.

## 5. Google Play reconciliation (one open decision)
Coin bundles and safe reveal are real Google Play managed products. For the ACTUAL
charge, Google Play is the charging authority and shows the user's localized price. The
backend `app_config` prices are the intended INR amounts plus the strikethrough original
and the coins-per-SKU mapping. Two options for what the client displays:
- (A, simpler, current) Show the backend INR prices everywhere; ops keeps the Play
  Console managed-product prices in sync to the same amounts.
- (B, later) Show Play's localized `ProductDetails` price for the live price and keep
  the backend `original_price_paise` for the strikethrough.
Recommendation: A now, revisit B for localization. Either way the backend owns coins
granted per SKU and the strikethrough original; the owner keeps Play Console in sync.

## 6. Non-goals
- No price constants in client code or in service code paths (always read `app_config`).
- The backend does not depend on the client for any price.
