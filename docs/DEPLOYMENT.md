# Deploying Jewelry ERP to Railway

A runbook. Follow it top to bottom the first time; after that, deploys are `git push`.

Read the two boxes at the end of §1 before you start — they are the two ways this
deployment silently loses data, and both are configuration, not code.

---

## 1. What gets deployed

Three services in one Railway project, all from this repository:

| Service | Root Directory | Builder | Healthcheck | Public domain |
|---|---|---|---|---|
| **Postgres** | — (Railway plugin) | — | — | none (private only) |
| **backend** | `/backend` | Dockerfile | `/health` | `api.<your-domain>` |
| **frontend** | `/frontend` | Dockerfile | `/healthz` | `app.<your-domain>` |

Each service reads **only** the config file inside its own Root Directory —
`backend/railway.toml` and `frontend/railway.toml`. That is why the Root
Directory setting matters, and it is the whole story: Railway has no notion of
a repo-root file carrying defaults that per-service files inherit or override.
If a setting is not in the service's own file, it is not applied. (An earlier
`railway.json` at the repo root implied otherwise and was removed rather than
left sitting there looking authoritative while doing nothing.)

`docker-compose.prod.yml` is **not** used on Railway. It remains valid for a
single-host deploy, but see §12: the frontend image changed and compose needs two
edits to keep working.

> ### Photographs will vanish unless you set `STORAGE_BACKEND=s3`
> Railway containers have an ephemeral filesystem. It is rebuilt on every
> redeploy, every crash-restart and every scale event. With the default local
> backend, product photographs are written to that filesystem — so every deploy
> deletes every photograph, while the database rows keep pointing at files that
> no longer exist. Nothing errors. You find out weeks later.
>
> A photo is taken when gold arrives at RP and again when the finished piece is
> stocked. They are the only visual record of what a piece looked like at each
> step. §4 sets up the bucket. Do not skip it.

> ### `CORS_ORIGINS` must be the exact frontend origin
> Scheme included, no trailing slash, no path: `https://app.example.com`.
> `app.example.com`, `https://app.example.com/` and `http://app.example.com`
> all fail to match. The symptom is a frontend that loads perfectly, an API
> whose `/health` is green, and every request failing in the browser console.

---

## 2. Create the project

1. Railway → **New Project** → **Deploy from GitHub repo** → pick this repo.
2. Delete the service Railway auto-creates; you will add three deliberately.
3. **+ New** → **Database** → **PostgreSQL**. Leave it private — never add a
   public domain to the database.
4. **+ New** → **GitHub Repo** → this repo. Rename the service `backend`.
   Settings → **Root Directory** = `/backend`. Railway then picks up
   `backend/railway.toml` and `backend/Dockerfile`.
5. **+ New** → **GitHub Repo** → this repo again. Rename it `frontend`.
   Settings → **Root Directory** = `/frontend`.

Both service configs set `watchPatterns`, so a backend-only commit does not
rebuild and restart the frontend.

---

## 3. Generate the secrets

Run these locally and keep the output in a password manager. They are not
recoverable from Railway later in plaintext.

```bash
# JWT_SECRET — must be at least 32 chars, and the app refuses to start in
# production if it still looks like a placeholder.
python -c "import secrets; print(secrets.token_urlsafe(64))"

# SEED_ADMIN_PASSWORD — the first admin login. Change it in the app afterwards.
python -c "import secrets; print(secrets.token_urlsafe(18))"
```

Rotating `JWT_SECRET` later invalidates every issued token — everyone is logged
out at once. That is a safe operation, just a noisy one; do it off-hours.

---

## 4. Object storage (Cloudflare R2)

R2 is S3-compatible and charges nothing for egress, which matters because the
shop browses photographs all day. AWS S3, Backblaze B2, MinIO and DigitalOcean
Spaces work with exactly the same five variables and different endpoints.

1. Cloudflare dashboard → **R2** → **Create bucket**.
   Name it `jewelry-erp-uploads`. Pick a location hint near the shop.
