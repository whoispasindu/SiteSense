import io
import zlib
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.permissions import Role
from app.integrations.storage import LocalStorage, StorageKeyError
from app.models import AuditLog, DailyReport, Project, ReportPhoto, Site
from app.services import photos
from tests.conftest import make_settings
from tests.report_fixtures import Person, image_bytes, report_body

pytestmark = pytest.mark.usefixtures("site_today")

MAX_PHOTO_BYTES = 200 * 1024


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(
        media_root=str(tmp_path / "media"), max_photo_bytes=MAX_PHOTO_BYTES, max_photos_per_report=3
    )


@pytest.fixture
def report(api: TestClient, report_project: Project, engineer: Person) -> dict[str, str]:
    response = api.post(
        f"/api/v1/projects/{report_project.id}/reports", json=report_body(), headers=engineer.headers
    )
    assert response.status_code == 201, response.text
    result: dict[str, str] = response.json()
    return result


def upload(
    api: TestClient,
    report_id: str,
    who: Person,
    data: bytes,
    name: str = "site.jpg",
    caption: str | None = None,
) -> httpx2.Response:
    form = {"caption": caption} if caption is not None else {}
    return api.post(
        f"/api/v1/reports/{report_id}/photos",
        files={"file": (name, data, "image/jpeg")},
        data=form,
        headers=who.headers,
    )


def jpeg_with_gps() -> bytes:
    exif = Image.Exif()
    exif[0x8825] = {2: (6.0, 53.0, 1.0), 4: (79.0, 51.0, 54.0)}  # GPS IFD: latitude, longitude
    exif[0x010F] = "PhoneMaker"
    exif[0x0112] = 6  # orientation: rotate 90 degrees
    return image_bytes("JPEG", (80, 40), exif=exif)


# --- Accepted uploads ------------------------------------------------------------------------
def test_jpeg_comments_do_not_survive_the_re_encode(
    api: TestClient, report: dict[str, str], engineer: Person, manager: Person
) -> None:
    """Found in the Phase 12 review: Pillow writes a JPEG comment it read, even with no arguments."""
    data = image_bytes("JPEG", (64, 48), comment=b"Taken by Kamal Perera at 6.87, 79.86")
    photo = upload(api, report["id"], engineer, data).json()

    for size in ("full", "thumb"):
        stored = api.get(f"/api/v1/photos/{photo['id']}", params={"size": size}, headers=manager.headers)
        image = Image.open(io.BytesIO(stored.content))
        assert "comment" not in image.info
        assert b"Kamal" not in stored.content


def test_engineer_uploads_a_photo_that_the_pm_can_view(
    api: TestClient, report: dict[str, str], engineer: Person, manager: Person, app: FastAPI, db: Session
) -> None:
    response = upload(api, report["id"], engineer, jpeg_with_gps(), caption="  Level 4 rebar  ")

    assert response.status_code == 201, response.text
    photo = response.json()
    assert photo["caption"] == "Level 4 rebar"
    # EXIF orientation was applied, so the stored image is upright (portrait).
    assert (photo["width"], photo["height"]) == (40, 80)

    detail = api.get(f"/api/v1/reports/{report['id']}", headers=manager.headers).json()
    assert [p["id"] for p in detail["photos"]] == [photo["id"]]

    full = api.get(f"/api/v1/photos/{photo['id']}", headers=manager.headers)
    assert full.status_code == 200
    assert full.headers["content-type"] == "image/jpeg"
    assert full.headers["cache-control"] == "private, max-age=600"
    assert full.headers["x-content-type-options"] == "nosniff"
    stored = Image.open(io.BytesIO(full.content))
    assert stored.format == "JPEG"
    assert len(stored.getexif()) == 0  # GPS position and camera details are gone

    thumb = api.get(f"/api/v1/photos/{photo['id']}", params={"size": "thumb"}, headers=manager.headers)
    assert thumb.status_code == 200
    assert thumb.content != full.content

    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "report.photo_added")) == 1


