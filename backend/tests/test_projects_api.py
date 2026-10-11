from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models import AuditLog, BoqItem, Project, Site, User
from tests.conftest import bearer, login

SAMPLE = Path(__file__).resolve().parent.parent / "app" / "seed_data" / "boq-havelock-residences.csv"
PROJECTS = "/api/v1/projects"
HEADER = b"Section Code,Section Name,Item Code,Description,Unit,Quantity,Rate\n"


@pytest.fixture
def colombo(make_site: Callable[..., Site]) -> Site:
    return make_site("COL-07")


@pytest.fixture
def kandy(make_site: Callable[..., Site]) -> Site:
    return make_site("KDY-02")


@pytest.fixture
def make_project(db: Session) -> Callable[..., Project]:
    def factory(site: Site, code: str = "HR-2026-01", **overrides: object) -> Project:
        values: dict[str, object] = {
            "code": code,
            "name": f"Project {code}",
            "site_id": site.id,
            "client_name": "Havelock Developers",
            "project_type": "residential",
            "status": "active",
            "contract_value": Decimal("1114000000.00"),
            "start_date": date(2026, 3, 2),
            "planned_end": date(2027, 9, 30),
        }
        values.update(overrides)
        project = Project(**values)
        db.add(project)
        db.commit()
        return project

    return factory


def headers_for(
    api: TestClient, make_user: Callable[..., User], role: Role, sites: list[Site]
) -> dict[str, str]:
    user = make_user(role, sites=sites)
    return bearer(login(api, user.email))


def new_project_body(site: Site, **overrides: object) -> dict[str, object]:
    return {
        "code": "hr-2026-01",
        "name": "Havelock Residences",
        "site_id": str(site.id),
        "client_name": "Havelock Developers (Pvt) Ltd",
        "project_type": "residential",
        "contract_value": "1114000000.00",
        "start_date": "2026-03-02",
        "planned_end": "2027-09-30",
        **overrides,
    }


def upload(
    api: TestClient,
    project_id: object,
    headers: dict[str, str],
    *,
    content: bytes,
    name: str = "boq.csv",
    dry_run: bool = True,
) -> Any:
    return api.post(
        f"{PROJECTS}/{project_id}/boq/import",
        params={"dry_run": str(dry_run).lower()},
        files={"file": (name, content, "text/csv")},
        headers=headers,
    )


# --- Creating and editing -------------------------------------------------------------------


