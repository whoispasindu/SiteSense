# Deployment

How to run SiteSense in production: first on your own machine with the production setup, then on
hosted services (the API on Render or Railway, the web app on Vercel, a managed PostgreSQL).

There is no public demo yet. Everything here is ready for one; the steps are the same for a demo
(demo mode on) and for a real company (demo mode off).

## 1. The production setup on your machine

`docker-compose.prod.yml` runs the same images and settings a server would:

- **Caddy** serves the built web app and the API on one HTTPS origin (`https://localhost`).
- **The API** runs 4 Uvicorn workers, read-only, as an unprivileged user.
- **The scheduler** runs the background jobs in its own process, one copy only.
- **Migrations** run once, as the schema owner, before the API starts.
- **PostgreSQL** is not reachable from your machine, only from the other containers.

```bash
cp .env.prod.example .env.prod
```

Open `.env.prod` and replace every `change-me` value. Generate each secret separately:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then start it (building the images from this checkout), load the demo company, and open the app:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.build.yml --env-file .env.prod up -d --build
```

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python -m app.cli seed-dev
```

Open <https://localhost>. Caddy uses a certificate from its own local authority, so the browser
warns once; accept it for `localhost`. Sign in with a demo account (see the README). With
`SITESENSE_DEMO_MODE=true` the demo accounts skip two-step codes, emails are only logged, a banner
says it is demo data, and everything resets to the seeded data at 03:00 Sri Lanka time.

The API refuses to start if anything in `.env.prod` is unsafe for production: a development secret,
an example database password, an MFA key equal to the JWT secret, plain-HTTP origins, or two-step
sign-in not enforced. The log says which.

Stop it with `docker compose -f docker-compose.prod.yml down` (add `-v` to delete its data).

### For a real company

Use the setup script and the released images instead: [self-hosting.md](self-hosting.md). It does
everything below for you. By hand:

- Set `SITESENSE_DEMO_MODE=false` and leave `SITESENSE_DEMO_RESET_DATABASE_URL` empty, so no running
  process holds the schema owner's password.
- Do not run `seed-dev`. Create the first Company Admin instead. It prints a one-time password,
  which must be changed at first sign-in, and then two-step sign-in must be set up:

  ```bash
  docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python -m app.cli create-admin --email you@company.lk --name "Your Name"
  ```

- On a server, set `SITESENSE_DOMAIN` to your domain, `SITESENSE_TLS` to an email address and
  `SITESENSE_BIND=0.0.0.0`. Caddy then gets a Let's Encrypt certificate by itself (ports 80 and 443
  must be open, and the domain must point at the server).
