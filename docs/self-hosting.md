# Run SiteSense yourself

SiteSense runs on one server of your own: the web app, the API, the background jobs, PostgreSQL and
an HTTPS front door (Caddy), all in Docker. This guide installs a release, upgrades it, and keeps
it backed up. ([ADR 0019](adr/0019-release-images-and-setup.md) explains the choices.)

## What you need

- A Linux server (amd64 or arm64) with **Docker** and **Docker Compose v2**, sized as in
  [How big a server](#how-big-a-server): 2 vCPU and 4 GB of memory for a small company, 4 vCPU and
  8 GB for about 50 people working at once.
- A **domain** pointing at the server (an `A` record), and ports **80 and 443** open to the internet.
  Caddy gets and renews the Let's Encrypt certificate by itself.
- **Python 3.9 or later** for the setup script (most Linux servers have it). Without it, run the
  script in a container, shown below.
- Optional: a mail server (SMTP) for alert emails, and a Claude API key for the AI-written briefing.
  Both can be added later.

To try SiteSense on your own computer first, use `localhost` as the domain: everything works the
same, with a certificate your browser warns about once.

## How big a server

From the [load test](performance.md): 50 people working at the same time, each acting every 1 to 3
seconds (about 58 requests a second, far busier than a normal day), with every response time
target met. During it the API used about **2.4 CPU cores and 2.1 GB** of memory, and PostgreSQL
about **0.6 cores**.

| Company | People using it at the same moment | Server |
| --- | --- | --- |
| Small | up to about 15 | 2 vCPU, 4 GB memory |
| Medium | about 50 (the load test) | 4 vCPU, 8 GB memory |
| Larger | more than 50 | Measure first: run the [load test](performance.md) against a copy; more API workers (`WEB_CONCURRENCY`) need more cores |

"At the same moment" is far fewer than everyone with an account: most people open SiteSense a
few times a day. Signing in is deliberately slow (password hashing, 0.3 s each), so a burst of
sign-ins at 8 am is the busiest it gets.

**Disk.** Start with 40 GB. The database stays small (megabytes per project). Photos are what
grow: each is stored at most 2,560 pixels wide, about 1 MB. A site that attaches six photos a day
on 300 working days adds about **2 GB a year**. Backups need room too (see below), unless they go
straight to another machine.

## Install

Download the latest release bundle from the
[releases page](https://github.com/whoispasindu/SiteSense/releases) (`sitesense-<version>.tar.gz`),
check it, unpack it and run the setup:

```bash
sha256sum -c sitesense-1.0.0.tar.gz.sha256
```

```bash
tar xzf sitesense-1.0.0.tar.gz && cd sitesense-1.0.0
```

```bash
python3 setup.py
```

It asks for:

| Question | Example | Notes |
| --- | --- | --- |
| Domain | `sitesense.example.com` | `localhost` to try it on this machine |
| First Company Admin | `you@example.com`, Your Name | Gets a one-time password at the end |
| Certificate email | (the admin's) | Let's Encrypt's expiry notices; not asked for `localhost` |
| Country | `GB` | The default when you import public holidays |
| Time zone | `Europe/London` | "Today" on site and every scheduled job |
| Currency | `GBP` | Set it now: amounts are never converted |
| Number format | `en-GB` | How amounts are written |
| LKR per unit | `400` | Only if the currency is not LKR: the risk model was trained in Sri Lankan rupees |
| Mail server, Claude key | | Optional |

Then it writes `.env.prod` with a strong random value for every secret (readable by you only),
pulls the release images, starts SiteSense, waits until it is healthy, and creates the first
Company Admin. Open the address it prints and sign in with the one-time password: you choose a new
password and set up two-step sign-in. Then, under Admin, add your sites, users and the year's public
holidays (**Import public holidays**).

**Back up `.env.prod` now**, somewhere other than the server. `SITESENSE_MFA_KEY` in it decrypts
everyone's two-step sign-in; without it, every person needs an admin reset.

### Without Python on the server

```bash
docker run --rm -it -v "$PWD:/sitesense" -v /var/run/docker.sock:/var/run/docker.sock \
  -w /sitesense docker:cli sh -c "apk add --no-cache python3 >/dev/null && python3 setup.py"
```

### For scripts and automation

Every question has a flag, and `--non-interactive` takes them all from the flags:

```bash
python3 setup.py --non-interactive --domain sitesense.example.com \
  --admin-email you@example.com --admin-name "Your Name" \
  --country GB --time-zone Europe/London --currency GBP --risk-lkr-per-unit 400
```

`python3 setup.py --help` lists them all. `--no-start` only writes `.env.prod`.

## Check the images (optional)

Every release image is signed by this repository's release workflow (Sigstore, keyless) and carries
an SBOM. To check one before you run it, with [cosign](https://docs.sigstore.dev/cosign/system_config/installation/)
**3.0 or later** (cosign 2.x cannot read the newer signature format the releases use, and reports
"no signatures found"):

```bash
cosign verify ghcr.io/whoispasindu/sitesense-backend:1.0.0 \
  --certificate-identity-regexp '^https://github.com/whoispasindu/SiteSense/.github/workflows/release.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Everyday commands

From the bundle's folder (`dc` is just shorter to type):

```bash
alias dc='docker compose -f docker-compose.prod.yml --env-file .env.prod'
```

```bash
dc ps
```

```bash
dc logs -f backend scheduler
```

```bash
dc restart
```

### Is it healthy?

- `dc ps` shows every service `running`, and `healthy` where it has a check (the API, the database
  and the scheduler).
- `https://<your domain>/api/v1/health/ready` answers `{"status":"ok","checks":{"database":"ok"}}`,
  or HTTP 503 when the database is unreachable. Point an uptime monitor at it.
- The logs are one JSON object a line (`dc logs backend`), with a `request_id` that also appears in
  any error the app shows. Unsafe settings stop the API at start, and the log says which.
- The scheduler logs each morning's jobs (`weather_refreshed`, `risk_scored`): if they are missing,
  look at `dc logs scheduler`.

## Upgrade

Releases follow semantic versioning: `1.0.1` fixes, `1.1.0` adds features, `2.0.0` may need you to
change something. **Security fixes go into the latest minor release** (for example 1.4.x): stay on
it, and upgrade within a few days of a security release.

Read the release notes first: the **Upgrading** part of each version in `CHANGELOG.md` says what
to do, if anything. Then back up (below), and:

1. Download and unpack the new bundle next to the old one, and copy your `.env.prod` into it.
2. In the new folder, set `SITESENSE_VERSION` in `.env.prod` to the new version.
3. Pull and start. Migrations run once, before the API starts:

```bash
dc pull && dc up -d --wait
```

The data lives in Docker volumes (`sitesense-prod_pgdata`, `sitesense-prod_media`), not in the
folder, so the new folder uses the same data. To go back, start the old folder again **and restore
the backup** taken before the upgrade: a newer database is not guaranteed to work with an older
release.

## Back up

Two things hold your data: the **database** and the **photos**. `backup.py` saves both in one file,
while SiteSense keeps running:

```bash
python3 backup.py create
```

That writes `backups/sitesense-backup-<date>-<time>.tar` (readable by you only), keeps the newest
14 and deletes older ones. Inside: the database (`pg_dump`), the photos, and a `backup.json` with
the release and database schema it came from and the SHA-256 of each part, so a damaged copy is
caught before it is restored. `--out` picks the folder and `--keep` how many to keep.

**Every night, and off the server.** A backup on the same disk is lost with the disk. Run it from
cron and copy the file elsewhere (another server, object storage, an office NAS). For example, with
`crontab -e`:

```
30 2 * * * cd /opt/sitesense-1.0.0 && python3 backup.py create --out /var/backups/sitesense && rclone copy /var/backups/sitesense remote:sitesense-backups
```

**`.env.prod` is not in the backup**, on purpose: it holds the secrets, so it can be stored
separately and more tightly (a password manager is a good place). You need it to restore:
`SITESENSE_MFA_KEY` in it decrypts everyone's two-step sign-in.

**Size.** A backup is about the size of all the photos (they are already compressed) plus a few MB
of database, and the 14 kept add up: plan for about 14 times the photos on the backup disk.

## Restore

A restore **replaces all data** in the installation with the backup's. It checks the file first
(the size and SHA-256 of each part), and refuses a backup from a newer release than the images it
would run. A backup from an older release is fine: SiteSense upgrades its database when it starts.

**On the same server**, to go back to last night:

```bash
python3 backup.py restore backups/sitesense-backup-20261115-023000.tar
```

It asks you to type `restore`, stops the app (the database stays up), restores the database and
the photos, and starts everything again, waiting until it is healthy.

**On a new server** (the old one is gone):

1. Install Docker, download **the same release's** bundle (or a newer one) and unpack it.
2. Put your saved `.env.prod` in the folder. Do not run `setup.py`: it would write new secrets.
3. Copy the backup file there and restore:

```bash
python3 backup.py restore sitesense-backup-20261115-023000.tar
```

4. Point the domain at the new server. Caddy gets a certificate for it by itself.

If `.env.prod` is lost: run `setup.py --no-start` for a new one, restore, then make a new admin
with `dc run --rm backend python -m app.cli create-admin --email ... --name ...`. Everyone's
two-step sign-in then has to be set up again (the new admin resets each person), because the old
key is gone.

**Test it.** A backup you have never restored is a hope, not a backup. Every few months, restore the
latest one on a spare machine (as for a new server, with `localhost` as the domain) and sign in.
The procedure was tested end to end before release: install, add data, back up, delete everything
(containers and volumes), restore; the users, records and photos were back and the admin could
sign in ([ADR 0020](adr/0020-backup-and-restore.md)).

## Build the images yourself

From a clone of the repository instead of a bundle, `python scripts/fetch_models.py` fetches the
report classifier's model files (checked against their SHA-256), and the build override builds
both images locally:

```bash
python scripts/setup.py --build
```

Then pass `--build` to the backup script too (`python scripts/backup.py --build create`), so its
short-lived containers use the images you built.

## Security notes

- Only Caddy publishes ports. PostgreSQL and the API are reachable only from the other containers.
- The API refuses to start with unsafe settings (development secrets, plain-HTTP origins, two-step
  sign-in off, and others); the log says which.
- Demo mode is never on in an installation made by the setup script. Never turn it on for real data.
- More: [security.md](security.md).
