"""Phase 12: the client portal (TC-07, TC-10) and the project manager's side of it.

Clients follow progress, the published handover date, milestones, shared photos and approved claims,
and reach no internal data: a schema test walks every client response for cost fields at any depth.
"""

import io
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models import (
    AuditLog,
    BoqSection,
    DailyReport,
    HandoverPublication,
    Notification,
    ProgressClaim,
    Project,
    ReportPhoto,
    Site,
    Task,
    VariationOrder,
)
from app.schemas import portal as portal_schemas
from tests.report_fixtures import Person, image_bytes, report_body

pytestmark = pytest.mark.usefixtures("site_today")

# Field names that would mean internal data reached a client, at any depth.
FORBIDDEN = {
    "budget", "budget_change", "budget_amount", "committed", "rate", "unit_price", "cost", "costs",
    "forecast_final", "variance", "overrun", "overrun_pct", "risk", "score", "level", "drivers",
    "ranges", "sections_over", "margin", "decision_comment", "notes", "comment", "limit_applied",
    "programme_forecast", "published_by", "shared_by", "uploaded_by", "author", "storage_key",
    "supplier", "price", "amount_internal",
}  # fmt: skip


def keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


@pytest.fixture
def client(person: Callable[..., Person], report_project: Project, db: Session) -> Person:
    who = person(Role.CLIENT)
    who.user.client_projects = [report_project]
    db.commit()
    return who


@pytest.fixture
def pm(person: Callable[..., Person]) -> Person:
    return person(Role.PROJECT_MANAGER)


@pytest.fixture
def qs(person: Callable[..., Person]) -> Person:
    return person(Role.QUANTITY_SURVEYOR)


@pytest.fixture
def engineer(person: Callable[..., Person]) -> Person:
    return person(Role.SITE_ENGINEER)


def get(api: TestClient, path: str, who: Person, status: int = 200) -> Any:
    response = api.get(f"/api/v1{path}", headers=who.headers)
    assert response.status_code == status, response.text
    return response.json()


def publish(
    api: TestClient, project: Project, who: Person, day: date, reason: str = "Rain in October."
) -> Any:
    return api.post(
        f"/api/v1/projects/{project.id}/handover",
        json={"handover_date": day.isoformat(), "reason": reason},
        headers=who.headers,
    )


def file_report_with_photo(
    api: TestClient, project: Project, engineer: Person, data: bytes | None = None
) -> str:
    report = api.post(f"/api/v1/projects/{project.id}/reports", json=report_body(), headers=engineer.headers)
    assert report.status_code == 201, report.text
    photo = api.post(
        f"/api/v1/reports/{report.json()['id']}/photos",
        files={"file": ("site.jpg", data or image_bytes("JPEG", (64, 48)), "image/jpeg")},
        data={"caption": "Level 4 slab poured"},
        headers=engineer.headers,
    )
    assert photo.status_code == 201, photo.text
    photo_id: str = photo.json()["id"]
    return photo_id


def share(api: TestClient, project: Project, who: Person, ids: list[str], shared: bool = True) -> Any:
    return api.post(
        f"/api/v1/projects/{project.id}/photos/client-share",
        json={"photo_ids": ids, "shared": shared},
        headers=who.headers,
    )


# --- Access -----------------------------------------------------------------------------------------------


def test_a_client_sees_only_their_own_projects(
    api: TestClient, db: Session, report_project: Project, client: Person, make_site: Callable[..., Site]
) -> None:
    other_site = make_site("KDY-09")
    other = Project(
        code="KD-9", name="Kandy Offices", site_id=other_site.id, client_name="Other",
        project_type="commercial", status="active", contract_value=Decimal("5000.00"),
        start_date=date(2026, 1, 1), planned_end=date(2027, 1, 1),
    )  # fmt: skip
    db.add(other)
    db.commit()

    cards = get(api, "/client/projects", client)
    assert [c["code"] for c in cards] == ["HR-1"]
    for path in (f"/client/projects/{other.id}", f"/client/projects/{other.id}/claims"):
        assert get(api, path, client, 404)["error"]["message"] == "Project not found."

    report_project.status = "cancelled"
    db.commit()
    assert get(api, "/client/projects", client) == []
    get(api, f"/client/projects/{report_project.id}", client, 404)


