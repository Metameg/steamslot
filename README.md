# SteamSlot

A pack-opening / loot-box web app for Steam games, modeled on Rips by Triumph. Users buy a pack,
open it for a server-decided randomized game win, then either buy back the win for its locked
value or redeem it as a real Steam CD key.

**Status**: MVP under active development. See [docs/design.md](docs/design.md) for the full
design/plan (core loop, schema, pricing model, RNG, testing strategy).

## Stack

- **Frontend**: React + Vite
- **Backend**: FastAPI (Python)
- **Database**: Postgres
- **Payments**: Stripe

## Layout

- `backend/` — FastAPI service (API, DB models/migrations, RNG + ledger logic, seed scripts)
- `frontend/` — React/Vite SPA
- `docs/` — design docs