def test_project_manager_creates_a_project_on_their_site(
    api: TestClient, make_user: Callable[..., User], colombo: Site, db: Session
) -> None:
    headers = headers_for(api, make_user, Role.PROJECT_MANAGER, [colombo])

    response = api.post(PROJECTS, json=new_project_body(colombo), headers=headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["code"] == "HR-2026-01"
    assert body["status"] == "planning"
    assert body["contract_value"] == "1114000000.00"
    assert body["site"]["code"] == "COL-07"
    assert body["boq_total"] == "0.00"
    db.expire_all()
    assert db.scalar(select(AuditLog.action).order_by(AuditLog.occurred_at.desc())) == "project.created"


def test_project_manager_cannot_create_on_an_unassigned_site(
    api: TestClient, make_user: Callable[..., User], colombo: Site, kandy: Site
) -> None:
    headers = headers_for(api, make_user, Role.PROJECT_MANAGER, [colombo])

    response = api.post(PROJECTS, json=new_project_body(kandy), headers=headers)

    assert response.status_code == 404


@pytest.mark.parametrize("role", [Role.SITE_ENGINEER, Role.QUANTITY_SURVEYOR, Role.ADMIN, Role.CLIENT])
def test_only_project_managers_create_projects(
    api: TestClient, make_user: Callable[..., User], colombo: Site, role: Role
) -> None:
    headers = headers_for(api, make_user, role, [colombo] if role != Role.ADMIN else [])

    assert api.post(PROJECTS, json=new_project_body(colombo), headers=headers).status_code == 403


def test_project_input_is_validated(api: TestClient, make_user: Callable[..., User], colombo: Site) -> None:
    headers = headers_for(api, make_user, Role.PROJECT_MANAGER, [colombo])
    bad = [
        {"planned_end": "2026-01-01"},
        {"planned_end": "9999-12-31"},
        {"contract_value": "0"},
        {"contract_value": "-5"},
        {"contract_value": "12.345"},
        {"code": "bad code!"},
        {"project_type": "castle"},
        {"status": "finished"},
        {"owner": "me"},
    ]
    for override in bad:
        response = api.post(PROJECTS, json=new_project_body(colombo, **override), headers=headers)
        assert response.status_code == 422, override


def test_duplicate_code_and_closed_site(
    api: TestClient,
    make_user: Callable[..., User],
    colombo: Site,
    make_project: Callable[..., Project],
    make_site: Callable[..., Site],
) -> None:
    closed = make_site("OLD-01", active=False)
    make_project(colombo, code="HR-2026-01")
    headers = headers_for(api, make_user, Role.PROJECT_MANAGER, [colombo, closed])

    assert api.post(PROJECTS, json=new_project_body(colombo), headers=headers).status_code == 409
    closed_site = api.post(PROJECTS, json=new_project_body(closed, code="NEW-1"), headers=headers)
    assert closed_site.status_code == 422


def test_update_project_and_reject_bad_dates(
    api: TestClient, make_user: Callable[..., User], colombo: Site, make_project: Callable[..., Project]
) -> None:
    project = make_project(colombo)
    headers = headers_for(api, make_user, Role.PROJECT_MANAGER, [colombo])
    url = f"{PROJECTS}/{project.id}"

    updated = api.patch(url, json={"status": "on_hold", "name": "Renamed"}, headers=headers)
    bad_dates = api.patch(url, json={"planned_end": "2020-01-01"}, headers=headers)
    forever = api.patch(url, json={"planned_end": "9999-12-31"}, headers=headers)
    assert forever.status_code == 422
    cannot_move = api.patch(url, json={"site_id": str(colombo.id)}, headers=headers)
    null_name = api.patch(url, json={"name": None}, headers=headers)

    assert updated.status_code == 200
    assert updated.json()["status"] == "on_hold"
    assert bad_dates.status_code == 422
    assert cannot_move.status_code == 422
    assert null_name.status_code == 422


# --- Reading and site scoping ---------------------------------------------------------------


def test_site_engineer_only_sees_projects_on_assigned_sites(
    api: TestClient,
    make_user: Callable[..., User],
    colombo: Site,
    kandy: Site,
    make_project: Callable[..., Project],
) -> None:
    mine = make_project(colombo, code="MINE-1")
    other = make_project(kandy, code="OTHER-1")
    headers = headers_for(api, make_user, Role.SITE_ENGINEER, [colombo])

    listed = api.get(PROJECTS, headers=headers).json()
    own = api.get(f"{PROJECTS}/{mine.id}", headers=headers)
    hidden = api.get(f"{PROJECTS}/{other.id}", headers=headers)
    hidden_boq = api.get(f"{PROJECTS}/{other.id}/boq", headers=headers)

    assert [p["code"] for p in listed] == ["MINE-1"]
    assert own.status_code == 200
    assert hidden.status_code == hidden_boq.status_code == 404
    assert hidden.json() == {**hidden.json(), "error": {**hidden.json()["error"], "code": "not_found"}}


def test_procurement_sees_every_project_and_client_sees_none(
    api: TestClient,
    make_user: Callable[..., User],
    colombo: Site,
    kandy: Site,
    make_project: Callable[..., Project],
) -> None:
    make_project(colombo, code="A-1")
    make_project(kandy, code="B-2")

    procurement = api.get(PROJECTS, headers=headers_for(api, make_user, Role.PROCUREMENT_OFFICER, []))
    client = api.get(PROJECTS, headers=headers_for(api, make_user, Role.CLIENT, [colombo]))

    assert {p["code"] for p in procurement.json()} == {"A-1", "B-2"}
    assert client.status_code == 403  # the client portal arrives in Phase 12, with cost-free schemas


def test_list_filters_and_search_escapes_wildcards(
    api: TestClient, make_user: Callable[..., User], colombo: Site, make_project: Callable[..., Project]
) -> None:
    make_project(colombo, code="HR-1", name="Havelock Residences", status="active")
    make_project(
        colombo, code="FV-2", name="Fort 50% View", status="planning", client_name="Southern Coast Homes"
    )
    headers = headers_for(api, make_user, Role.PROJECT_MANAGER, [colombo])

    def codes(**params: str) -> list[str]:
        return [p["code"] for p in api.get(PROJECTS, params=params, headers=headers).json()]

    assert codes(status="planning") == ["FV-2"]
    assert codes(q="havelock") == ["HR-1"]
    assert codes(q="50%") == ["FV-2"]
    assert codes(q="%") == ["FV-2"]  # literal "%", not "match everything" (HR-1 has none)
    assert codes(q="_") == []


def test_project_detail_includes_team_from_site_assignments(
    api: TestClient,
    make_user: Callable[..., User],
    colombo: Site,
    kandy: Site,
    make_project: Callable[..., Project],
) -> None:
    project = make_project(colombo)
    engineer = make_user(Role.SITE_ENGINEER, sites=[colombo])
    make_user(Role.SITE_ENGINEER, sites=[kandy])
    make_user(Role.SITE_ENGINEER, sites=[colombo], active=False)
    headers = headers_for(api, make_user, Role.PROJECT_MANAGER, [colombo])

    team = api.get(f"{PROJECTS}/{project.id}", headers=headers).json()["team"]

    assert engineer.full_name in {m["full_name"] for m in team}
    assert len(team) == 2  # the engineer and the PM making the request; not Kandy, not inactive


# --- BOQ import -------------------------------------------------------------------------------


@pytest.fixture
def qs_headers(api: TestClient, make_user: Callable[..., User], colombo: Site) -> dict[str, str]:
    return headers_for(api, make_user, Role.QUANTITY_SURVEYOR, [colombo])


def test_dry_run_reports_without_saving(
    api: TestClient,
    qs_headers: dict[str, str],
    colombo: Site,
    make_project: Callable[..., Project],
    db: Session,
) -> None:
    project = make_project(colombo)

    response = upload(api, project.id, qs_headers, content=SAMPLE.read_bytes(), name=SAMPLE.name)

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["dry_run"] is True
    assert report["imported"] is False
    assert report["ok_rows"] == 40
    assert report["skipped_rows"] == 8
    assert report["error_rows"] == 0
    assert report["boq_total"] == "1113985000.00"
    assert len(report["sections"]) == 8
    assert db.scalar(select(BoqItem).where(BoqItem.project_id == project.id)) is None


def test_import_saves_boq_with_section_totals_and_budget(
    api: TestClient,
    qs_headers: dict[str, str],
    colombo: Site,
    make_project: Callable[..., Project],
    db: Session,
) -> None:
    project = make_project(colombo)

    report = upload(api, project.id, qs_headers, content=SAMPLE.read_bytes(), dry_run=False).json()
    boq = api.get(f"{PROJECTS}/{project.id}/boq", headers=qs_headers).json()
    detail = api.get(f"{PROJECTS}/{project.id}", headers=qs_headers).json()

    assert report["imported"] is True
    assert boq["item_count"] == 40
    assert boq["boq_total"] == "1113985000.00"
    assert boq["budget_total"] == "981742500.00"
    substructure = next(s for s in boq["sections"] if s["code"] == "B")
    assert substructure["name"] == "Substructure"
    assert substructure["amount"] == "91490000.00"
    assert substructure["budget_amount"] == "80583500.00"
    assert [i["item_code"] for i in substructure["items"]] == ["B.01", "B.02", "B.03", "B.04", "B.05"]
    assert substructure["items"][0] == {
        **substructure["items"][0],
        "quantity": "2850.000",
        "rate": "1450.00",
        "amount": "4132500.00",
    }
    assert detail["boq_total"] == boq["boq_total"]
    assert [s["code"] for s in detail["sections"]] == ["A", "B", "C", "D", "E", "F", "G", "H"]
    db.expire_all()
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "boq.imported"))
    assert entry is not None
    assert entry.details["items"] == 40