def test_tc07_the_client_reaches_no_internal_endpoint(
    api: TestClient, report_project: Project, client: Person
) -> None:
    pid = report_project.id
    for path in (
        f"/projects/{pid}/budget",  # TC-07
        f"/projects/{pid}",
        f"/projects/{pid}/boq",
        f"/projects/{pid}/risk",
        f"/projects/{pid}/handover",
        f"/projects/{pid}/photos",
        f"/projects/{pid}/claims",
        "/cost/overview",
        "/analytics/portfolio",
        "/briefing/today",
    ):
        assert api.get(f"/api/v1{path}", headers=client.headers).status_code == 403, path


def test_internal_roles_cannot_use_the_client_endpoints(
    api: TestClient, report_project: Project, pm: Person, qs: Person
) -> None:
    for who in (pm, qs):
        assert api.get("/api/v1/client/projects", headers=who.headers).status_code == 403
        assert api.get(f"/api/v1/client/projects/{report_project.id}", headers=who.headers).status_code == 403


# --- The handover date --------------------------------------------------------------------------------------


def test_the_client_sees_the_contract_date_until_one_is_published(
    api: TestClient, report_project: Project, client: Person
) -> None:
    view = get(api, f"/client/projects/{report_project.id}", client)
    assert view["handover_date"] == "2027-03-31"
    assert view["handover_published"] is False
    assert view["handover"] == {
        "contract_end": "2027-03-31", "published_date": None, "reason": None, "published_at": None,
        "history": [],
    }  # fmt: skip


def test_the_pm_publishes_and_the_client_is_told(
    api: TestClient, db: Session, report_project: Project, report_task: Task, pm: Person, client: Person
) -> None:
    first = publish(api, report_project, pm, date(2027, 4, 30), "Two weeks of heavy rain in October.")
    assert first.status_code == 200, first.text
    second = publish(
        api, report_project, pm, date(2027, 5, 14), "The lift supplier is two weeks late."
    ).json()
    assert second["published"]["handover_date"] == "2027-05-14"
    assert second["published"]["programme_forecast"] is not None  # recorded for the contractor
    assert [e["handover_date"] for e in second["history"]] == ["2027-05-14", "2027-04-30"]

    view = get(api, f"/client/projects/{report_project.id}", client)
    assert view["handover_date"] == "2027-05-14"
    assert view["handover"]["reason"] == "The lift supplier is two weeks late."
    assert [h["handover_date"] for h in view["handover"]["history"]] == ["2027-04-30"]

    notes = db.scalars(select(Notification).where(Notification.user_id == client.user.id)).all()
    assert [n.kind for n in notes] == ["handover_published", "handover_published"]
    assert notes[0].link == f"/client/projects/{report_project.id}"
    actions = db.scalars(select(AuditLog.action).where(AuditLog.action.like("project.handover%"))).all()
    assert actions == ["project.handover_published", "project.handover_published"]


def test_confirming_unchanged_tells_nobody_and_stays_internal(
    api: TestClient, db: Session, report_project: Project, report_task: Task, pm: Person, client: Person
) -> None:
    assert (
        api.post(f"/api/v1/projects/{report_project.id}/handover/confirm", headers=pm.headers).status_code
        == 409
    )
    publish(api, report_project, pm, date(2027, 4, 30))
    confirmed = api.post(f"/api/v1/projects/{report_project.id}/handover/confirm", headers=pm.headers).json()
    assert confirmed["current"]["kind"] == "confirmed"
    assert confirmed["published"]["kind"] == "published"
    # Republishing the same date tells nobody either.
    publish(api, report_project, pm, date(2027, 4, 30), "Still on track for the end of April.")

    view = get(api, f"/client/projects/{report_project.id}", client)
    [earlier] = view["handover"]["history"]
    assert (earlier["handover_date"], earlier["reason"]) == ("2027-04-30", "Rain in October.")
    assert len(db.scalars(select(Notification).where(Notification.user_id == client.user.id)).all()) == 1
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "project.handover_confirmed")) is not None