2. **R2 → Manage R2 API Tokens → Create API Token**
   - Permission: **Object Read & Write**
   - Scope it to **that one bucket**, not "all buckets".
   - Cloudflare shows the **Access Key ID**, the **Secret Access Key** (once —
     copy it now) and the S3 endpoint
     `https://<account-id>.r2.cloudflarestorage.com`.
   - That endpoint is the *private, credentialed write* address. It is **not**
     the address browsers read from.
3. Give the bucket a **public read** address, because `<img src>` is
   unauthenticated:
   - **Preferred:** bucket → **Settings → Custom Domains → Connect Domain** →
     `images.<your-domain>`. Requires the domain to be on Cloudflare. Cloudflare
     creates the DNS record and the certificate itself.
   - **Quick start:** bucket → **Settings → Public Development URL** → enable.
     You get `https://pub-<hash>.r2.dev`. Cloudflare rate-limits r2.dev and
     explicitly does not support it for production. Fine for the first smoke
     test; move to a custom domain before go-live.
4. Do **not** make the bucket world-writable and do not put the API token
   anywhere but Railway's variables.

**Bucket CORS is not required.** The app renders photos with `<img src>`, which
is not a CORS-governed request. Uploads go server-to-server from the backend, not
from the browser. Add a CORS rule only if a future feature fetches images with
`fetch()`.

`S3_PUBLIC_BASE_URL` is written verbatim into `product.image_url` at upload
time. **Changing it later orphans every URL already stored.** Decide on the
custom domain before you upload real photographs, or plan a one-off UPDATE.

---

## 5. Backend service variables

Railway → `backend` → **Variables**.

| Variable | Value | Notes |
|---|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Reference variable — type it exactly, including the braces. |
| `ENVIRONMENT` | `production` | Anything but development/test/ci turns on the startup secret checks. |
| `DEBUG` | `false` | Startup fails if this is true in production. |
| `JWT_SECRET` | from §3 | ≥ 32 chars. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | One working day. |
| `CORS_ORIGINS` | `https://app.<your-domain>` | Exact origin. See the box in §1. |
| `SEED_ADMIN_EMAIL` | the owner's email | |
| `SEED_ADMIN_PASSWORD` | from §3 | `admin123` blocks startup. |
| `SEED_ADMIN_NAME` | e.g. `System Admin` | |
| `STORAGE_BACKEND` | `s3` | **Required on Railway.** |
| `S3_ENDPOINT` | `https://<account-id>.r2.cloudflarestorage.com` | Private write endpoint. |
| `S3_BUCKET` | `jewelry-erp-uploads` | |
| `S3_ACCESS_KEY_ID` | from §4 | |
| `S3_SECRET_ACCESS_KEY` | from §4 | |
| `S3_PUBLIC_BASE_URL` | `https://images.<your-domain>` | Public read address, no trailing slash. |
| `S3_REGION` | `auto` | R2 ignores it. Real AWS S3 needs the actual region. |
| `S3_PREFIX` | `products` | Optional; key prefix inside the bucket. |

Optional, both safe to omit:

| Variable | Value | Notes |
|---|---|---|
| `AI_PROVIDER` | `openrouter` or `anthropic` | Omit or `none` and every figure still renders — only the narration is skipped, and `/ask` returns 503 with setup instructions. |
| `OPENROUTER_API_KEY` | your key | For `openrouter`. Needs no extra Python package. |
| `ANTHROPIC_API_KEY` | your key | For `anthropic`. That route also needs `pip install anthropic`. |
| `AI_MODEL` | `z-ai/glm-4.7-flash` | Defaults follow the provider. See `docs/AI_SETUP.md` — note that no GLM model is on OpenRouter's free tier, though this one costs about $0.06/M input. |
| `FORWARDED_ALLOW_IPS` | leave unset | Only set this if Railway's edge stops being the immediate hop. Setting it to `*` lets any caller choose its own client IP, which disables the login rate limit. |
| `WHATSAPP_PROVIDER` | `twilio` | Omit and the send endpoint returns 503. |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_WHATSAPP_FROM` | from Twilio | The `FROM` value must keep its `whatsapp:` prefix. |

Do **not** set `PORT`. Railway injects it and the container binds it.

**About the Postgres URL (already handled, don't "fix" it):** Railway's plugin
hands out `postgresql://…`, but SQLAlchemy's async engine needs the driver named
— `postgresql+asyncpg://…`. `backend/app/core/config.py` rewrites the scheme on
load. Pasting a hand-edited `+asyncpg` URL also works, but then rotating the
database credential silently leaves you on a stale URL. Use the reference
variable.

