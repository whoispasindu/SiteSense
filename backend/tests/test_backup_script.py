"""scripts/backup.py (ADR 0020): the archive it writes, the checks before a restore, the commands.

The script runs Docker on a server, so these tests cover everything around that: the end-to-end
backup, wipe and restore was run against a real installation (see the pull request).
"""

import importlib.util
import json
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sitesense_backup", REPO / "scripts" / "backup.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


backup = _load()
CREATED = datetime(2026, 11, 15, 2, 0, tzinfo=UTC)


def make_backup(tmp_path: Path, revision: str = "0019") -> Path:
    work = tmp_path / "work"
    work.mkdir()
    database, media = work / backup.DATABASE, work / backup.MEDIA
    database.write_bytes(b"PGDMP fake dump")
    media.write_bytes(b"fake photos")
    target = tmp_path / "sitesense-backup-20261115-020000.tar"
    meta = backup.make_meta(CREATED, "1.0.0", revision, database, media)
    backup.write_archive(target, meta, database, media)
    return target


def test_a_backup_holds_the_database_the_photos_and_what_they_are(tmp_path: Path) -> None:
    path = make_backup(tmp_path)
    with tarfile.open(path) as tar:
        assert sorted(tar.getnames()) == ["backup.json", "database.dump", "media.tar.gz"]
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600
    out = tmp_path / "out"
    out.mkdir()
    meta = backup.open_archive(path, out)
    assert meta["sitesense_version"] == "1.0.0"
    assert meta["schema_revision"] == "0019"
    assert meta["created_at"] == "2026-11-15T02:00:00+00:00"
    assert (out / "database.dump").read_bytes() == b"PGDMP fake dump"


def test_a_damaged_backup_is_refused(tmp_path: Path) -> None:
    path = make_backup(tmp_path)
    with tarfile.open(path) as tar:
        meta = json.loads(tar.extractfile("backup.json").read())  # type: ignore[union-attr]
    meta["files"]["database.dump"]["sha256"] = "0" * 64
    work = tmp_path / "work"
    tampered = tmp_path / "tampered.tar"
    backup.write_archive(tampered, meta, work / "database.dump", work / "media.tar.gz")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(backup.BackupError, match="damaged"):
        backup.open_archive(tampered, out)


def test_something_else_is_not_taken_for_a_backup(tmp_path: Path) -> None:
    other = tmp_path / "other.tar"
    with tarfile.open(other, "w") as tar:
        tar.add(__file__, arcname="notes.txt")
    with pytest.raises(backup.BackupError, match="not a SiteSense backup"):
        backup.open_archive(other, tmp_path)


def test_a_backup_from_a_newer_release_is_refused_and_older_ones_are_upgraded() -> None:
    assert backup.parse_head("0019 (head)\n") == "0019"
    assert backup.is_newer("0021", "0019")
    assert not backup.is_newer("0011", "0019")  # migrations bring it up to date on start
    assert not backup.is_newer("0019", "0019")
    with pytest.raises(backup.BackupError, match="schema"):
        backup.parse_head("FAILED: no config")


def test_old_backups_are_pruned_newest_kept(tmp_path: Path) -> None:
    names = [f"sitesense-backup-202611{day:02d}-020000.tar" for day in range(1, 6)]
    for name in names:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "keep-me.txt").write_bytes(b"not a backup")
    removed = backup.prune(tmp_path, keep=2)
    assert sorted(p.name for p in removed) == names[:3]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([*names[3:], "keep-me.txt"])
    assert backup.prune(tmp_path, keep=0) == []  # 0 keeps everything


def test_the_settings_file_is_read_as_setup_writes_it(tmp_path: Path) -> None:
    env = tmp_path / ".env.prod"
    env.write_text("# comment\nSITESENSE_VERSION='1.0.0'\nSITESENSE_EMAIL_FROM='SiteSense <a@b.c>'\nEMPTY=\n")
    assert backup.read_env(env) == {
        "SITESENSE_VERSION": "1.0.0",
        "SITESENSE_EMAIL_FROM": "SiteSense <a@b.c>",
        "EMPTY": "",
    }


def test_the_commands(tmp_path: Path) -> None:
    compose = backup.Compose(tmp_path, tmp_path / ".env.prod", project="trial")
    assert compose.base()[:4] == ["docker", "compose", "-p", "trial"]
    assert compose.dump_database()[-7:] == [
        "db",
        "pg_dump",
        "-U",
        "postgres",
        "-d",
        "sitesense",
        "--format=custom",
    ]
    restore = compose.restore_database()
    assert {"--clean", "--if-exists", "--single-transaction", "--exit-on-error"} <= set(restore)
    assert compose.pack_media()[-5:] == ["-czf", "-", "-C", "/data/media", "."]
    assert compose.stop_app()[-4:] == ["proxy", "frontend", "backend", "scheduler"]  # never the database
    assert compose.start()[-3:] == ["up", "-d", "--wait"]
    assert "docker-compose.build.yml" not in " ".join(compose.base())
    built = backup.Compose(tmp_path, tmp_path / ".env.prod", build=True)
    assert str(tmp_path / "docker-compose.build.yml") in built.base()


def test_main_needs_the_installations_settings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "docker-compose.prod.yml").write_text("services: {}\n", encoding="utf-8")
    assert backup.main(["--dir", str(tmp_path), "create"]) == 1
    assert ".env.prod is missing" in capsys.readouterr().err