def test_only_the_pm_publishes_and_dates_are_checked(
    api: TestClient, report_project: Project, report_task: Task, pm: Person, qs: Person, engineer: Person
) -> None:
    assert publish(api, report_project, qs, date(2027, 4, 30)).status_code == 403
    assert publish(api, report_project, engineer, date(2027, 4, 30)).status_code == 403
    assert (
        api.post(f"/api/v1/projects/{report_project.id}/handover/confirm", headers=qs.headers).status_code
        == 403
    )
    assert publish(api, report_project, pm, date(2026, 1, 1)).status_code == 422  # before the start
    assert publish(api, report_project, pm, date(2045, 1, 1)).status_code == 422  # beyond 15 years
    assert publish(api, report_project, pm, date(2027, 4, 30), "  ").status_code == 422
    extra = api.post(
        f"/api/v1/projects/{report_project.id}/handover",
        json={"handover_date": "2027-04-30", "reason": "Fine.", "notify": False},
        headers=pm.headers,
    )
    assert extra.status_code == 422
    # Readers of the programme see the state, without the publish button.
    state = get(api, f"/projects/{report_project.id}/handover", qs)
    assert state["can_publish"] is False
    assert state["suggestions"]["contract_end"] == "2027-03-31"


def age(db: Session, project: Project, days: int) -> None:
    for row in db.scalars(select(HandoverPublication).where(HandoverPublication.project_id == project.id)):
        row.published_at -= timedelta(days=days)
    db.commit()


def test_the_pm_is_reminded_when_the_published_date_looks_out_of_date(
    api: TestClient, db: Session, report_project: Project, report_task: Task, pm: Person, qs: Person
) -> None:
    state = publish(api, report_project, pm, date(2026, 10, 30), "Ahead of plan.").json()
    forecast = date.fromisoformat(state["suggestions"]["programme_forecast"])
    assert forecast > date(2026, 11, 20)  # the frame task alone runs to the end of November
    reminder = state["reminder"]
    assert reminder["forecast_gap_days"] > 7
    assert reminder["reasons"][0].startswith(f"The programme now forecasts {forecast:%d %b %Y}")

    portfolio = get(api, "/analytics/portfolio", pm)
    [item] = portfolio["handover_reminders"]
    assert (item["code"], item["published_date"]) == ("HR-1", "2026-10-30")
    assert get(api, "/analytics/portfolio", qs)["handover_reminders"] is None

    # A date at the programme's forecast is current again.
    assert publish(api, report_project, pm, forecast, "Following the programme.").json()["reminder"] is None
    assert get(api, "/analytics/portfolio", pm)["handover_reminders"] == []


def test_a_date_unreviewed_for_30_days_needs_a_look_and_confirming_clears_it(
    api: TestClient, db: Session, report_project: Project, report_task: Task, pm: Person
) -> None:
    forecast = date.fromisoformat(
        publish(api, report_project, pm, date(2027, 3, 31)).json()["suggestions"]["programme_forecast"]
    )
    publish(api, report_project, pm, forecast, "Following the programme.")
    age(db, report_project, 29)
    assert get(api, f"/projects/{report_project.id}/handover", pm)["reminder"] is None
    age(db, report_project, 2)
    reminder = get(api, f"/projects/{report_project.id}/handover", pm)["reminder"]
    assert reminder["reasons"] == ["Not reviewed for 31 days."]
    confirmed = api.post(f"/api/v1/projects/{report_project.id}/handover/confirm", headers=pm.headers).json()
    assert confirmed["reminder"] is None


# --- Milestones -------------------------------------------------------------------------------------------


def patch_task(api: TestClient, task: Task, who: Person, **body: object) -> Any:
    return api.patch(f"/api/v1/tasks/{task.id}", json=body, headers=who.headers)


