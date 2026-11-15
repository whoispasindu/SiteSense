# ADR 0019: Release images, models in the image, and a one-step setup

- Status: accepted
- Date: 2026-11-15
- Changes: the production setup in [ADR 0016](0016-hardening-and-deployment.md) (pulls released
  images instead of building them; the bind address and certificate are settings)

## Context

SiteSense will be released as open source for companies to run themselves, and later as a hosted
service built from the same release ([release plan](../plans/open-source-release.md), steps 1, 2 and
4). Until now, running the production setup meant:

- a clone of the repository, because `docker-compose.prod.yml` built the images from source;
- the GitHub CLI, signed in, to fetch the report classifier's model files;
- filling in `.env.prod` by hand, including five secrets;
- editing `infra/caddy/Caddyfile` to remove `tls internal` on a real server, and changing the port
  bindings, which published 80 and 443 on `127.0.0.1` only, so a server was unreachable.

## Decision

### Release images (`.github/workflows/release.yml`)

A version tag (`v1.0.0`) runs the release workflow:

1. **The tag must match** the backend's `version` and the web app's `package.json` version.
2. **Images** `ghcr.io/<owner>/sitesense-backend` and `-frontend`, built from the `prod` targets
   for `linux/amd64` and `linux/arm64`, tagged `1.0.0`, `1.0` and `latest` (a pre-release gets only
   its own tag). Each carries an **SBOM** and **build provenance** (BuildKit attestations) and is
   **signed with Sigstore**, keyless, with the workflow's own identity. Anyone can check where an
   image came from with `cosign verify` (docs/self-hosting.md).
3. **A GitHub Release** with the notes from `CHANGELOG.md` and the **deployment bundle**
   (`scripts/make_bundle.py`): the production compose file with its defaults pinned to this
   version's images, the Caddy and database files it mounts, the settings example, the setup script
   and the self-hosting guide, with a SHA-256.

Every action is pinned to a commit SHA, as in CI. Jobs get only the permissions they need
(`packages: write` and `id-token: write` for the image job only; `contents: write` for the release
job only). The release itself is made with the runner's `gh`, not another third-party action.

While the repository is private, so are its packages; they become public with the repository
(release plan, step 6). Signing also waits until then: keyless signing writes the signer's identity,
including the repository's name, to Sigstore's public transparency log.

### Models in the image

The release workflow fetches the DistilBERT files (`scripts/fetch_models.py`, checked against the
committed SHA-256) before building, so the backend image contains them: no GitHub account and no
download at run time. `fetch_models.py` also downloads over **plain HTTPS** now (`--via https`), for
people building from a clone of the public repository. It goes only to `github.com` and follows
redirects only to GitHub's own storage, caps each download at the size the manifest pins, and
checks the SHA-256 as before. The GitHub CLI stays the default where it is installed (and is needed
while the repository is private).

### Production compose

- `docker-compose.prod.yml` pulls `${SITESENSE_IMAGE_PREFIX}-backend:${SITESENSE_VERSION}` and
  `-frontend`. In the repository the defaults are `ghcr.io/whoispasindu/sitesense` and `latest`; in
  a release bundle they are that release. Upgrading is changing `SITESENSE_VERSION`, pulling and
  starting.
- `docker-compose.build.yml` is an override that builds both images from the checkout instead,
  for development and for anyone who wants to build their own.
- `SITESENSE_BIND` (default `127.0.0.1`; `0.0.0.0` on a server) and `SITESENSE_TLS` (default
  `internal`; an email address on a server, for Let's Encrypt) replace editing files.
- The SMTP port and security setting now reach the API (they were missing from the compose file).

### The setup script (`scripts/setup.py`)

Standard-library Python only (3.9 or later), so it runs on a stock server or in a throwaway
container. It asks for the domain, the first Company Admin, the country, time zone, currency
(and the LKR rate when it is not LKR, ADR 0017), and optionally SMTP and a Claude key. Then it:

- writes `.env.prod` with a fresh `secrets.token_urlsafe` value for each of the three database
  passwords, the JWT secret and the MFA key, readable by its owner only (`0600`), and **refuses to
  overwrite an existing one**, which holds the keys to the data;
- never turns demo mode on, and leaves the demo reset URL empty (no process holds the schema owner's
  password);
- pulls the images (or builds them with `--build`), starts the stack, waits until it is healthy, and
  runs `create-admin`, which prints the one-time password.

Every question has a flag, and `--non-interactive` makes it scriptable: the future hosted service
can provision a company's installation with the same script.

Tests (`backend/tests/test_release_tools.py`) load the script and check that what it writes passes
the API's own production checks, that the compose file and the script agree on every setting, that
an existing settings file is never touched, and that a bundle pins its own images.

## Consequences

- A company needs a server with Docker, Python and a domain. Five commands install it
  ([self-hosting](../self-hosting.md)).
- The images are public once the repository is; until then only the owner can pull them.
- The deployment guide's hosted option (Render, Railway, Vercel) still builds from git, and its
  images do not include the transformer model.
- Still to do: a worked and tested backup-and-restore guide, and sizing beyond 50 people (release
  plan, step 5).