---

## 6. Frontend service variables

Railway → `frontend` → **Variables**.

| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://api.<your-domain>/api/v1` |

**This is a build-time value.** Vite substitutes `import.meta.env.*` when the
bundle is compiled; there is no server left at runtime to read an environment
variable. Railway forwards service variables into the Docker build as build
arguments, which is what `ARG VITE_API_BASE_URL` in `frontend/Dockerfile`
consumes.

Consequence: **after changing this variable you must Redeploy, not Restart.** A
restart re-runs the existing image with the old URL still baked in, and looks
exactly like the change did nothing.

Verify what actually got baked:

```bash
curl -s https://app.<your-domain>/ | grep -o '/assets/index-[^"]*\.js'
curl -s https://app.<your-domain>/assets/index-<hash>.js | grep -o 'https://api[^"]*'
```

Do not set `PORT` here either. The image defaults to 8080 and nginx renders
`listen ${PORT}` through the official image's envsubst templating at start.

---

## 7. Migrations

The backend's start command is:

```
alembic upgrade head && python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port $PORT …
```

Migrations run **before** the server accepts traffic, so a container never serves
requests against a schema one revision behind its code. If a migration fails the
container exits, the healthcheck never passes, and Railway keeps the previous
deploy serving. That is the intended behaviour: a failed migration should be a
failed deploy, not a half-migrated live system.

`python -m app.seed` is idempotent — it creates the admin, roles and chart of
accounts if absent and does nothing otherwise.

The healthcheck timeout is 300s in `backend/railway.toml` because the very first
deploy runs every migration in the repo before `/health` can answer.

Useful commands (needs `npm i -g @railway/cli`, then `railway link`):

```bash
railway run --service backend alembic current      # what revision is live
railway run --service backend alembic history      # what exists
railway run --service backend alembic upgrade head # manual catch-up
railway logs --service backend
```

**Never run `alembic downgrade` against production.** Down-revisions in this repo
are written for local iteration and several of them drop columns. Roll forward
with a new migration, or restore from a backup (§10).

**Not automated, and deliberately so:** `numReplicas` is pinned to 1 on the
backend. Two containers running `alembic upgrade head` at the same moment block
on the `alembic_version` row and the loser can time out mid-migration. Before
scaling past one replica, move the migration into a Railway pre-deploy command
and take it out of `startCommand`.

---

## 8. Custom domains

Assume the domain is `example.com`. Two subdomains, one per public service.

**Backend:**
1. Railway → `backend` → **Settings → Networking → Custom Domain**.
2. Enter `api.example.com`. Railway shows a target like
   `backend-production-1a2b.up.railway.app`.
3. At your DNS provider, create:
   `CNAME  api  →  backend-production-1a2b.up.railway.app`

**Frontend:**
1. Railway → `frontend` → **Settings → Networking → Custom Domain**.
2. Enter `app.example.com`.
3. `CNAME  app  →  frontend-production-3c4d.up.railway.app`

Notes that will cost you an afternoon otherwise:

- **Use the exact target Railway prints for that service.** The two services have
  different targets; swapping them produces a working TLS certificate serving the
  wrong app.