def test_the_pm_flags_milestones_with_client_names(
    api: TestClient,
    db: Session,
    report_project: Project,
    report_task: Task,
    pm: Person,
    engineer: Person,
    client: Person,
) -> None:
    assert patch_task(api, report_task, engineer, client_milestone=True).status_code == 403
    assert patch_task(api, report_task, pm, milestone_name="Frame up").status_code == 422  # not a milestone
    assert patch_task(api, report_task, pm, client_milestone="yes").status_code == 422  # strict
    response = patch_task(api, report_task, pm, client_milestone=True, milestone_name="Structure complete")
    assert response.status_code == 200, response.text
    assert (response.json()["client_milestone"], response.json()["milestone_name"]) == (
        True,
        "Structure complete",
    )

    [milestone] = get(api, f"/client/projects/{report_project.id}", client)["milestones"]
    assert milestone["name"] == "Structure complete"
    assert milestone["planned_date"] == "2026-11-30"
    assert milestone["status"] in {"on_track", "late"}
    assert milestone["completed_on"] is None

    # Unflagging drops the client name too.
    cleared = patch_task(api, report_task, pm, client_milestone=False).json()
    assert (cleared["client_milestone"], cleared["milestone_name"]) == (False, None)
    assert get(api, f"/client/projects/{report_project.id}", client)["milestones"] == []


def test_a_milestone_is_never_expected_after_the_published_handover(
    api: TestClient, db: Session, report_project: Project, report_task: Task, pm: Person, client: Person
) -> None:
    patch_task(api, report_task, pm, client_milestone=True)
    publish(api, report_project, pm, date(2026, 11, 2), "Optimistic.")
    [milestone] = get(api, f"/client/projects/{report_project.id}", client)["milestones"]
    assert milestone["name"] == "Frame level 4"  # the task's own name when no client name is given
    assert milestone["expected_date"] == "2026-11-02"


def test_a_finished_milestone_shows_its_date(
    api: TestClient, report_project: Project, report_task: Task, pm: Person, client: Person
) -> None:
    patch_task(api, report_task, pm, client_milestone=True, percent_complete="100")
    [milestone] = get(api, f"/client/projects/{report_project.id}", client)["milestones"]
    assert milestone["status"] == "done"
    assert milestone["completed_on"] == milestone["expected_date"]


# --- Photos -----------------------------------------------------------------------------------------------


def test_photos_are_private_until_the_pm_shares_them(
    api: TestClient,
    db: Session,
    report_project: Project,
    engineer: Person,
    pm: Person,
    qs: Person,
    client: Person,
) -> None:
    first = file_report_with_photo(api, report_project, engineer)
    second = api.post(
        f"/api/v1/reports/{db.get(ReportPhoto, uuid.UUID(first)).report_id}/photos",  # type: ignore[union-attr]
        files={"file": ("b.jpg", image_bytes("JPEG", (32, 32)), "image/jpeg")},
        headers=engineer.headers,
    ).json()["id"]
    assert get(api, f"/client/projects/{report_project.id}", client)["photos"] == []
    get(api, f"/client/photos/{first}", client, 404)

    assert share(api, report_project, qs, [first]).status_code == 403
    assert share(api, report_project, engineer, [first]).status_code == 403
    shared = share(api, report_project, pm, [first, second]).json()  # "share selected"
    assert (shared["total"], shared["shared"]) == (2, 2)

    photos = get(api, f"/client/projects/{report_project.id}", client)["photos"]
    assert {p["id"] for p in photos} == {first, second}
    assert next(p for p in photos if p["id"] == first)["caption"] == "Level 4 slab poured"
    assert api.get(f"/api/v1/client/photos/{first}", headers=client.headers).status_code == 200

    share(api, report_project, pm, [second], shared=False)
    get(api, f"/client/photos/{second}", client, 404)
    stored = db.get(ReportPhoto, uuid.UUID(second))
    assert stored is not None
    assert (stored.shared_with_client, stored.shared_at, stored.shared_by) == (False, None, None)
    entries = db.scalars(select(AuditLog).where(AuditLog.action == "photo.client_share_changed")).all()
    assert [e.details["shared"] for e in entries] == [True, False]


def test_sharing_refuses_photos_of_another_project(
    api: TestClient, db: Session, report_project: Project, engineer: Person, pm: Person
) -> None:
    mine = file_report_with_photo(api, report_project, engineer)
    response = share(api, report_project, pm, [mine, str(uuid.uuid4())])
    assert response.status_code == 404
    photo = db.get(ReportPhoto, uuid.UUID(mine))
    assert photo is not None
    db.refresh(photo)
    assert photo.shared_with_client is False  # nothing changed
    assert share(api, report_project, pm, []).status_code == 422
    assert share(api, report_project, pm, [mine], shared="true").status_code == 422  # type: ignore[arg-type]