- Back up the database and the photos every night with `backup.py create`, and copy the file off
  the server ([self-hosting.md](self-hosting.md#back-up)). Photos live in the `media` volume, not
  in the database.

## 2. Other ways to host: API on Render or Railway, web app on Vercel, managed PostgreSQL

The recommended way to run SiteSense for a company is one server of your own, with the release
images and the setup script: [self-hosting.md](self-hosting.md). This section is an alternative for
those who prefer managed services; it builds from git, and its images do not include the report
classifier's transformer model.

```
browser ──https──> Vercel (web app, and /api/* rewritten) ──https──> API on Render or Railway ──> managed PostgreSQL
```

The browser only ever talks to the Vercel address. Vercel forwards `/api/*` to the API. This keeps
the refresh cookie on the same site as the app: it is `SameSite=Strict`, so a web app on one domain
calling an API on another would sign everyone out at every page load.

### About free tiers

Free tiers change often, so check each provider's pricing page before you start. The usual limits
matter here:

- **Free web services sleep when idle.** The first request after a quiet spell is slow, and
  scheduled jobs (reminders, weather, risk scoring, emails, the nightly demo reset) do not run while
  the service sleeps.
- **Free PostgreSQL** has a small storage cap, and on some providers the database expires after a
  trial period.
- **Persistent disks** (needed for site photos) are usually a paid add-on.

A free setup is fine for trying SiteSense or a short demo. For a real company, budget for a small
always-on API instance, a disk for photos, and a database with backups.

### Step 1: PostgreSQL

Create a PostgreSQL 16 or newer database on your provider (Render, Railway, Neon or Supabase all
offer one). Then, connected as the admin user the provider gives you, create the two roles SiteSense
uses. Use your own passwords, different from each other:

```sql
CREATE ROLE sitesense_owner LOGIN PASSWORD 'owner-password-here';
CREATE ROLE sitesense_app LOGIN PASSWORD 'app-password-here' NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT sitesense_owner TO CURRENT_USER;  -- some providers need this before the next line
CREATE DATABASE sitesense OWNER sitesense_owner;
```

Then, connected to the `sitesense` database:

```sql
REVOKE ALL ON DATABASE sitesense FROM PUBLIC;
GRANT CONNECT ON DATABASE sitesense TO sitesense_app;
ALTER SCHEMA public OWNER TO sitesense_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO sitesense_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sitesense_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sitesense_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sitesense_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO sitesense_app;
```

This is the same as `infra/postgres/init/01-roles.sh`. The running API uses `sitesense_app`, which
can read and write rows but never change the schema or delete audit records. Migrations use
`sitesense_owner`.

You now have two connection strings, in this form (keep `sslmode=require` if your provider gives
it):

```
postgresql+psycopg://sitesense_app:APP_PASSWORD@HOST:5432/sitesense?sslmode=require
postgresql+psycopg://sitesense_owner:OWNER_PASSWORD@HOST:5432/sitesense?sslmode=require
```

### Step 2: The API on Render

1. New → **Web Service** → connect the GitHub repository.
2. Runtime **Docker**. Root directory `backend`, Dockerfile path `Dockerfile`, Docker build target
   `prod` (under Advanced). Health check path `/api/v1/health/ready`.
3. Add a **disk** mounted at `/data/media` for site photos (paid). Without one, photos are lost at
   every deploy.
4. **Pre-deploy command:** `alembic upgrade head`, with the owner connection string available to it
   (see the environment below). On plans without a pre-deploy command, run it once from the shell
   tab after each release that adds a migration.
5. Environment variables. The `SITESENSE_*` names are in the README's configuration table:

   | Variable | Value |
   | --- | --- |
   | `SITESENSE_ENVIRONMENT` | `production` |
   | `SITESENSE_DATABASE_URL` | the `sitesense_app` connection string |
   | `SITESENSE_MIGRATION_DATABASE_URL` | the `sitesense_owner` connection string (needed by the pre-deploy command; on a real company's instance, remove it after migrating if you run migrations by hand) |
   | `SITESENSE_JWT_SECRET` | a new random secret |
   | `SITESENSE_MFA_KEY` | another new random secret (keep it: changing it resets every two-step enrolment) |
   | `SITESENSE_CORS_ORIGINS` | `https://your-app.vercel.app` (your Vercel address, or your own domain) |
   | `SITESENSE_ALLOWED_HOSTS` | `your-api.onrender.com` (the Render address) |
   | `SITESENSE_APP_BASE_URL` | `https://your-app.vercel.app` (links in emails point here) |
   | `SITESENSE_DEMO_MODE` | `true` for a demo, `false` for real data |
   | `SITESENSE_DEMO_PASSWORD` | demo only: the demo accounts' password |
   | `FORWARDED_ALLOW_IPS` | `*` (the API is only reachable through Render's proxy) |
   | `WEB_CONCURRENCY` | `1` on the smallest instances, more with more memory (each worker uses about 500 MB with the models loaded) |

   Optional: `SITESENSE_ANTHROPIC_API_KEY` (give the key a monthly spending limit in the Claude
   Console; without it the briefing is rule-based) and the `SITESENSE_SMTP_*` settings (in demo mode
   emails are only logged anyway).
6. **Scheduled jobs.** Either add a **Background Worker** with the same image, build target and
   environment, and start command `python -m app.cli run-scheduler`, and set
   `SITESENSE_SCHEDULER_ENABLED=false` on the web service. Or, on a single small instance, leave the
   scheduler on in the web service with `WEB_CONCURRENCY=1`, so it runs once. Remember that a
   sleeping free instance runs no jobs.
7. Deploy. Then, for a demo, seed it once from the shell tab:

   ```bash
   python -m app.cli seed-dev
   ```

   For the nightly reset, the scheduler needs `SITESENSE_MIGRATION_DATABASE_URL` (the reset deletes
   audit rows, which only the owner may do). For a real company, create the first admin instead
   (`python -m app.cli create-admin --email ... --name ...`).

### Step 2, alternative: the API on Railway

Same image and settings:

1. New project → **Deploy from GitHub repo**. Set the service's root directory to `backend`.
   Railway builds the Dockerfile; set the build target to `prod` (variable `RAILWAY_DOCKERFILE_TARGET`
   or the service's build settings, depending on the current UI).
2. Add a **volume** mounted at `/data/media`.
3. Add the variables from the table above, with `SITESENSE_ALLOWED_HOSTS` set to the Railway
   domain. If you create the database on Railway too, build the two connection strings from its
   host and port.
4. Pre-deploy command: `alembic upgrade head`. Health check path: `/api/v1/health/ready`.
5. For the scheduler, add a second service from the same repository with start command
   `python -m app.cli run-scheduler`, and set `SITESENSE_SCHEDULER_ENABLED=false` on the web
   service.

### Step 3: The web app on Vercel

1. New project → import the repository. Root directory `frontend`, framework preset **Vite**. Build
   command `npm run build`, output directory `dist`.
2. Add `frontend/vercel.json`, with your API address in place of `your-api.onrender.com`. It
   forwards the API, makes deep links work, and sets the same security headers as
   `frontend/nginx.conf`:

   ```json
   {
     "rewrites": [
       { "source": "/api/:path*", "destination": "https://your-api.onrender.com/api/:path*" },
       { "source": "/((?!assets/).*)", "destination": "/index.html" }
     ],
     "headers": [
       {
         "source": "/assets/(.*)",
         "headers": [{ "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }]
       },
       {
         "source": "/(.*)",
         "headers": [
           { "key": "Content-Security-Policy", "value": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests" },
           { "key": "X-Content-Type-Options", "value": "nosniff" },
           { "key": "X-Frame-Options", "value": "DENY" },
           { "key": "Referrer-Policy", "value": "no-referrer" },
           { "key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=(), payment=()" },
           { "key": "Cross-Origin-Opener-Policy", "value": "same-origin" },
           { "key": "Strict-Transport-Security", "value": "max-age=63072000; includeSubDomains" }
         ]
       }
     ]
   }
   ```

   Leave `VITE_API_BASE_URL` unset: the app calls `/api/v1` on its own address, and Vercel forwards
   it.
3. Deploy, then put the Vercel address in the API's `SITESENSE_CORS_ORIGINS` and
   `SITESENSE_APP_BASE_URL` (Step 2) and redeploy the API.

### Step 4: Check it

- `https://your-app.vercel.app/api/v1/health/ready` answers `{"status":"ok",...}`.
- Sign in. In demo mode the banner shows, and the demo accounts need no code. With demo mode off,
  a project manager is asked to set up two-step sign-in before anything else.
- Reload the page: you stay signed in (the refresh cookie works through the Vercel address).
- In the browser's developer tools, the responses carry the security headers above, and nothing is
  in local or session storage.

## Things to know

- **Rate limits are per API process.** With 4 workers, a budget of 10 sign-ins a minute is at most
  40 in practice. Account lockout is kept in the database and holds across processes. Behind more
  than one proxy (Vercel, then Render), the client address the API sees comes from forwarded
  headers, which a client can pad, so the per-IP sign-in budget is weaker there. Lockout and the
  per-user budgets are not affected.
- **Two-step sign-in in production is always enforced** for Company Admins, project managers,
  quantity surveyors and procurement officers (the API refuses to start otherwise). Only the seeded
  demo accounts skip it, and only in demo mode.
- **Keep `SITESENSE_MFA_KEY` safe and stable.** It encrypts the authenticator secrets. Losing it
  means every enrolled user needs an admin reset.
- **Model files.** The report classifier's transformer weights live in a GitHub Release, not in
  git. An image built on your machine after `python scripts/fetch_models.py` (README) includes
  them, checked against their SHA-256. Render and Railway build from git, so their images do not,
  and the API uses the built-in TF-IDF model instead. Both are tested; the transformer sorts
  problems into categories better (macro F1 0.80 against 0.73, see the model card).