- **On Cloudflare, leave the records DNS-only (grey cloud) until Railway reports
  the certificate as issued.** Proxying blocks the HTTP-01 challenge. Once the
  cert is live you may switch to proxied, but SSL/TLS mode must be **Full
  (strict)** — anything less produces a redirect loop.
- **A bare apex (`example.com`) cannot be a CNAME.** Use `ALIAS`/`ANAME` if your
  provider supports it, or Cloudflare's CNAME flattening, or just redirect the
  apex to `app.example.com`.
- DNS propagation is usually minutes. If Railway still says "waiting" after an
  hour, check with `dig api.example.com CNAME +short` — you are almost certainly
  looking at a typo or a record your provider silently appended the zone to
  (`api.example.com.example.com`).

**Then, in this order:**
1. Set `CORS_ORIGINS=https://app.example.com` on the backend and **redeploy**.
2. Set `VITE_API_BASE_URL=https://api.example.com/api/v1` on the frontend and
   **redeploy** (§6 — a restart will not do it).
3. If you moved the R2 public address to `images.example.com`, update
   `S3_PUBLIC_BASE_URL` too — and remember it only affects photographs uploaded
   *after* the change (§4).

Serving both from one origin (path-based `/api`) is possible but is not what
these configs do: the frontend image no longer proxies `/api` anywhere, because
on Railway there is no in-cluster hostname for nginx to proxy to.

---

## 9. Automated Postgres backups

Two layers. Set up both; they fail differently.

### Layer 1 — Railway's own backups

Railway → Postgres service → **Backups**. Enable scheduled backups and set the
retention you are willing to pay for. Daily is the sensible default for a shop
that posts a few dozen entries a day.

Honest limits: these live in the same Railway account as the database. They
protect against a bad migration or a wrong `DELETE`. They do not protect against
a lost or compromised Railway account, a billing lapse that suspends the project,
or Railway itself having a bad day. That is what layer 2 is for.

### Layer 2 — offsite `pg_dump` to R2

Two things to settle before the job below will run, both of which contradict
something said earlier in this document if you skip them:

**Reaching the database from outside Railway.** §2 tells you to keep Postgres
private, and that is right — but a backup running on your own machine or in
GitHub Actions is *outside*, and the private hostname does not resolve there.
Enable **TCP Proxy** on the Postgres service (Railway → Postgres → Settings →
Networking → TCP Proxy) and use the proxy host and port it gives you in
`PGURL`. That is a public endpoint protected only by the password, so treat the
credential accordingly: never commit it, and rotate it if it leaks. If you would
rather not expose it at all, run the job as a Railway cron *inside* the project,
where the private hostname works and no proxy is needed.

**Matching the client to the server.** `pg_dump` refuses to dump from a server
newer than itself, and Railway upgrades its Postgres image without asking. The
job below pins `postgres:16-alpine`; check the real version and change the tag
to match if it differs, or the backup starts failing silently one morning:

```bash
docker run --rm postgres:16-alpine psql "$PGURL" -tAc "SHOW server_version;"
```

**This is not automated by this repository.** Nothing in this repo creates the
schedule; you have to set it up once. Here is the exact thing to set up.

Add a scheduled workflow at `.github/workflows/backup.yml`:

```yaml
name: Nightly database backup
on:
  schedule:
    - cron: "0 21 * * *"   # 02:00 PKT
  workflow_dispatch:        # so you can test it without waiting a day

jobs:
  dump:
    runs-on: ubuntu-latest
    container: postgres:16-alpine   # pg_dump MUST be >= the server major version
    steps:
      - name: Dump
        env:
          PGURL: ${{ secrets.DATABASE_PUBLIC_URL }}
        run: |
          set -euo pipefail
          STAMP=$(date -u +%Y%m%dT%H%M%SZ)
          pg_dump --format=custom --no-owner --no-privileges "$PGURL" > "/tmp/jewelry-$STAMP.dump"
          ls -l "/tmp/jewelry-$STAMP.dump"
          echo "STAMP=$STAMP" >> "$GITHUB_ENV"
      - name: Upload to R2
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
          AWS_DEFAULT_REGION: auto
        run: |
          apk add --no-cache aws-cli
          aws s3 cp "/tmp/jewelry-$STAMP.dump" \
            "s3://jewelry-erp-backups/$STAMP.dump" \
            --endpoint-url "https://<account-id>.r2.cloudflarestorage.com"
```