def test_the_client_copy_carries_no_metadata(
    api: TestClient,
    app: FastAPI,
    db: Session,
    report_project: Project,
    engineer: Person,
    pm: Person,
    client: Person,
) -> None:
    photo_id = file_report_with_photo(api, report_project, engineer)
    share(api, report_project, pm, [photo_id])
    # Put a file with GPS, device, timestamps and a comment in place, as an older version might have stored.
    exif = Image.Exif()
    exif[0x8825] = {2: (6.0, 53.0, 1.0), 4: (79.0, 51.0, 54.0)}
    exif[0x010F] = "PhoneMaker"
    exif[0x0132] = "2026:10:12 07:31:00"
    raw = image_bytes("JPEG", (64, 48), exif=exif, comment=b"Kamal Perera")
    photo = db.get(ReportPhoto, uuid.UUID(photo_id))
    assert photo is not None
    app.state.storage.save(photo.storage_key, raw)

    response = api.get(f"/api/v1/client/photos/{photo_id}", headers=client.headers)
    assert response.status_code == 200
    image = Image.open(io.BytesIO(response.content))
    assert len(image.getexif()) == 0
    assert "comment" not in image.info
    assert b"PhoneMaker" not in response.content
    assert b"Kamal" not in response.content
    thumb = api.get(f"/api/v1/client/photos/{photo_id}", params={"size": "thumb"}, headers=client.headers)
    assert thumb.status_code == 200


def test_the_pm_lists_the_projects_photos(
    api: TestClient, report_project: Project, engineer: Person, pm: Person, client: Person
) -> None:
    photo_id = file_report_with_photo(api, report_project, engineer)
    listing = get(api, f"/projects/{report_project.id}/photos", pm)
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == photo_id
    assert listing["items"][0]["shared_with_client"] is False
    report = get(api, f"/reports/{listing['items'][0]['report_id']}", pm)
    assert report["photos"][0]["shared_with_client"] is False


# --- Payments ---------------------------------------------------------------------------------------------


def claim(db: Session, project: Project, who: Person, number: str, status: str, certified: str, previous: str,
          when: datetime, paid: date | None = None) -> ProgressClaim:  # fmt: skip
    value = Decimal(certified)
    retention = (value * Decimal("0.05")).quantize(Decimal("0.01"))
    row = ProgressClaim(
        number=number, project_id=project.id, status=status, contract_value=project.contract_value,
        certified_pct=(value / project.contract_value * 100).quantize(Decimal("0.01")), certified_value=value,
        retention=retention, previous_claims=Decimal(previous), amount=value - retention - Decimal(previous),
        notes="Internal: SECRET QS note", submitted_by=who.user.id, submitted_at=when,
        decided_by=None if status == "submitted" else who.user.id,
        decided_at=None if status == "submitted" else when + timedelta(days=1),
        decision_comment=None if status == "submitted" else "Internal: SECRET PM comment",
        paid_on=paid, paid_recorded_by=who.user.id if paid else None,
    )  # fmt: skip
    db.add(row)
    db.commit()
    return row


def test_the_client_sees_approved_claims_and_the_retention_held(
    api: TestClient, db: Session, report_project: Project, qs: Person, client: Person
) -> None:
    t0 = datetime(2026, 6, 1, 4, tzinfo=UTC)
    claim(db, report_project, qs, "PC-0001", "paid", "100000.00", "0.00", t0, paid=date(2026, 6, 20))
    claim(db, report_project, qs, "PC-0002", "returned", "150000.00", "95000.00", t0 + timedelta(days=30))
    claim(db, report_project, qs, "PC-0003", "approved", "200000.00", "95000.00", t0 + timedelta(days=40))
    claim(db, report_project, qs, "PC-0004", "submitted", "260000.00", "190000.00", t0 + timedelta(days=60))

    view = get(api, f"/client/projects/{report_project.id}/claims", client)
    assert [c["number"] for c in view["claims"]] == [
        "PC-0003",
        "PC-0001",
    ]  # newest first; internal ones hidden
    latest = view["claims"][0]
    assert latest == {
        "number": "PC-0003", "status": "approved", "certified_pct": "20.00", "certified_value": "200000.00",
        "retention": "10000.00", "previous_claims": "95000.00", "amount": "95000.00",
        "approved_on": "2026-07-12", "paid_on": None,
    }  # fmt: skip
    assert view["claims"][1]["paid_on"] == "2026-06-20"
    assert Decimal(view["claimed_to_date"]) == Decimal("190000.00")
    assert Decimal(view["paid_to_date"]) == Decimal("95000.00")
    assert Decimal(view["retention_held"]) == Decimal("10000.00")  # cumulative: the latest claim's figure
    assert "end of the defects period" in view["retention_note"]
    assert "SECRET" not in str(view)