@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
def test_png_and_webp_are_converted_to_jpeg(
    api: TestClient, report: dict[str, str], engineer: Person, fmt: str
) -> None:
    response = upload(api, report["id"], engineer, image_bytes(fmt), name=f"photo.{fmt.lower()}")

    assert response.status_code == 201, response.text
    content = api.get(f"/api/v1/photos/{response.json()['id']}", headers=engineer.headers).content
    assert content[:3] == b"\xff\xd8\xff"


def test_large_photos_are_scaled_down(api: TestClient, report: dict[str, str], engineer: Person) -> None:
    big = image_bytes("JPEG", (3000, 1000), quality=30)

    response = upload(api, report["id"], engineer, big)

    assert response.status_code == 201, response.text
    assert (response.json()["width"], response.json()["height"]) == (2560, 853)


# --- Rejected uploads (file type and size checks) ----------------------------------------------


def _png_bomb() -> bytes:
    """A tiny PNG that claims 100,000 x 100,000 pixels."""
    import struct

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", 100_000, 100_000, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\0" * 64))
        + chunk(b"IEND", b"")
    )


REJECTED = {
    "script renamed .jpg": b"#!/bin/sh\nrm -rf /\n",
    "html": b"<html><script>alert(1)</script></html>",
    "svg": b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    "pdf": b"%PDF-1.7\n1 0 obj\n",
    "gif": b"GIF89a\x01\x00\x01\x00\x00\x00\x00;",
    "empty": b"",
    "truncated jpeg": image_bytes("JPEG", (200, 200))[:200],
    "jpeg header then junk": b"\xff\xd8\xff\xe0" + b"\x00" * 300,
    "riff that is not webp": b"RIFF\x00\x00\x00\x00WAVEfmt ",
    "decompression bomb": _png_bomb(),
}


@pytest.mark.parametrize("data", REJECTED.values(), ids=REJECTED.keys())
def test_non_images_and_broken_images_are_rejected(
    api: TestClient, report: dict[str, str], engineer: Person, data: bytes, db: Session, settings: Settings
) -> None:
    response = upload(api, report["id"], engineer, data)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] in {"photo_rejected", "validation_error"}
    assert db.scalar(select(func.count(ReportPhoto.id))) == 0
    media = Path(settings.media_root)
    assert not media.exists() or not any(p.is_file() for p in media.rglob("*"))


def test_oversized_photos_are_rejected(api: TestClient, report: dict[str, str], engineer: Person) -> None:
    noise = Image.effect_noise((900, 900), 100).convert("RGB")
    out = io.BytesIO()
    noise.save(out, format="PNG")
    assert len(out.getvalue()) > MAX_PHOTO_BYTES

    response = upload(api, report["id"], engineer, out.getvalue(), name="big.png")

    assert response.status_code == 413


def test_photo_count_is_limited(api: TestClient, report: dict[str, str], engineer: Person) -> None:
    for _ in range(3):
        assert upload(api, report["id"], engineer, image_bytes()).status_code == 201

    response = upload(api, report["id"], engineer, image_bytes())

    assert response.status_code == 422
    assert "at most 3 photos" in response.json()["error"]["message"]


def test_caption_is_limited(api: TestClient, report: dict[str, str], engineer: Person) -> None:
    response = upload(api, report["id"], engineer, image_bytes(), caption="x" * 201)

    assert response.status_code == 422


# --- Who may add, see and remove photos ----------------------------------------------------------


def test_only_the_author_adds_photos_on_the_day(
    api: TestClient,
    report: dict[str, str],
    engineer: Person,
    person: Callable[..., Person],
    db: Session,
) -> None:
    colleague = person(Role.SITE_ENGINEER)
    assert upload(api, report["id"], colleague, image_bytes()).status_code == 403

    stored = db.get(DailyReport, report["id"])
    assert stored is not None
    stored.submitted_at = stored.submitted_at - timedelta(days=1)
    db.commit()
    assert upload(api, report["id"], engineer, image_bytes()).status_code == 422