Setup, once:

- Create a **second** R2 bucket `jewelry-erp-backups`, private, with its own API
  token. Do not reuse the uploads bucket or its credentials — the uploads token
  is held by a public-facing web service.
- Set a **lifecycle rule** on it (R2 → bucket → Settings → Object lifecycle) to
  delete objects older than 30–90 days, or you will pay to store 3,000 dumps.
- GitHub → repo → Settings → Secrets: `DATABASE_PUBLIC_URL` (Railway Postgres →
  Variables → the *public* URL, since GitHub Actions is outside Railway's private
  network), `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.
- Run it once with **workflow_dispatch** and confirm an object appears. A backup
  job you have never seen succeed is not a backup job.

`--format=custom` matters: it is compressed and it lets `pg_restore` do a
selective or parallel restore. A plain `.sql` file gives you neither.

---

## 10. Restoring — and testing that you can

**A backup you have not restored is a hypothesis.** Do this drill once during
setup and once a quarter. It takes ten minutes and it is the only way to learn
that your dumps are truncated *before* you need them.

### The drill (restore into a scratch database, never over production)

```bash
# 1. Fetch the most recent dump.
aws s3 ls s3://jewelry-erp-backups/ --endpoint-url https://<account-id>.r2.cloudflarestorage.com | tail -5
aws s3 cp s3://jewelry-erp-backups/<STAMP>.dump ./restore-test.dump \
  --endpoint-url https://<account-id>.r2.cloudflarestorage.com

# 2. Check what major version the server actually is, and match it below.
#    pg_restore refuses a dump made by a NEWER pg_dump than itself, and Railway
#    upgrades its Postgres image without asking you.
docker run --rm postgres:16-alpine psql "$PGURL" -tAc "SHOW server_version;"

# 3. Restore into a throwaway local Postgres of that same major version.
#    Everything runs INSIDE the container: no port mapping, no --network host.
#    `--network host` does not reach the host on macOS or Windows — Docker
#    Desktop runs the engine in a VM, so a drill written that way silently
#    fails on the machines most people actually try it from, which is the one
#    thing a restore drill must never do.
docker run -d --name pg-restore-test -e POSTGRES_PASSWORD=test postgres:16-alpine
until docker exec pg-restore-test pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
docker exec pg-restore-test psql -U postgres -c "CREATE DATABASE restore_test;"
docker cp ./restore-test.dump pg-restore-test:/tmp/d.dump
docker exec pg-restore-test \
  pg_restore --no-owner --no-privileges -U postgres -d restore_test /tmp/d.dump
```

Note the `until pg_isready` rather than `sleep 5`: on a slow machine five
seconds is not always enough, and a drill that fails intermittently gets
skipped, which defeats the point of having one.

### 3. Prove it is actually the books, not an empty schema

Row counts alone are not proof. Check that the ledger still balances — a dump
that lost rows shows up here and nowhere else:

```bash
docker exec pg-restore-test psql -U postgres -d restore_test -c "
  SELECT
    (SELECT count(*) FROM journal_entries)        AS entries,
    (SELECT count(*) FROM journal_lines)          AS lines,
    (SELECT count(*) FROM products)               AS products,
    (SELECT max(created_at) FROM journal_entries) AS newest_entry;
"

# Every entry must net to zero on value_pkr. Any row returned here means the
# restore is damaged — balances in this system are DERIVED from these lines, so
# an unbalanced entry is a set of books that will never reconcile again.
docker exec pg-restore-test psql -U postgres -d restore_test -c "
  SELECT entry_id, sum(value_pkr) AS imbalance
  FROM journal_lines
  GROUP BY entry_id
  HAVING sum(value_pkr) <> 0;
