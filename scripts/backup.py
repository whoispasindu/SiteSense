"""Back up a SiteSense installation, and restore one (docs/self-hosting.md, ADR 0020).

    python3 backup.py create                      # into ./backups, keeping the last 14
    python3 backup.py create --out /srv/backups --keep 30
    python3 backup.py restore backups/sitesense-backup-20261115-020000.tar

A backup is one file, `sitesense-backup-<UTC time>.tar`, readable by its owner only, holding:

- database.dump   the whole database (pg_dump, custom format);
- media.tar.gz    every site photo (the media volume);
- backup.json     when it was made, the release and database schema it came from, and the SHA-256
                  and size of the two files above.

It does not hold .env.prod: keep that file safe separately. A restore needs the same
SITESENSE_MFA_KEY, or everyone's two-step sign-in has to be set up again.

Restoring replaces all data in this installation with the backup's, then starts SiteSense, which
upgrades the database if the backup came from an older release. A backup from a newer release than
the images here is refused. Run it from the folder with docker-compose.prod.yml and .env.prod.

Standard-library Python 3.9 or later, and Docker Compose v2.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

HERE = Path(__file__).resolve().parent
COMPOSE_FILE = "docker-compose.prod.yml"
BUILD_FILE = "docker-compose.build.yml"
FORMAT = 1
DATABASE, MEDIA, META = "database.dump", "media.tar.gz", "backup.json"
NAME = re.compile(r"^sitesense-backup-\d{8}-\d{6}\.tar$")
APP_SERVICES = ["proxy", "frontend", "backend", "scheduler"]


class BackupError(Exception):
    """Something to tell the operator; the message says what to do."""


# --- Docker Compose ------------------------------------------------------------------------------


@dataclass
class Compose:
    directory: Path
    env_file: Path
    project: str | None = None
    build: bool = False  # images built from a checkout (setup.py --build), not pulled

    def base(self) -> list[str]:
        command = ["docker", "compose"]
        if self.project:
            command += ["-p", self.project]
        command += ["-f", str(self.directory / COMPOSE_FILE)]
        if self.build:
            command += ["-f", str(self.directory / BUILD_FILE)]
        return [*command, "--env-file", str(self.env_file)]

    def running(self) -> list[str]:
        return [*self.base(), "ps", "--status", "running", "--services"]

    def schema_revision(self) -> list[str]:
        sql = "SELECT version_num FROM alembic_version"
        return [
            *self.base(),
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "postgres",
            "-d",
            "sitesense",
            "-At",
            "-c",
            sql,
        ]

    def dump_database(self) -> list[str]:
        return [*self.base(), "exec", "-T", "db", "pg_dump", "-U", "postgres", "-d", "sitesense",
                "--format=custom"]  # fmt: skip

    def pack_media(self) -> list[str]:
        return [*self.base(), "run", "--rm", "--no-deps", "-T", "--entrypoint", "tar", "backend",
                "-czf", "-", "-C", "/data/media", "."]  # fmt: skip

    def image_head(self) -> list[str]:
        return [*self.base(), "run", "--rm", "--no-deps", "-T", "--entrypoint", "alembic", "backend", "heads"]

    def stop_app(self) -> list[str]:
        return [*self.base(), "stop", *APP_SERVICES]

    def start_database(self) -> list[str]:
        return [*self.base(), "up", "-d", "--wait", "db"]

    def restore_database(self) -> list[str]:
        return [*self.base(), "exec", "-T", "db", "pg_restore", "-U", "postgres", "-d", "sitesense",
                "--clean", "--if-exists", "--single-transaction", "--exit-on-error"]  # fmt: skip

    def restore_media(self) -> list[str]:
        script = "find /data/media -mindepth 1 -delete && tar -xzf - -C /data/media"
        return [*self.base(), "run", "--rm", "--no-deps", "-T", "--entrypoint", "sh", "backend", "-c", script]

    def start(self) -> list[str]:
        return [*self.base(), "up", "-d", "--wait"]


def run(command: list[str], *, stdin: IO[bytes] | None = None, stdout: IO[bytes] | None = None) -> bytes:
    """Runs a step; binary output goes to `stdout` when given, else is returned."""
    result = subprocess.run(  # noqa: S603 - fixed docker compose arguments, no shell
        command, stdin=stdin, stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()[-1500:]
        raise BackupError(f"`{' '.join(command[-6:])}` failed (exit {result.returncode}). {detail}".strip())
    return result.stdout if stdout is None else b""


# --- The archive ---------------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_env(path: Path) -> dict[str, str]:
    """KEY=value lines, as setup.py writes them (single quotes are literal, as in Compose)."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def make_meta(
    created: datetime, version: str, revision: str, database: Path, media: Path
) -> dict[str, object]:
    return {
        "format": FORMAT,
        "created_at": created.isoformat(timespec="seconds"),
        "sitesense_version": version,
        "schema_revision": revision,
        "files": {
            DATABASE: {"bytes": database.stat().st_size, "sha256": sha256_file(database)},
            MEDIA: {"bytes": media.stat().st_size, "sha256": sha256_file(media)},
        },
    }