def test_pm_cannot_upload(api: TestClient, report: dict[str, str], manager: Person) -> None:
    assert upload(api, report["id"], manager, image_bytes()).status_code == 403


def test_photos_on_other_sites_are_invisible(
    api: TestClient,
    report: dict[str, str],
    engineer: Person,
    person: Callable[..., Person],
    make_site: Callable[..., Site],
) -> None:
    photo = upload(api, report["id"], engineer, image_bytes()).json()
    outsider = person(Role.PROJECT_MANAGER, sites=[make_site("KDY-02")])

    assert api.get(f"/api/v1/photos/{photo['id']}", headers=outsider.headers).status_code == 404
    assert api.get(f"/api/v1/photos/{photo['id']}").status_code == 401
    assert (
        api.get(
            f"/api/v1/photos/{photo['id']}", params={"size": "../../x"}, headers=engineer.headers
        ).status_code
        == 422
    )


def test_author_deletes_a_photo_and_its_files(
    api: TestClient, report: dict[str, str], engineer: Person, settings: Settings, db: Session
) -> None:
    photo = upload(api, report["id"], engineer, image_bytes()).json()
    files = list(Path(settings.media_root).rglob("*.jpg"))
    assert len(files) == 2  # full size and thumbnail

    response = api.delete(f"/api/v1/photos/{photo['id']}", headers=engineer.headers)

    assert response.status_code == 204
    assert not any(p.exists() for p in files)
    assert api.get(f"/api/v1/photos/{photo['id']}", headers=engineer.headers).status_code == 404
    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "report.photo_deleted")) == 1


def test_missing_file_answers_404_not_500(
    api: TestClient, report: dict[str, str], engineer: Person, settings: Settings
) -> None:
    photo = upload(api, report["id"], engineer, image_bytes()).json()
    for path in Path(settings.media_root).rglob("*.jpg"):
        path.unlink()

    assert api.get(f"/api/v1/photos/{photo['id']}", headers=engineer.headers).status_code == 404


def test_upload_body_limit_applies_to_photo_route_only(
    api: TestClient, report: dict[str, str], engineer: Person, report_project: Project
) -> None:
    # 2 KB general limit in tests; the photo route allows the photo limit plus multipart overhead.
    assert upload(api, report["id"], engineer, image_bytes("PNG", (300, 300))).status_code == 201
    big_json = report_body(work_done="x" * 4000)
    response = api.post(
        f"/api/v1/projects/{report_project.id}/reports", json=big_json, headers=engineer.headers
    )
    assert response.status_code == 413


# --- Units -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key", ["../etc/passwd", "ab/../../x.jpg", "ABCDEF.jpg", "0" * 32 + ".png", "0" * 32 + ".jpg/..", ""]
)
def test_storage_refuses_keys_it_did_not_generate(tmp_path: Path, key: str) -> None:
    storage = LocalStorage(tmp_path)

    with pytest.raises(StorageKeyError):
        storage.save(key, b"x")
    with pytest.raises(StorageKeyError):
        storage.read(key)


def test_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    key = "a" * 32 + ".jpg"

    storage.save(key, b"data")

    assert storage.read(key) == b"data"
    assert (tmp_path / "aa" / key).exists()
    storage.delete(key)
    storage.delete(key)  # deleting twice is fine
    assert not (tmp_path / "aa" / key).exists()


def test_sniffing_ignores_the_declared_type() -> None:
    assert photos.sniff_format(image_bytes("JPEG")) == "JPEG"
    assert photos.sniff_format(image_bytes("PNG")) == "PNG"
    assert photos.sniff_format(image_bytes("WEBP")) == "WEBP"
    assert photos.sniff_format(b"GIF89a") is None


def test_format_mismatch_is_rejected() -> None:
    """A PNG body behind a JPEG signature: the decoder and the signature disagree."""
    with pytest.raises(photos.PhotoRejectedError):
        photos.process(b"\xff\xd8\xff" + image_bytes("PNG")[3:])