def test_the_contract_value_shows_approved_variations(
    api: TestClient, db: Session, report_project: Project, pm: Person, client: Person
) -> None:
    section = BoqSection(project_id=report_project.id, code="A", name="Structure", position=1)
    db.add(section)
    db.flush()
    db.add(
        VariationOrder(
            number="VO-0001", project_id=report_project.id, title="Balcony", description="Extra balcony",
            section_id=section.id, time_impact_days=0, status="approved", approver="pm",
            limit_applied=Decimal("100000"), contract_change=Decimal("25000.00"),
            budget_change=Decimal("20000.00"),
            raised_by=pm.user.id, raised_by_role="pm", raised_at=datetime(2026, 5, 1, tzinfo=UTC),
            priced_at=datetime(2026, 5, 2, tzinfo=UTC), decided_at=datetime(2026, 5, 3, tzinfo=UTC),
        )
    )  # fmt: skip
    report_project.contract_value += Decimal("25000.00")
    db.commit()

    view = get(api, f"/client/projects/{report_project.id}/claims", client)
    assert Decimal(view["original_contract_value"]) == Decimal("1000000.00")
    assert Decimal(view["approved_variations"]) == Decimal("25000.00")
    assert Decimal(view["contract_value"]) == Decimal("1025000.00")
    assert view["retention_held"] == "0.00"
    assert view["claims"] == []


# --- No internal data, at any depth -----------------------------------------------------------------------


def test_no_client_response_carries_internal_fields(
    api: TestClient, db: Session, report_project: Project, report_task: Task, engineer: Person, pm: Person,
    qs: Person, client: Person,
) -> None:  # fmt: skip
    """The schema test (guide, Phase 12): every client endpoint, fully populated, holds no cost field."""
    patch_task(api, report_task, pm, client_milestone=True, milestone_name="Structure complete")
    publish(api, report_project, pm, date(2027, 4, 30))
    publish(api, report_project, pm, date(2027, 5, 14))
    share(api, report_project, pm, [file_report_with_photo(api, report_project, engineer)])
    claim(
        db,
        report_project,
        qs,
        "PC-0001",
        "paid",
        "100000.00",
        "0.00",
        datetime(2026, 6, 1, tzinfo=UTC),
        date(2026, 6, 20),
    )

    responses = [
        get(api, "/client/projects", client),
        get(api, f"/client/projects/{report_project.id}", client),
        get(api, f"/client/projects/{report_project.id}/claims", client),
        get(api, "/client/variations", client),
    ]
    view = responses[1]
    # Really populated, so the walk below sees every kind of field.
    assert view["milestones"]
    assert view["photos"]
    assert view["handover"]["history"]
    assert responses[2]["claims"]
    for body in responses:
        leaked = keys(body) & FORBIDDEN
        assert not leaked, leaked


def schema_fields(model: type[BaseModel], seen: set[type[BaseModel]] | None = None) -> set[str]:
    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)
    names = set(model.model_fields)
    for field in model.model_fields.values():
        for arg in (*getattr(field.annotation, "__args__", ()), field.annotation):
            inner = getattr(arg, "__args__", (arg,))
            for candidate in inner:
                if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                    names |= schema_fields(candidate, seen)
    return names


@pytest.mark.parametrize(
    "schema",
    [portal_schemas.ClientProjectCard, portal_schemas.ClientProject, portal_schemas.ClientClaims],
)
def test_client_schemas_declare_no_internal_field(schema: type[BaseModel]) -> None:
    assert not schema_fields(schema) & FORBIDDEN