def write_archive(target: Path, meta: dict[str, object], database: Path, media: Path) -> None:
    partial = target.with_suffix(".partial")
    with tarfile.open(partial, "w") as tar:
        data = json.dumps(meta, indent=2).encode("utf-8")
        info = tarfile.TarInfo(META)
        info.size, info.mode = len(data), 0o600
        tar.addfile(info, io.BytesIO(data))
        tar.add(database, arcname=DATABASE)
        tar.add(media, arcname=MEDIA)
    partial.chmod(0o600)  # company data: its owner only
    partial.replace(target)


def open_archive(path: Path, into: Path) -> dict[str, object]:
    """Checks a backup and unpacks its two files into `into`; returns its backup.json."""
    try:
        with tarfile.open(path, "r") as tar:
            names = sorted(tar.getnames())
            if names != sorted([META, DATABASE, MEDIA]):
                raise BackupError(f"{path.name} is not a SiteSense backup (it holds {', '.join(names)}).")
            meta_file = tar.extractfile(META)
            if meta_file is None:
                raise BackupError(f"{path.name} has no readable {META}.")
            meta = json.loads(meta_file.read().decode("utf-8"))
            for name in (DATABASE, MEDIA):
                member = tar.getmember(name)
                if not member.isfile():
                    raise BackupError(f"{name} in {path.name} is not a file.")
                source = tar.extractfile(member)
                assert source is not None
                with (into / name).open("wb") as out:
                    shutil.copyfileobj(source, out)
    except (tarfile.TarError, OSError, ValueError) as exc:
        raise BackupError(f"Cannot read {path}: {exc}") from exc
    if meta.get("format") != FORMAT:
        raise BackupError(f"{path.name} uses backup format {meta.get('format')}, this script reads {FORMAT}.")
    files = meta.get("files")
    if not isinstance(files, dict):
        raise BackupError(f"{path.name} has no file list.")
    for name in (DATABASE, MEDIA):
        expected = files.get(name, {})
        actual = into / name
        if actual.stat().st_size != expected.get("bytes") or sha256_file(actual) != expected.get("sha256"):
            raise BackupError(f"{name} in {path.name} is damaged (its size or SHA-256 does not match).")
    return dict(meta)


def parse_head(output: str) -> str:
    """'0019 (head)' -> '0019'."""
    match = re.search(r"^(\S+) \(head\)", output, flags=re.MULTILINE)
    if not match:
        raise BackupError(f"Cannot tell which database schema these images have ({output.strip()!r}).")
    return match.group(1)


def is_newer(revision: str, head: str) -> bool:
    """Revisions are numbered 0001, 0002, ...: a backup from a newer release has a higher number."""
    if revision.isdigit() and head.isdigit():
        return int(revision) > int(head)
    return False


def prune(directory: Path, keep: int) -> list[Path]:
    """Deletes all but the newest `keep` backups in `directory` (by the time in their names)."""
    backups = sorted(p for p in directory.iterdir() if NAME.match(p.name))
    old = backups[:-keep] if keep > 0 else []
    for path in old:
        path.unlink()
    return old


# --- Commands ------------------------------------------------------------------------------------