def test_invalid_file_imports_nothing_even_when_not_a_dry_run(
    api: TestClient,
    qs_headers: dict[str, str],
    colombo: Site,
    make_project: Callable[..., Project],
    db: Session,
) -> None:
    project = make_project(colombo)
    content = HEADER + b"A,P,A.1,Ok,nr,1,10\nA,P,A.2,Bad,nr,-1,10\n"

    report = upload(api, project.id, qs_headers, content=content, dry_run=False).json()

    assert report["imported"] is False
    assert report["error_rows"] == 1
    assert report["rows"][1]["errors"] == [{"column": "quantity", "message": "Must be greater than zero."}]
    assert db.scalar(select(BoqItem).where(BoqItem.project_id == project.id)) is None


def test_reimport_replaces_the_previous_boq(
    api: TestClient, qs_headers: dict[str, str], colombo: Site, make_project: Callable[..., Project]
) -> None:
    project = make_project(colombo)
    upload(api, project.id, qs_headers, content=SAMPLE.read_bytes(), dry_run=False)
    small = (
        b"Section Code,Section Name,Item Code,Description,Unit,Quantity,Rate\nZ,Only,Z.1,One item,nr,2,50\n"
    )

    preview = upload(api, project.id, qs_headers, content=small).json()
    upload(api, project.id, qs_headers, content=small, dry_run=False)
    boq = api.get(f"{PROJECTS}/{project.id}/boq", headers=qs_headers).json()

    assert preview["replaces_items"] == 40
    assert boq["item_count"] == 1
    assert boq["boq_total"] == "100.00"