def test_client_schemas_are_not_built_on_internal_ones() -> None:
    for name in (
        "ClientProjectCard",
        "ClientProject",
        "ClientClaims",
        "ClientClaim",
        "ClientMilestone",
        "ClientPhoto",
    ):
        schema = getattr(portal_schemas, name)
        for base in schema.__mro__[1:]:
            if issubclass(base, BaseModel) and base is not BaseModel:
                assert base.__module__ == portal_schemas.__name__, (name, base)


# --- TC-10: the client approves a variation ---------------------------------------------------------------


def test_the_project_view_counts_variations_waiting_for_the_client(
    api: TestClient, db: Session, report_project: Project, pm: Person, client: Person
) -> None:
    section = BoqSection(project_id=report_project.id, code="A", name="Structure", position=1)
    db.add(section)
    db.flush()
    db.add(
        VariationOrder(
            number="VO-0002", project_id=report_project.id, title="Extra floor", description="Add a floor",
            section_id=section.id, time_impact_days=30, status="awaiting_client", approver="client",
            limit_applied=Decimal("100000"), contract_change=Decimal("500000.00"),
            budget_change=Decimal("400000.00"),
            raised_by=pm.user.id, raised_by_role="pm", raised_at=datetime(2026, 5, 1, tzinfo=UTC),
            priced_at=datetime(2026, 5, 2, tzinfo=UTC), sent_to_client_at=datetime(2026, 5, 2, tzinfo=UTC),
        )
    )  # fmt: skip
    db.commit()
    [card] = get(api, "/client/projects", client)
    assert card["variations_waiting"] == 1


def test_progress_comes_without_costs(
    api: TestClient, db: Session, report_project: Project, report_task: Task, client: Person
) -> None:
    view = get(api, f"/client/projects/{report_project.id}", client)
    assert view["actual_percent"] == 20.0
    assert view["progress"]
    assert set(view["progress"][0]) == {"date", "planned", "actual"}
    assert view["location"] == "Colombo"


def test_reports_are_never_part_of_the_portal(
    api: TestClient, db: Session, report_project: Project, engineer: Person, client: Person
) -> None:
    file_report_with_photo(api, report_project, engineer)
    report = db.scalars(select(DailyReport)).one()
    assert api.get(f"/api/v1/reports/{report.id}", headers=client.headers).status_code == 403
    view = get(api, f"/client/projects/{report_project.id}", client)
    assert str(report_body()["work_done"]) not in str(view)


# --- Two clients on one site: nothing of B's is visible to A, not even that it exists ---------------------


def not_found(response: Any) -> tuple[int, Any]:
    """The status and error body, without the per-request ID."""
    body = response.json()
    body["error"].pop("request_id", None)
    return response.status_code, body