def create(compose: Compose, out: Path, keep: int, now: datetime | None = None) -> Path:
    if "db" not in run(compose.running()).decode().split():
        raise BackupError("The database is not running. Start SiteSense first (docker compose ... up -d).")
    version = read_env(compose.env_file).get("SITESENSE_VERSION", "unknown")
    revision = run(compose.schema_revision()).decode().strip()
    created = now or datetime.now(timezone.utc)  # noqa: UP017 - datetime.UTC needs Python 3.11
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"sitesense-backup-{created:%Y%m%d-%H%M%S}.tar"
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        database, media = Path(tmp) / DATABASE, Path(tmp) / MEDIA
        print("Dumping the database...", flush=True)
        with database.open("wb") as handle:
            run(compose.dump_database(), stdout=handle)
        print("Packing the photos...", flush=True)
        with media.open("wb") as handle:
            run(compose.pack_media(), stdout=handle)
        write_archive(target, make_meta(created, version, revision, database, media), database, media)
    removed = prune(out, keep)
    size = target.stat().st_size / 1_048_576
    print(f"Backup written: {target} ({size:.1f} MB, schema {revision}, release {version}).")
    if removed:
        print(f"Removed {len(removed)} older backup(s), keeping the last {keep}.")
    print("Copy it off this server, and keep .env.prod safe separately (it is not in the backup).")
    return target


def restore(compose: Compose, path: Path, *, confirmed: bool) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        meta = open_archive(path, Path(tmp))
        revision = str(meta.get("schema_revision", ""))
        head = parse_head(run(compose.image_head()).decode())
        if is_newer(revision, head):
            raise BackupError(
                f"This backup is from a newer SiteSense (schema {revision}) than these images "
                f"(schema {head}). "
                f"Set SITESENSE_VERSION to {meta.get('sitesense_version')} or later, pull, and restore again."
            )
        print(
            f"Backup of {meta.get('created_at')}, release {meta.get('sitesense_version')}, schema {revision}."
        )
        if not confirmed:
            answer = input(
                "This replaces ALL data in this installation with the backup. Type restore to go on: "
            )
            if answer.strip().lower() != "restore":
                raise BackupError("Nothing was changed.")
        print("Stopping SiteSense (the database stays up)...", flush=True)
        run(compose.stop_app())
        run(compose.start_database())
        print("Restoring the database...", flush=True)
        with (Path(tmp) / DATABASE).open("rb") as handle:
            run(compose.restore_database(), stdin=handle)
        print("Restoring the photos...", flush=True)
        with (Path(tmp) / MEDIA).open("rb") as handle:
            run(compose.restore_media(), stdin=handle)
    print("Starting SiteSense (it upgrades the database first if the backup is from an older release)...")
    run(compose.start())
    print("Restored. Everyone signs in as before; if .env.prod is not the one the backup was made with,")
    print(
        "two-step sign-in has to be set up again (a Company Admin resets it; create-admin makes a new admin)."
    )


def find_directory(explicit: Path | None) -> Path:
    for candidate in [explicit] if explicit else [HERE, HERE.parent]:
        if candidate is not None and (candidate / COMPOSE_FILE).is_file():
            return candidate.resolve()
    raise BackupError(
        f"Cannot find {COMPOSE_FILE}. Run this from the release bundle's folder, or pass --dir."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up or restore SiteSense (docs/self-hosting.md).")
    parser.add_argument("--dir", type=Path, help="the folder with docker-compose.prod.yml")
    parser.add_argument("--env-file", type=Path, help="default: .env.prod there")
    parser.add_argument("--project", help="docker compose project name (default: sitesense-prod)")
    parser.add_argument("--build", action="store_true", help="the images were built with setup.py --build")
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("create", help="write a backup file")
    make.add_argument(
        "--out", type=Path, default=Path("backups"), help="folder for backups (default: ./backups)"
    )
    make.add_argument(
        "--keep", type=int, default=14, help="newest backups to keep there (default: 14; 0 keeps all)"
    )
    back = commands.add_parser("restore", help="replace all data with a backup's")
    back.add_argument("file", type=Path)
    back.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args(argv)
    try:
        directory = find_directory(args.dir)
        env_file = (args.env_file or directory / ".env.prod").resolve()
        if not env_file.is_file():
            raise BackupError(
                f"{env_file} is missing: run setup first, or put the installation's .env.prod there."
            )
        compose = Compose(directory, env_file, args.project, args.build)
        if args.command == "create":
            if args.keep < 0:
                raise BackupError("--keep cannot be negative.")
            create(compose, args.out.resolve(), args.keep)
        else:
            restore(compose, args.file.resolve(), confirmed=args.yes)
    except BackupError as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