def test_file_level_problems_are_clear_errors(
    api: TestClient, qs_headers: dict[str, str], colombo: Site, make_project: Callable[..., Project]
) -> None:
    project = make_project(colombo)

    wrong_type = upload(api, project.id, qs_headers, content=b"%PDF-1.7", name="boq.pdf")
    no_header = upload(api, project.id, qs_headers, content=b"just,some\nrandom,text\n")
    too_big = upload(api, project.id, qs_headers, content=b"a" * (5 * 1024 * 1024 + 10))
    path_name = upload(api, project.id, qs_headers, content=SAMPLE.read_bytes(), name="../../etc/boq.csv")

    assert wrong_type.status_code == 422
    assert "xlsx or .csv" in wrong_type.json()["error"]["message"]
    assert no_header.status_code == 422
    assert "No header row" in no_header.json()["error"]["message"]
    assert too_big.status_code == 413
    assert path_name.json()["file_name"] == "boq.csv"


def test_upload_route_alone_accepts_large_bodies(
    api: TestClient, qs_headers: dict[str, str], colombo: Site, make_project: Callable[..., Project]
) -> None:
    project = make_project(colombo)
    content = (
        SAMPLE.read_bytes() + b"\n" * 4000
    )  # ~ 10 KB: over the 2 KB test default, under the upload limit

    assert upload(api, project.id, qs_headers, content=content).status_code == 200
    big_json = api.post(
        PROJECTS,
        content=b"{" + b" " * 4000 + b"}",
        headers={**qs_headers, "Content-Type": "application/json"},
    )
    assert big_json.status_code == 413


