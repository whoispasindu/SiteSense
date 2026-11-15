"""Make the deployment bundle a release attaches (ADR 0019): everything a server needs, no source.

    python scripts/make_bundle.py --version 1.0.0 --owner whoispasindu --out dist

Writes dist/sitesense-<version>.tar.gz and its .sha256. Inside, in a folder sitesense-<version>/:

- docker-compose.prod.yml, with the image prefix and version defaulting to this release, so the
  bundle runs exactly the images it was released with;
- infra/caddy/Caddyfile and infra/postgres/init/01-roles.sh, which the compose file mounts;
- .env.prod.example, setup.py (with a VERSION file beside it), backup.py, README.md (docs/self-hosting.md),
  CHANGELOG.md and LICENSE.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "docker-compose.prod.yml": "docker-compose.prod.yml",
    "infra/caddy/Caddyfile": "infra/caddy/Caddyfile",
    "infra/postgres/init/01-roles.sh": "infra/postgres/init/01-roles.sh",
    ".env.prod.example": ".env.prod.example",
    "scripts/setup.py": "setup.py",
    "scripts/backup.py": "backup.py",
    "docs/self-hosting.md": "README.md",
    "CHANGELOG.md": "CHANGELOG.md",
    "LICENSE": "LICENSE",
}
VERSION = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
OWNER = re.compile(r"^[A-Za-z0-9-]{1,39}$")


def pin(compose: str, version: str, owner: str) -> str:
    """Point the compose file's defaults at this release's images."""
    pinned = compose.replace(
        "${SITESENSE_IMAGE_PREFIX:-ghcr.io/whoispasindu/sitesense}",
        f"${{SITESENSE_IMAGE_PREFIX:-ghcr.io/{owner.lower()}/sitesense}}",
    ).replace("${SITESENSE_VERSION:-latest}", f"${{SITESENSE_VERSION:-{version}}}")
    if f"SITESENSE_VERSION:-{version}" not in pinned:
        raise SystemExit("docker-compose.prod.yml has no ${SITESENSE_VERSION:-latest} to pin.")
    return pinned


def contents(version: str, owner: str) -> dict[str, tuple[bytes, int]]:
    """Bundle path -> (bytes, file mode)."""
    out: dict[str, tuple[bytes, int]] = {}
    for source, target in FILES.items():
        data = (ROOT / source).read_bytes()
        if target == "docker-compose.prod.yml":
            data = pin(data.decode("utf-8"), version, owner).encode("utf-8")
        mode = 0o755 if target.endswith((".sh", "setup.py", "backup.py")) else 0o644
        out[target] = (data, mode)
    out["VERSION"] = (f"{version}\n".encode(), 0o644)
    return out


def write(version: str, owner: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"sitesense-{version}.tar.gz"
    folder = f"sitesense-{version}"
    mtime = int(time.time())
    with tarfile.open(archive, "w:gz") as tar:
        for name, (data, mode) in sorted(contents(version, owner).items()):
            info = tarfile.TarInfo(f"{folder}/{name}")
            info.size, info.mode, info.mtime = len(data), mode, mtime
            tar.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out_dir / f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--version", required=True)
    parser.add_argument("--owner", required=True, help="GitHub owner of the images (ghcr.io/<owner>/...)")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)
    if not VERSION.match(args.version) or not OWNER.match(args.owner):
        print("Bad --version or --owner.", file=sys.stderr)
        return 2
    print(f"Wrote {write(args.version, args.owner, args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