"
```

Expect: zero rows from the second query, and a `newest_entry` within a day of
the dump's timestamp. Then clean up:

```bash
docker rm -f pg-restore-test && rm restore-test.dump
```

### Restoring for real

1. **Stop writes first.** Railway → `backend` → Settings → set replicas to 0, or
   remove the public domain. Restoring under live traffic produces a database
   that is neither the backup nor the present.
2. Restore into a **new, empty** database, not over the live one — `pg_restore`
   into a populated database leaves a hybrid that looks fine and is not.
   Provision a second Postgres service, restore into it, point
   `DATABASE_URL` at it, redeploy, verify, and only then retire the old one.
3. After the app is up, re-run the imbalance query above against the live
   database before you let anyone post an entry.
4. Photographs are **not** in the dump. They are in R2 and survive a database
   restore independently — but a database restored to last night still holds
   `image_url`s for photos uploaded today, which now point at objects that exist.
   That is harmless. The reverse (restoring an old R2 state) is not; don't.

---

## 11. Go-live checklist

Infrastructure:
- [ ] Three services exist; backend Root Directory `/backend`, frontend `/frontend`.
- [ ] Postgres has **no** public domain.
- [ ] `DATABASE_URL` on the backend is the reference `${{Postgres.DATABASE_URL}}`.
- [ ] Backend deploy log shows `alembic upgrade head` completing, then uvicorn starting.
- [ ] `railway run --service backend alembic current` matches the newest file in `backend/alembic/versions/`.

Secrets:
- [ ] `JWT_SECRET` is ≥32 random chars and not from any example file.
- [ ] `SEED_ADMIN_PASSWORD` is not `admin123`, and you have changed it in-app after first login.
- [ ] `ENVIRONMENT=production`, `DEBUG=false`.
- [ ] No secret is committed to git. (`.env.prod` is gitignored; `.env.prod.example` has placeholders only.)

Storage:
- [ ] `STORAGE_BACKEND=s3` on the backend.
- [ ] Uploaded a product photo through the UI, then **redeployed the backend**, then reloaded the product page and the photo is still there. This is the test that R1 is actually fixed; nothing else proves it.
- [ ] The uploads R2 token is scoped to the uploads bucket only.

Domains and wiring:
- [ ] `https://api.<domain>/health` returns `{"status":"ok", …}`.
- [ ] `https://app.<domain>/healthz` returns `ok`.
- [ ] `CORS_ORIGINS` is the exact frontend origin with scheme, no trailing slash.
- [ ] The built bundle contains the API URL you expect (§6 curl check).
- [ ] Logged in from a real browser and loaded a page that fetches data — no CORS errors in the console.

Data safety:
- [ ] Railway scheduled backups enabled with a chosen retention.
- [ ] Offsite backup workflow has run **successfully at least once** (§9).
- [ ] The restore drill in §10 has been performed and the imbalance query returned zero rows.
- [ ] The backups bucket has a lifecycle rule.

Opening position (§13 — do this before anyone writes a bill):
- [ ] Today's gold rate is set.
- [ ] Every pot the shop keeps material in exists, at the purity it actually holds.
- [ ] Each pot has been **weighed** and recorded as opening stock — not copied from the old system.
- [ ] Opening balances typed on customers, workers and bank accounts, then posted once.
- [ ] `python -m tools.check_stock_ledger` says the shelves and the books agree.
- [ ] A labelled backup taken at this point, before the first bill.

Business sanity, in production, before handing over:
- [ ] Created a design, posted a leg, and confirmed the ledger entry balances.
- [ ] Created and stocked a product with a photograph.
- [ ] Document numbers increment correctly after a redeploy (they are `MAX`-based under an advisory lock, so they should — verify anyway).

---

