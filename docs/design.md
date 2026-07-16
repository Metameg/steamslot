# SteamSlot — MVP Design & Plan

## Context

We're building a web app modeled on **Rips by Triumph** (a slot-machine / loot-box app for
physical Pokémon cards), but for **Steam games** instead of cards. A user pays real money to
open a randomized "pack," a slot-machine reveal lands on a game they've won, and they can either
**buy it back** for its full value (credited to their wallet) or **redeem** it as a real Steam CD
key. The goal of this stage is a **validation MVP**: build the real core loop with real money and
real (just-in-time) fulfillment, while deliberately deferring heavy compliance machinery
(formal KYC/AML vendor, gambling licensing, tax reporting) until after the idea is proven.

Immediate deliverable requested by the user: an **interactive ER-diagram webpage** of the schema
below, produced as soon as planning is approved.

## Product Overview & Core Loop

1. User deposits money (Stripe) → wallet balance.
2. User **buys a pack** of a chosen tier → `packs` row created (`unopened`), wallet debited, odds
   table version locked to the pack.
3. User **opens (rips) the pack** → server-authoritative roll commits an outcome → a `pull` is
   written with the won game and its locked value → reveal animation lands on that result.
4. User chooses per win:
   - **Buyback**: 100% of the game's locked MSRP credited to wallet balance. Instant, internal.
   - **Redeem**: enqueues a `redemption_request`; admin buys a portable CD key just-in-time from
     an authorized retailer and delivers it in-app for the user to activate themselves.
5. User may **withdraw** wallet balance to bank/PayPal (Stripe payout) — the only path where real
   money leaves, gated by Stripe's identity checks + $5 min / daily cap.

## Key Decisions (resolved during brainstorming)

- **Model**: real money, real Steam keys. Buyback pays **100% of fair value**.
- **Stage**: validation MVP — defer formal KYC/AML, licensing, tax reporting.
- **Key sourcing**: official/authorized retailers only (Humble/Fanatical/GMG/publisher). **No
  pre-stocked inventory** — fulfillment is **just-in-time**: when a user redeems, admin buys a
  **portable CD key** at that moment and pastes it in. (Explicitly NOT Steam account-to-account
  gifting, which hits friend-wait / regional / fraud-flagging / trapped-wallet problems.)
- **Delivery**: reveal a CD key string the user activates via "Activate a Product on Steam."
- **Age/KYC**: self-attested 18+ checkbox at signup + Stripe-level card/payout identity checks
  only. No custom identity vendor for MVP.
- **Pricing basis**: a won game's value = the game's **regular/MSRP price** (one canonical region,
  e.g. US), **snapshotted onto the pull at win-time** and locked. This single choice:
  - kills **vault-and-wait** arbitrage (value frozen at win),
  - makes **buyback-then-rebuy** irrelevant (we pay exactly the budgeted value; user's downstream
    shopping is their business; house edge is in the odds),
  - caps **JIT redemption cost** (regular price is the ceiling; sales only make fulfillment cheaper).
  - Requires only a **slow batch price sync** (daily/weekly) from Steam's public `appdetails` API,
    not a real-time feed.
- **House edge**: comes entirely from `EV(pack) < price(pack)`, independent of inventory. Odds
  tables must be tuned so expected payout < pack price; an admin EV calculator enforces this.
- **RNG**: server-authoritative CSPRNG, tamper-proof. No provably-fair seed-commit/reveal for MVP.
- **Tech stack**: **React (Vite) frontend + Python/FastAPI backend + Postgres + Stripe**
  (separate frontend and backend services). Server owns all RNG and money logic.

## Tech Stack Detail

- **Frontend**: React + Vite SPA. Talks to backend over a versioned REST API. Reveal animation is
  purely presentational — it never determines or receives the outcome early.
- **Backend**: FastAPI (Python). Pydantic for runtime request/response validation at every money
  boundary. Owns Postgres and all Stripe integration.
- **DB**: Postgres. All money as **integer minor units (cents) + currency code** — never floats.
- **Payments**: Stripe Payments (deposits, verified via signed webhooks), Stripe Connect/payouts
  (withdrawals).
- **Auth**: email+password (modern KDF hash) or OAuth; signed HTTP-only cookie or JWT sessions.

## Database Schema (11 tables)

Conventions: all money = `int` cents + `currency`. `ledger_entries` is append-only and is the
source of truth for balances; `users.wallet_balance_cached` = sum of that user's ledger entries.

### Identity & money

**users**
`id` · `email` · `password_hash` (nullable if OAuth) · `display_name` · `role` (user/admin) ·
`age_attested` (bool) · `terms_accepted_at` · `stripe_customer_id` ·
`stripe_connect_account_id` (nullable — set on first withdrawal) · `wallet_balance_cached` (int
cents) · `created_at` · `updated_at`

