# Run SiteSense yourself

SiteSense runs on one server of your own: the web app, the API, the background jobs, PostgreSQL and
an HTTPS front door (Caddy), all in Docker. This guide installs a release, upgrades it, and keeps
it backed up. ([ADR 0019](adr/0019-release-images-and-setup.md) explains the choices.)

## What you need

- A Linux server (amd64 or arm64) with **Docker** and **Docker Compose v2**. For up to about 50
  people at once: 2 vCPU and 4 GB of memory (the [load test](performance.md) ran on a laptop of
  that size with room to spare), and 20 GB of disk to start; photos grow with use.
- A **domain** pointing at the server (an `A` record), and ports **80 and 443** open to the internet.
  Caddy gets and renews the Let's Encrypt certificate by itself.
- **Python 3.9 or later** for the setup script (most Linux servers have it). Without it, run the
  script in a container, shown below.
- Optional: a mail server (SMTP) for alert emails, and a Claude API key for the AI-written briefing.
  Both can be added later.

To try SiteSense on your own computer first, use `localhost` as the domain: everything works the
same, with a certificate your browser warns about once.

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
an SBOM. To check one before you run it, with [cosign](https://docs.sigstore.dev/cosign/system_config/installation/):

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

## Upgrade

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

Two things hold your data: the **database** and the **photos**. Back up both, every night, to
somewhere other than this server, and keep `.env.prod` with them.

```bash
dc exec -T db pg_dump -U postgres -d sitesense --format=custom > sitesense-$(date +%F).dump
```

```bash
docker run --rm -v sitesense-prod_media:/media:ro -v "$PWD:/out" alpine \
  tar czf /out/sitesense-photos-$(date +%F).tar.gz -C /media .
```

Restore into a fresh installation: run the setup with `--no-start`, replace the new `.env.prod`
with your saved one, start only the database (`dc up -d db`), restore with
`dc exec -T db pg_restore -U postgres -d sitesense --clean --if-exists < sitesense-<date>.dump`,
unpack the photos into the `media` volume the same way they were packed, then `dc up -d --wait`.
A fully worked and tested restore guide is part of the next release step (see the
[release plan](plans/open-source-release.md)).

## Build the images yourself

From a clone of the repository instead of a bundle, `python scripts/fetch_models.py` fetches the
report classifier's model files (checked against their SHA-256), and the build override builds
both images locally:

```bash
python scripts/setup.py --build
```

## Security notes

- Only Caddy publishes ports. PostgreSQL and the API are reachable only from the other containers.
- The API refuses to start with unsafe settings (development secrets, plain-HTTP origins, two-step
  sign-in off, and others); the log says which.
- Demo mode is never on in an installation made by the setup script. Never turn it on for real data.
- More: [security.md](security.md).