def test_two_clients_on_one_site_cannot_see_or_detect_each_others_projects(
    api: TestClient, db: Session, report_site: Site, report_project: Project, person: Callable[..., Person],
    pm: Person, engineer: Person,
) -> None:  # fmt: skip
    """Phase 12: client access is per project. Client A's answers for B's records match a missing record."""
    a = person(Role.CLIENT)
    b = person(Role.CLIENT)
    theirs = Project(
        code="HR-2", name="Havelock Towers", site_id=report_site.id, client_name="B Holdings",
        project_type="residential", status="active", contract_value=Decimal("2000000.00"),
        start_date=date(2026, 3, 1), planned_end=date(2027, 6, 30),
    )  # fmt: skip
    db.add(theirs)
    db.flush()
    a.user.client_projects = [report_project]
    b.user.client_projects = [theirs]
    db.commit()

    # B's project has everything a client could be shown: a handover date, a shared photo, a claim and a
    # variation waiting for the client.
    publish(api, theirs, pm, date(2027, 7, 31), "Lift delivery.")
    photo_id = file_report_with_photo(api, theirs, engineer)
    share(api, theirs, pm, [photo_id])
    claim(
        db,
        theirs,
        pm,
        "PC-0099",
        "paid",
        "100000.00",
        "0.00",
        datetime(2026, 6, 1, tzinfo=UTC),
        date(2026, 6, 20),
    )
    section = BoqSection(project_id=theirs.id, code="A", name="Structure", position=1)
    db.add(section)
    db.flush()
    variation = VariationOrder(
        number="VO-0099", project_id=theirs.id, title="Penthouse", description="Add a penthouse",
        section_id=section.id, time_impact_days=20, status="awaiting_client", approver="client",
        limit_applied=Decimal("100000"), contract_change=Decimal("300000.00"),
        budget_change=Decimal("250000.00"), raised_by=pm.user.id, raised_by_role="pm",
        raised_at=datetime(2026, 5, 1, tzinfo=UTC), priced_at=datetime(2026, 5, 2, tzinfo=UTC),
        sent_to_client_at=datetime(2026, 5, 2, tzinfo=UTC),
    )  # fmt: skip
    db.add(variation)
    db.commit()

    # B sees all of it (so each record is real and reachable by its own client)...
    assert [c["code"] for c in get(api, "/client/projects", b)] == ["HR-2"]
    assert api.get(f"/api/v1/client/photos/{photo_id}", headers=b.headers).status_code == 200
    assert [v["number"] for v in get(api, "/client/variations", b)] == ["VO-0099"]

    # ...and A gets exactly the answer it gets for something that does not exist.
    missing = uuid.uuid4()
    pairs = [
        (f"/client/projects/{theirs.id}", f"/client/projects/{missing}"),
        (f"/client/projects/{theirs.id}/claims", f"/client/projects/{missing}/claims"),
        (f"/client/photos/{photo_id}", f"/client/photos/{missing}"),
        (f"/client/photos/{photo_id}?size=thumb", f"/client/photos/{missing}?size=thumb"),
        (f"/client/variations/{variation.id}", f"/client/variations/{missing}"),
    ]
    for real, fake in pairs:
        real_answer = not_found(api.get(f"/api/v1{real}", headers=a.headers))
        assert real_answer[0] == 404, real
        assert real_answer == not_found(api.get(f"/api/v1{fake}", headers=a.headers)), real
    decide_real = api.post(
        f"/api/v1/variations/{variation.id}/client-decision", json={"decision": "approve"}, headers=a.headers
    )
    decide_fake = api.post(
        f"/api/v1/variations/{missing}/client-decision", json={"decision": "approve"}, headers=a.headers
    )
    assert not_found(decide_real) == not_found(decide_fake)
    assert not_found(decide_real)[0] == 404
    db.refresh(variation)
    assert variation.status == "awaiting_client"  # nothing changed

    # A's lists hold only A's own project; nothing of B's appears.
    assert [c["code"] for c in get(api, "/client/projects", a)] == ["HR-1"]
    assert get(api, "/client/variations", a) == []
    everything = str([get(api, "/client/projects", a), get(api, f"/client/projects/{report_project.id}", a)])
    for marker in ("HR-2", "Havelock Towers", "VO-0099", "PC-0099", "Penthouse", photo_id):
        assert marker not in everything

    # Notifications (and so emails) about B's project reach B only.
    notes_a = db.scalars(select(Notification).where(Notification.user_id == a.user.id)).all()
    notes_b = db.scalars(select(Notification).where(Notification.user_id == b.user.id)).all()
    assert notes_a == []
    assert [n.kind for n in notes_b] == ["handover_published"]


def test_a_client_with_no_linked_project_sees_nothing(
    api: TestClient, report_project: Project, person: Callable[..., Person]
) -> None:
    unlinked = person(Role.CLIENT)  # on the site, but linked to nothing
    assert get(api, "/client/projects", unlinked) == []
    get(api, f"/client/projects/{report_project.id}", unlinked, 404)


def test_a_photo_of_another_project_cannot_be_shared_through_this_one(
    api: TestClient, db: Session, report_site: Site, report_project: Project, engineer: Person, pm: Person
) -> None:
    """Found by a mutation check: sharing goes through the project, and only that project's photos count."""
    other = Project(
        code="HR-3", name="Havelock Annex", site_id=report_site.id, client_name="C Holdings",
        project_type="residential", status="active", contract_value=Decimal("500000.00"),
        start_date=date(2026, 3, 1), planned_end=date(2027, 6, 30),
    )  # fmt: skip
    db.add(other)
    db.commit()
    theirs = file_report_with_photo(api, other, engineer)

    response = share(api, report_project, pm, [theirs])
    assert response.status_code == 404
    photo = db.get(ReportPhoto, uuid.UUID(theirs))
    assert photo is not None
    db.refresh(photo)
    assert photo.shared_with_client is False