@pytest.mark.parametrize("role", [Role.PROJECT_MANAGER, Role.SITE_ENGINEER, Role.PROCUREMENT_OFFICER])
def test_only_quantity_surveyors_import_boqs(
    api: TestClient,
    make_user: Callable[..., User],
    colombo: Site,
    make_project: Callable[..., Project],
    role: Role,
) -> None:
    project = make_project(colombo)
    headers = headers_for(api, make_user, role, [colombo] if role != Role.PROCUREMENT_OFFICER else [])

    assert upload(api, project.id, headers, content=SAMPLE.read_bytes()).status_code == 403


def test_qs_cannot_import_into_a_project_on_another_site(
    api: TestClient, qs_headers: dict[str, str], kandy: Site, make_project: Callable[..., Project]
) -> None:
    project = make_project(kandy, code="K-1")

    assert upload(api, project.id, qs_headers, content=SAMPLE.read_bytes()).status_code == 404


# --- Budget lines ---------------------------------------------------------------------------


def test_qs_adjusts_a_budget_line_and_it_is_audited(
    api: TestClient,
    qs_headers: dict[str, str],
    colombo: Site,
    make_project: Callable[..., Project],
    db: Session,
) -> None:
    project = make_project(colombo)
    upload(api, project.id, qs_headers, content=SAMPLE.read_bytes(), dry_run=False)
    section = next(
        s
        for s in api.get(f"{PROJECTS}/{project.id}/boq", headers=qs_headers).json()["sections"]
        if s["code"] == "A"
    )
    url = f"{PROJECTS}/{project.id}/budget-lines/{section['budget_line_id']}"

    response = api.patch(url, json={"budget_amount": "30000000.00"}, headers=qs_headers)
    negative = api.patch(url, json={"budget_amount": "-1"}, headers=qs_headers)

    assert response.status_code == 200
    assert response.json()["budget_amount"] == "30000000.00"
    assert response.json()["amount"] == "32510000.00"  # contract value unchanged
    assert negative.status_code == 422
    db.expire_all()
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "budget_line.updated"))
    assert entry is not None
    assert entry.details == {"section": "A", "from": "28990000.00", "to": "30000000.00"}


def test_budget_line_must_belong_to_the_project(
    api: TestClient, qs_headers: dict[str, str], colombo: Site, make_project: Callable[..., Project]
) -> None:
    first = make_project(colombo, code="P-1")
    second = make_project(colombo, code="P-2")
    upload(api, first.id, qs_headers, content=SAMPLE.read_bytes(), dry_run=False)
    line_id = api.get(f"{PROJECTS}/{first.id}/boq", headers=qs_headers).json()["sections"][0][
        "budget_line_id"
    ]

    response = api.patch(
        f"{PROJECTS}/{second.id}/budget-lines/{line_id}", json={"budget_amount": "1"}, headers=qs_headers
    )

    assert response.status_code == 404


def test_the_contract_changes_only_through_variations_once_under_way(
    api: TestClient,
    make_user: Callable[..., User],
    colombo: Site,
    make_project: Callable[..., Project],
    db: Session,
) -> None:
    """Phase 8 security review: a direct edit would bypass the QS's price, BR-09 and the client's approval."""
    project = make_project(colombo)
    headers = headers_for(api, make_user, Role.PROJECT_MANAGER, [colombo])
    url = f"{PROJECTS}/{project.id}"

    for change in ({"contract_value": "1200000000.50"}, {"planned_end": "2027-12-31"}):
        refused = api.patch(url, json=change, headers=headers)
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == "contract_locked"
    assert api.get(url, headers=headers).json()["contract_locked"] is True

    project.status = "planning"
    db.commit()
    assert api.get(url, headers=headers).json()["contract_locked"] is False
    corrected = api.patch(url, json={"contract_value": "1200000000.50"}, headers=headers)
    assert corrected.json()["contract_value"] == "1200000000.50"
    same = api.patch(url, json={"contract_value": "1200000000.50", "name": "Same value"}, headers=headers)
    assert same.status_code == 200  # an unchanged value is not a change