**ledger_entries** (append-only, immutable)
`id` · `user_id`→users · `entry_type` (deposit / pack_purchase / buyback_credit / withdrawal /
refund / admin_adjustment) · `amount` (signed int cents; + credit, − debit) · `currency` ·
`reference_type` + `reference_id` (polymorphic link to pack / pull / withdrawal that caused it) ·
`idempotency_key` (unique) · `created_at`

### Catalog & odds

**games** (catalog — no stocked keys)
`id` · `steam_app_id` · `title` · `regular_price` (int cents, canonical region) · `currency` ·
`region` · `header_image_url` · `is_eligible` (bool) · `price_synced_at` · `created_at` ·
`updated_at`

**pack_types** (tier definition)
`id` · `name` (Basic/Silver/Gold) · `price` (int cents) · `description` · `is_active` ·
`created_at` · `updated_at`

**odds_tables** (versioned snapshot of a pack_type's odds)
`id` · `pack_type_id`→pack_types · `version` · `is_published` · `published_at` · `created_at`

**odds_bands** (rows within an odds_table)
`id` · `odds_table_id`→odds_tables · `name` (Common…Grail) · `probability` (decimal weight) ·
`min_price` (int cents) · `max_price` (int cents) · `sort_order`

Rolling: pick a band by probability, then a random `is_eligible` game whose `regular_price` falls
in that band's `[min_price, max_price]`. If a band has no eligible game in range, exclude it and
re-normalize; record the effective probabilities used in `pulls.roll_metadata`.

### Gameplay

**packs** (held instance the user owns until they rip it)
`id` · `user_id`→users · `pack_type_id`→pack_types · `odds_table_id`→odds_tables (**locked at
purchase**) · `price_paid` (int cents) · `status` (unopened / opened) · `purchased_at` ·
`opened_at` (nullable)

**pulls** (committed result of opening one pack)
`id` · `pack_id`→packs (unique) · `user_id`→users · `game_id`→games · `odds_band_id`→odds_bands ·
`locked_value` (int cents — MSRP snapshot at win) · `status` (vaulted / bought_back /
redeem_requested / redeemed) · `roll_metadata` (JSON: rng details, effective probabilities) ·
`created_at`

### Fulfillment & payments

**redemption_requests** (admin JIT worklist)
`id` · `pull_id`→pulls (unique) · `user_id`→users · `status` (pending / fulfilled / cancelled) ·
`delivered_key` (encrypted, nullable) · `fulfilled_by`→users (admin) · `requested_at` ·
`fulfilled_at` · `notes`

**withdrawals**
`id` · `user_id`→users · `amount` (int cents) · `status` (pending / paid / failed) ·
`stripe_payout_id` · `requested_at` · `processed_at`

**stripe_events** (webhook idempotency & audit)
`id` · `stripe_event_id` (unique) · `type` · `payload` (JSON) · `status` · `processed_at`

Deposits have no table: a deposit = a `stripe_events` row (confirmed payment) + a `ledger_entries`
row.

## Server-Authoritative RNG & Reveal

Strict sequence, so the client can never determine or peek at the outcome:
1. Client sends "open pack N" with an **idempotency key** (double-tap/retry can't roll twice).
2. Server, in **one DB transaction**: validates ownership + unopened status, rolls via CSPRNG
   against the pack's locked odds table, picks the game, snapshots `locked_value`, writes the
   `pull`, flips pack to `opened`. Committed and final.
3. Server returns the result.
4. Client plays the slot animation and lands on the already-decided game.

## Money Integrity Rules

- Pack purchase, roll, buyback, deposit, withdrawal wrapped in DB transactions with **row-level
  locking** on the wallet — no double-spend / double-credit under concurrency or retries.
- **Idempotency keys** on every Stripe webhook and every open/buyback request.
- Stripe **webhooks are the source of truth for money-in**, signature-verified and reconcilable
  against the ledger.
- Balance can never go negative; every mutation writes a ledger entry.

## Admin Operations (no admin UI for MVP — deferred)

The admin **panel/UI is out of scope for the MVP** and will be built later. The operations it would
cover still need to happen, so for the MVP they're handled without a UI:

- **Games catalog + odds tables**: seeded via scripts/migrations (add games, set `is_eligible`,
  define pack tiers/bands/probabilities/price ranges, publish an odds version). The **EV check**
  (`EV < pack price`) runs as a validation in the seed/publish script rather than a live UI.
- **Price sync**: a scheduled/CLI batch job hitting Steam `appdetails`.
- **Redemption fulfillment**: for MVP, pending `redemption_requests` are worked directly against
  the DB (or a minimal internal script) — admin buys the key and writes it to `delivered_key`.
- **Ledger / withdrawals audit**: direct DB queries for now.

A proper role-gated admin panel (catalog/odds editor with live EV calculator, redemption queue,
ledger views) is a **post-MVP** addition.

## Catalog Seeding (MVP)

**Goal**: populate `games` with a modest set of real Steam titles spanning price bands — enough to
exercise the odds engine across bands, not a comprehensive catalog.

**Selection — curated app IDs.** A hand-picked list of ~40 well-known Steam app IDs chosen to span
target MSRP buckets, with **≥5–6 priced titles per bucket** so every odds band has multiple
eligible games (exercises the roll's "pick a random eligible game in the band's price range" +
band re-normalization path). Representative examples (prices approximate; real MSRP comes from the
fetch):
- **~$1–5**: Vampire Survivors, Among Us
- **~$5–15**: Portal 2, Terraria, Balatro, Stardew Valley, Hollow Knight
- **~$15–30**: Hades, Celeste, Cuphead, Inscryption, Slay the Spire, Dead Cells, Outer Wilds
- **~$30–50**: The Witcher 3, Disco Elysium, Factorio, RimWorld, Tunic
- **~$50–70**: Elden Ring, Cyberpunk 2077, Baldur's Gate 3, Red Dead Redemption 2, Sekiro

**Prices — one-time live-fetch → committed fixture.**
- Reusable fetcher `fetch_game(appid, cc="us")`: GET
  `store.steampowered.com/api/appdetails?appids={id}&cc=us&l=en`; check `data[appid].success`;
  read `name`, `price_overview.initial` (**regular MSRP in cents — NOT `final`**, per the
  locked-value pricing decision), `price_overview.currency`, `header_image`. Skip/flag entries that
  are `is_free` or lack `price_overview` (unreleased/region-locked). Small politeness delay between
  calls.
- `scripts/refresh_catalog_fixture.py` (developer tool, run occasionally): runs `fetch_game` over
  the curated ID list and writes a **committed fixture** (`data/catalog_seed.json`) of
  `{steam_app_id, title, regular_price_cents, currency, header_image_url}`. This is the **only**
  place the one-time live-fetch happens.

**Seed — offline, schema-current, reproducible.**
- `scripts/seed_catalog.py`: reads the committed fixture and **upserts** into `games`
  (`ON CONFLICT (steam_app_id) DO UPDATE`), setting `is_eligible=true`, `region='US'`,
  `currency='USD'`, `price_synced_at=now`. Idempotent, **no network at seed time**. Runs **after
  migrations**, so it always matches the current schema.
- Fresh dev/CI setup = run migrations, then run seed → identical, offline catalog every time. The
  reproducibility artifact is the checked-in fixture, not a DB dump (dumps would go stale against
  the rapidly-evolving MVP schema).

**Live prices — the recurring price-sync job (already planned).** Live prices are the sync job's
responsibility: it iterates existing `games`, calls the same `fetch_game`, and updates
`regular_price` + `price_synced_at` on its cadence. Run it once after seeding to true-up a live DB.
Deterministic tests run against a freshly-seeded (un-synced) DB or the fixture; a running dev/prod
DB may drift from the fixture as the sync updates it — intended.

**Notes / edge cases.**
- `appdetails` is Steam's public-but-undocumented storefront endpoint; ~40 calls run rarely sit
  well within its soft rate limit.
- Single canonical region (US/USD) for MVP, matching the pricing decision.
- The `games` table as a whole is read-mostly; the full dev/test DB still wants per-developer /
  per-CI isolation (tests write `packs`/`pulls`/`ledger_entries`), so avoid a single shared
  network DB as the test substrate.

## Testing Priority

Focus on the money + RNG core:
- **Odds engine**: over large samples the empirical distribution matches the published table;
  `EV < pack price` for every published table; band exclusion/re-normalization correct.
- **Ledger**: `wallet_balance_cached` always equals sum of entries; never negative; idempotency
  holds under replay.
- **Concurrency**: parallel opens/buybacks cannot double-spend or double-credit.
- **Integration**: full deposit → buy → open → buyback/redeem → withdraw loop against Stripe test
  mode.
- Frontend reveal animation lightly tested (presentational).

## Explicit Non-Goals (deferred past MVP)

- **Admin panel/UI** (catalog+odds editor, redemption queue, ledger views) — handled via
  seed scripts / direct DB for MVP.
- Formal KYC/AML identity vendor, gambling licensing, tax (1099) reporting.
- Provably-fair RNG verification.
- Pre-stocked key inventory / automated procurement.
- Per-user regional pricing (single canonical region for MVP).
- Steam account linking / direct-to-library delivery.
- Native mobile apps.

## Immediate Deliverable

An **interactive ER-diagram webpage** rendering the 11-table schema above (tables, fields, keys,
relationships), produced as an Artifact immediately after this plan is approved.

## Verification

- Schema webpage: open the published Artifact URL; confirm all 11 tables, their fields, PK/FK
  markers, and relationship lines render correctly and match this document.
- Once implementation begins (separate plan): run the odds-engine distribution/EV tests and the
  ledger-invariant tests; exercise the full money loop end-to-end against Stripe test mode and
  confirm ledger reconciliation.

## Next Step After Approval

Produce the ER-diagram webpage, then move into a detailed implementation plan (scaffolding →
schema/migrations → auth → catalog+odds **seed scripts** → deposit → buy/open/RNG →
buyback/redeem → withdrawal → reveal UX), each slice built and verified in order. No admin UI in
this MVP scope.