## 12. Known gaps — things a human still has to do

Listed honestly rather than buried.

1. **No screen enters the shop's opening position.** Two endpoints do it and
   neither has a button:

   - `POST /api/v1/inventory/{item_id}/opening` — what each pot held on day one.
     The only way to put metal or stones into stock without a purchase behind
     it, and it posts to the asset account against `3200 Opening Balance
     Equity` like any other document.
   - `POST /api/v1/ledger/opening-balances` — moves the `opening_balance`
     figures already typed on customers, workers and bank accounts into the
     ledger. Idempotent and serialised on an advisory lock, so a double click
     cannot double anybody's balance. It refuses without a 24k PKR gold rate on
     record, because worker metal has to be valued to balance the entry.

   Customer opening balances **are** enterable on the customer form; it is the
   posting step and the stock side that have no UI. Until one exists, a shop
   goes live either with an empty safe or by calling these with a token. See
   §13 for the order to do it in.

2. **`docker-compose.prod.yml` needs two edits.** The frontend image is now
   standalone — it listens on `${PORT:-8080}` and no longer proxies `/api` to a
   host named `backend`, because that host does not exist on Railway. For compose
   to keep working: map `"${FRONTEND_PORT:-80}:8080"` instead of `:80`, and give
   the frontend build `VITE_API_BASE_URL: http://<host>:8000/api/v1` pointing at
   the published backend port. The old `frontend/nginx.conf` is left in place and
   unused by the image; a single-host deploy that wants the reverse-proxy layout
   should mount it explicitly.

3. **Backups are set up by hand.** §9 gives the workflow file and the secrets,
   but nothing in this repo creates them. Until you complete §9 and §10, the only
   backups are Railway's, in the same account as the database.

4. **Migrations run in the start command, so the backend is pinned to one
   replica.** Fine for one shop. §7 says what to change before scaling.

5. **Existing local photographs are not migrated.** If a shop has been running on
   local disk, the files in `backend/uploads/` must be copied into the bucket
   under the `products/` prefix *and* the `product.image_url` values rewritten
   from `/static/x.png` to `https://images.<domain>/products/x.png`. There is no
   migration script for this. Do it once, in a transaction, with a backup taken
   first.

6. **No error tracking, uptime monitoring, or log retention.** Railway keeps
   recent logs and nothing pages anyone. `/health` is a real endpoint — point an
   external uptime monitor at `https://api.<domain>/health` at minimum.

7. **No staging environment.** Railway environments make this cheap (duplicate
   the project, use a separate database and bucket). Worth doing before the first
   migration that touches posted entries.

---

## 13. Day one: putting the shop's real position in

The checklist above proves the software runs. This is the part that decides
whether its numbers mean anything, and it has to happen **before** anybody
writes a bill.

Order matters, because each step is the input to the next:

1. **Set today's gold rate.** Nothing metal-valued can post without one, and
   opening balances are refused outright until it exists.
2. **Create the pots** — each tray, safe and parcel the shop actually keeps
   material in, at the purity that pot holds. A pot's purity is not cosmetic:
   metal returned into a pot is valued at that purity, and putting 18k into a
   pot labelled 24k overstates fine grams by a third.
3. **Weigh each pot and record it as opening stock.** One call per pot. Weigh
   it — do not copy the last system's figure, which is exactly the number the
   count is meant to test.
4. **Type opening balances** on customers, workers and bank accounts: who owes
   the shop, who the shop owes, what is in each account.
5. **Post them** with `POST /ledger/opening-balances`, once.
6. **Check the books against the safe.** Run `python -m tools.check_stock_ledger`
   and confirm it says the shelves and the books agree. If it does not, stop —
   every figure the system reports from here on is built on this.
7. **Take a backup**, and label it. This is the only moment where the database
   is a clean statement of the shop's position with nothing posted against it.

If the shop is coming off an existing system, note that its stock figures are a
claim, not a measurement. The count in step 3 is what makes them real.
