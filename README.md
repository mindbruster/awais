# Jewelry ERP

A jewelry business management system covering daily gold rates, raw material
inventory, the karigar → stones → polish manufacturing pipeline, per-product
stone breakdowns, multi-currency invoices, RBAC, reports, and a printable
invoice view.

See `docs/jewelry_erp_implementation_plan.md` for the original phased roadmap.

## Stack

- **Backend:** FastAPI + SQLAlchemy 2.0 (async) + Alembic + Postgres 16
- **Frontend:** React + Vite + TypeScript + Tailwind
- **Auth:** JWT + role permission matrix + password-confirm on destructive actions
- **Optional:** Twilio WhatsApp integration

## 🚀 Quick start (one-line commands)

The repo has a root `package.json` that orchestrates everything. You only need:

```bash
# First time on a fresh clone
npm install        # installs `concurrently`
npm run init       # venv + deps + db + migrations + seed

# Every day
npm run dev        # starts Postgres + backend + frontend in one terminal
```

That's it. Open <http://localhost:5173> and log in with
`admin@jewelryerp.com` / `admin123`.

To stop everything: Ctrl+C in the dev terminal, then `npm run stop`.

### All available commands

| Command | What it does |
|---|---|
| `npm run dev` | **Postgres + FastAPI + Vite** in parallel (recommended for daily use) |
| `npm run stop` | Stops the Postgres container |
| `npm run init` | First-time setup: venv, npm deps, env files, db, migrate, seed |
| `npm run setup` | Same as init but **without** touching the db (deps + env only) |
| `npm run db:up` | Start Postgres in the background |
| `npm run db:down` | Stop Postgres (data persists) |
| `npm run db:reset` | ⚠️ Wipe Postgres volume + re-migrate + re-seed |
| `npm run db:psql` | Open a `psql` shell against the running container |
| `npm run migrate` | Apply Alembic migrations |
| `npm run seed` | Create roles + admin user (idempotent) |
| `npm run test` | End-to-end test suite (136 assertions, real DB) |
| `npm run build` | Production build of the frontend |
| `npm run prod:up` | Build + start the **production** stack (uses `.env.prod`) |
| `npm run prod:down` | Stop the production stack |
| `npm run prod:logs` | Follow logs from the production stack |

### What the `dev` window looks like

```
[db]   postgres-1  | LOG:  database system is ready to accept connections
[api]  INFO:     Uvicorn running on http://127.0.0.1:8000
[ui]   ➜  Local:   http://localhost:5173/
```

Each pane gets a colour and a name prefix so you can see where logs come from.

### Manual / fallback commands

If you don't want the orchestrator, the underlying tools still work:

```bash
docker compose up -d                   # postgres
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --reload    # backend
cd ../frontend
npm run dev                            # frontend
```

## Project layout

```
.
├── package.json             # root orchestrator (concurrently)
├── scripts/                 # tiny node helpers (env-copy, venv-python wrapper)
├── docker-compose.yml       # Postgres + pgAdmin (dev)
├── docker-compose.prod.yml  # Postgres + backend + frontend (production)
├── backend/                 # FastAPI app
│   ├── app/
│   │   ├── core/            # config, db, security, permissions
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic schemas
│   │   ├── services/        # inventory, pricing, serial gen, whatsapp
│   │   ├── api/v1/          # routers
│   │   ├── seed.py
│   │   └── main.py
│   ├── alembic/versions/    # 5 migrations
│   ├── tests/e2e.py         # full E2E suite hitting real Postgres + API
│   ├── uploads/             # product images (served at /static/)
│   └── requirements.txt
├── frontend/                # React + Vite + Tailwind
└── docs/
```

## What's implemented

**Foundation (Phases 1–2)**: JWT login + RBAC, admin user CRUD, Customers, Products, Inventory.

**Stock ledger (Phase 3)**: every stock change recorded as a signed-delta movement; the snapshot on `inventory_items` is updated atomically by the service layer; refuses to go negative.

**Manufacturing (Phase 4)**: Vendors (karigar / stone_fixer / polish) and `manufacturing_jobs` with the stage machine `draft → karigar_assigned → karigar_received → stone_fixer_assigned → stone_fixer_received → polish_assigned → polish_received → completed`. Loss is auto-computed at each stage. `complete` materialises a Product + a finished-goods inventory row.

**Products (Phase 5)**: auto-generated serial numbers (`P-YY-00001`), image upload at `POST /api/v1/products/{id}/image` served via `/static/`.

**Sales & invoices (Phase 6)**: multi-line invoices with the pricing engine — gold amount = `weight × (purity/24) × rate`, plus stones, labor, and discount as either amount or gold-weight. Lifecycle `draft → issued → paid` or `void`. Normal sales deduct stock on issue; on-approval sales only flip product status. Void reverses sale movements.

**Cost roll-up (Phase 7)**: `karigar_cost + stone_fixing_cost + polish_cost + other_cost` is editable per job and rolled into `product.total_cost` on completion.

**RBAC + sensitive actions (Phase 8)**: role matrix in `app/core/permissions.py` (`admin / accountant / staff`); `X-Confirm-Password` header required for void invoice / cancel job / delete user / delete product.

**WhatsApp send (Phase 9, optional)**: `POST /api/v1/invoices/{id}/send-whatsapp` — Twilio backend behind `WHATSAPP_PROVIDER=twilio`, returns 503 with setup instructions when not configured.

**Reports (Phase 11)**: `/reports/stock`, `/reports/sales`, `/reports/manufacturing-loss`, `/reports/profit` — date-range filterable, role-gated.

**Production deployment (Phase 12)**: backend & frontend Dockerfiles + `docker-compose.prod.yml` with healthchecks and named volumes for data + uploads.

**Optimisation (Phase 13)**: covering indexes for created_at sorts, sales/profit reports.

**Items, stones & multi-currency**:
- Daily gold rates (`/gold-rates`) — auto-applied to new invoices via `/gold-rates/current`
- Stones master (`/stones`) with kind / cut / color / clarity
- Per-product stone breakdown (`/products/{id}/stones`) with master + snapshot price
- PKR / USD on invoices, gold rates, and stones with currency-aware formatting in the UI

## Default credentials

`admin@jewelryerp.com` / `admin123` — change on first login.
pgAdmin (dev): `admin@jewelryerp.com` / `admin` at <http://localhost:5050>.

## Tests

```bash
npm run test
```

Hits a real Postgres + a running API. 136 assertions cover auth, CRUD, RBAC,
stock ledger, the full manufacturing pipeline, normal + on-approval sales,
cost roll-up, gold rates, stones, product stone breakdown, multi-currency,
WhatsApp stub, and password-protected actions.
