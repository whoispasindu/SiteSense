"""Phase 7: AI tags on daily reports, the author's confirmation, follow-up actions, risk re-scoring."""

import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.nlp.tagger import LOW_CONFIDENCE
from app.ai.risk.features import build as build_features
from app.core import clock
from app.core.permissions import Role
from app.models import (
    AuditLog,
    EmailOutbox,
    Notification,
    Project,
    ReportAction,
    ReportIssue,
    RiskScore,
    User,
)
from tests.materials_fixtures import Boq, Who, needed_by
from tests.report_fixtures import Person, report_body


def file_report(api: TestClient, project: Project, who: Person | Who, problems: str | None) -> str:
    response = api.post(
        f"/api/v1/projects/{project.id}/reports", json=report_body(problems=problems), headers=who.headers
    )
    assert response.status_code == 201, response.text
    report_id: str = response.json()["id"]
    return report_id


def analyze(api: TestClient, report_id: str, who: Person | Who) -> dict:  # type: ignore[type-arg]
    response = api.post(f"/api/v1/reports/{report_id}/analyze", headers=who.headers)
    assert response.status_code == 200, response.text
    body: dict = response.json()  # type: ignore[type-arg]
    return body


def confirm(api: TestClient, report_id: str, who: Person | Who, issues: list[dict], **actions: object):  # type: ignore[no-untyped-def,type-arg]
    return api.post(
        f"/api/v1/reports/{report_id}/issues/confirm",
        json={"issues": issues, "actions": actions},
        headers=who.headers,
    )


def keep(issue: dict, **changes: str) -> dict:  # type: ignore[type-arg]
    return {
        "suggestion_id": issue["id"],
        "category": issue["category"],
        "severity": issue["severity"],
        **changes,
    }


def notes_of(db: Session, user: User, kind: str) -> list[Notification]:
    return list(
        db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.kind == kind))
    )


# --- Analysis --------------------------------------------------------------------------------------------


def test_tc06_cement_not_delivered_again(
    api: TestClient, db: Session, report_project: Project, engineer: Person
) -> None:
    """TC-06: tagged material delay, high severity; confirming it re-scores the project's risk."""
    report_id = file_report(api, report_project, engineer, "cement not delivered again")
    db.execute(delete(RiskScore))  # the report itself re-scores; start clean to see the confirm
    db.commit()

    body = analyze(api, report_id, engineer)

    [issue] = body["issues"]
    assert (issue["category"], issue["severity"], issue["status"]) == ("material_delay", "high", "suggested")
    assert (issue["source"], issue["low_confidence"]) == ("ai", False)
    assert (body["can_confirm"], body["confirmed"]) == (True, False)
    assert body["model_version"] == "1.1.0"  # DistilBERT category, TF-IDF severity

    confirmed = confirm(api, report_id, engineer, [keep(issue)]).json()

    assert confirmed["issues"][0]["status"] == "confirmed"
    assert (confirmed["confirmed"], confirmed["can_confirm"]) == (True, False)
    row = db.scalar(select(RiskScore).where(RiskScore.project_id == report_project.id))
    assert row is not None  # re-scored
    assert row.features["values"]["issues_material_14"] == 1.0


def test_analysing_again_replaces_the_suggestions(
    api: TestClient, report_project: Project, engineer: Person
) -> None:
    report_id = file_report(api, report_project, engineer, "Mixer broke down. Rain all day.")

    first = analyze(api, report_id, engineer)
    second = analyze(api, report_id, engineer)

    assert len(first["issues"]) == len(second["issues"]) == 2
    assert {i["id"] for i in first["issues"]}.isdisjoint({i["id"] for i in second["issues"]})


def test_analysis_is_rate_limited_per_client(
    api: TestClient, report_project: Project, engineer: Person
) -> None:
    report_id = file_report(api, report_project, engineer, "Crane down")
    statuses = [
        api.post(f"/api/v1/reports/{report_id}/analyze", headers=engineer.headers).status_code
        for _ in range(31)
    ]

    assert statuses[:30] == [200] * 30
    assert statuses[30] == 429


def test_a_report_without_problems_has_nothing_to_tag(
    api: TestClient, report_project: Project, engineer: Person
) -> None:
    report_id = file_report(api, report_project, engineer, None)

    assert analyze(api, report_id, engineer)["issues"] == []


def test_low_confidence_tags_are_flagged(api: TestClient, report_project: Project, engineer: Person) -> None:
    """The low-confidence path: highlighted for the author, who must decide."""
    report_id = file_report(api, report_project, engineer, "the thing with the stuff")

    body = analyze(api, report_id, engineer)

    [issue] = body["issues"]
    assert issue["low_confidence"] is True
    assert issue["confidence"] < body["low_confidence_below"] == 0.6


def test_names_are_redacted_before_storage(
    api: TestClient, db: Session, report_project: Project, engineer: Person, person: Callable[..., Person]
) -> None:
    mason = person(Role.SITE_ENGINEER)
    report_id = file_report(api, report_project, engineer, f"{mason.user.full_name} fell from the scaffold")

    [issue] = analyze(api, report_id, engineer)["issues"]

    assert mason.user.full_name not in issue["snippet"]
    assert "[PERSON]" in issue["snippet"]
    stored = db.scalar(select(ReportIssue).where(ReportIssue.report_id == uuid.UUID(report_id)))
    assert stored is not None
    assert "[PERSON]" in stored.snippet
    assert (issue["category"], issue["severity"]) == ("safety", "high")


# --- Confirmation ------------------------------------------------------------------------------------------


def test_the_author_edits_removes_and_adds_tags(
    api: TestClient, db: Session, report_project: Project, engineer: Person
) -> None:
    report_id = file_report(api, report_project, engineer, "Mixer broke down. Rain all day.")
    mixer, rain = analyze(api, report_id, engineer)["issues"]

    response = confirm(
        api, report_id, engineer,
        [keep(mixer, severity="low"),
         {"category": "labour", "severity": "medium", "snippet": "Two masons absent"}],
    )  # fmt: skip

    assert response.status_code == 200, response.text
    issues = {i["snippet"]: i for i in response.json()["issues"]}
    assert issues[mixer["snippet"]]["severity"] == "low"
    assert issues[mixer["snippet"]]["edited"] is True
    assert issues[rain["snippet"]]["status"] == "removed"
    added = issues["Two masons absent"]
    assert (added["source"], added["confidence"], added["status"]) == ("manual", None, "confirmed")
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "report.issues_confirmed"))
    assert audit is not None
    assert audit.details | {"actions": []} == {
        "confirmed": 2,
        "removed": 1,
        "added": 1,
        "edited": 1,
        "actions": [],
    }


def test_confirming_twice_is_refused(api: TestClient, report_project: Project, engineer: Person) -> None:
    report_id = file_report(api, report_project, engineer, "Crane down")
    [issue] = analyze(api, report_id, engineer)["issues"]
    confirm(api, report_id, engineer, [keep(issue)])

    assert confirm(api, report_id, engineer, [keep(issue)]).status_code == 409
    assert api.post(f"/api/v1/reports/{report_id}/analyze", headers=engineer.headers).status_code == 409


@pytest.mark.parametrize(
    ("issues", "message"),
    [
        ([{"suggestion_id": str(uuid.uuid4()), "category": "labour", "severity": "low"}], "does not belong"),
        ([{"category": "labour", "severity": "low"}], "needs the text"),
        ([{"category": "fire", "severity": "low", "snippet": "abc"}], ""),
    ],
)
def test_confirmation_is_validated(
    api: TestClient,
    report_project: Project,
    engineer: Person,
    issues: list[dict[str, str]],
    message: str,
) -> None:
    report_id = file_report(api, report_project, engineer, "Crane down")
    analyze(api, report_id, engineer)

    response = confirm(api, report_id, engineer, issues)

    assert response.status_code == 422
    assert message in response.text


def test_each_suggestion_can_be_confirmed_once(
    api: TestClient, report_project: Project, engineer: Person
) -> None:
    report_id = file_report(api, report_project, engineer, "Crane down")
    [issue] = analyze(api, report_id, engineer)["issues"]

    assert confirm(api, report_id, engineer, [keep(issue), keep(issue)]).status_code == 422


def test_only_the_author_on_the_day_checks_issues(
    api: TestClient, report_project: Project, engineer: Person, manager: Person,
    person: Callable[..., Person], site_today: Callable,  # type: ignore[type-arg]
) -> None:  # fmt: skip
    report_id = file_report(api, report_project, engineer, "Crane down")

    assert api.post(f"/api/v1/reports/{report_id}/analyze", headers=manager.headers).status_code == 403
    assert confirm(api, report_id, person(Role.SITE_ENGINEER), []).status_code == 403
    assert api.get(f"/api/v1/reports/{report_id}/issues", headers=manager.headers).status_code == 200

    site_today(clock.site_today() + timedelta(days=1))  # the next day: the report is closed
    assert api.post(f"/api/v1/reports/{report_id}/analyze", headers=engineer.headers).status_code == 403


def test_issues_on_other_sites_are_invisible(
    api: TestClient,
    report_project: Project,
    engineer: Person,
    person: Callable[..., Person],
    make_site: Callable,  # type: ignore[type-arg]
) -> None:
    report_id = file_report(api, report_project, engineer, "Crane down")
    outsider = person(Role.PROJECT_MANAGER, sites=[make_site("KDY-77")])

    assert api.get(f"/api/v1/reports/{report_id}/issues", headers=outsider.headers).status_code == 404
    assert api.post(f"/api/v1/reports/{report_id}/analyze", headers=outsider.headers).status_code == 404
    assert (
        api.get(f"/api/v1/projects/{report_project.id}/report-actions", headers=outsider.headers).status_code
        == 404
    )


# --- Follow-up actions -----------------------------------------------------------------------------------


def test_high_severity_alerts_the_project_managers(
    api: TestClient, db: Session, report_project: Project, engineer: Person, manager: Person
) -> None:
    report_id = file_report(api, report_project, engineer, "cement not delivered again")
    [issue] = analyze(api, report_id, engineer)["issues"]

    body = confirm(api, report_id, engineer, [keep(issue)], pm_alert=True).json()

    [action] = body["actions"]
    assert (action["kind"], action["status"], action["can_close"]) == ("pm_alert", "done", False)
    [note] = notes_of(db, manager.user, "issue_high")
    assert note.title == "High-severity issue on HR-1"
    assert note.link == f"/reports/{report_id}"
    assert notes_of(db, engineer.user, "issue_high") == []


def emails_to(db: Session, user: User) -> list[EmailOutbox]:
    return list(db.scalars(select(EmailOutbox).where(EmailOutbox.user_id == user.id)))


def test_high_severity_email_follows_the_authors_confirmation_never_the_ai(
    api: TestClient, db: Session, report_project: Project, engineer: Person, manager: Person
) -> None:
    """Phase 11: the urgent email goes out only for a high severity the author has confirmed."""
    report_id = file_report(api, report_project, engineer, "cement not delivered again")
    [issue] = analyze(api, report_id, engineer)["issues"]
    assert issue["severity"] == "high"  # the AI's suggestion
    # A suggestion alone alerts nobody, in the app or by email.
    assert notes_of(db, manager.user, "issue_high") == []
    assert emails_to(db, manager.user) == []

    # The author marks it medium: no alert can be asked for, and no email goes out.
    refused = confirm(api, report_id, engineer, [keep(issue, severity="medium")], pm_alert=True)
    assert refused.status_code == 422
    assert confirm(api, report_id, engineer, [keep(issue, severity="medium")]).status_code == 200
    assert notes_of(db, manager.user, "issue_high") == []
    assert emails_to(db, manager.user) == []


def test_a_confirmed_high_severity_issue_is_emailed_at_once(
    api: TestClient, db: Session, report_project: Project, engineer: Person, manager: Person
) -> None:
    report_id = file_report(api, report_project, engineer, "cement not delivered again")
    [issue] = analyze(api, report_id, engineer)["issues"]
    confirm(api, report_id, engineer, [keep(issue)], pm_alert=True)

    [email] = emails_to(db, manager.user)
    assert (email.kind, email.subject) == ("urgent", "SiteSense: High-severity issue on HR-1")
    assert "cement" not in email.body  # the report's words stay in the app
    assert emails_to(db, engineer.user) == []


def test_stop_work_is_cleared_only_by_the_project_manager(
    api: TestClient,
    db: Session,
    report_project: Project,
    engineer: Person,
    manager: Person,
    person: Callable[..., Person],
) -> None:
    """BR-11 (the part in Phase 7): a stop-work flag stays open until the PM clears it."""
    report_id = file_report(api, report_project, engineer, "A helper fell from the scaffold")
    [issue] = analyze(api, report_id, engineer)["issues"]
    [action] = confirm(
        api, report_id, engineer, [keep(issue)], stop_work=True, stop_work_scope="project"
    ).json()["actions"]
    assert (action["kind"], action["status"], action["can_close"]) == ("stop_work", "open", False)
    assert len(notes_of(db, manager.user, "stop_work")) == 1
    close = f"/api/v1/report-actions/{action['id']}/close"

    assert api.post(close, json={"resolution": "done"}, headers=engineer.headers).status_code == 403
    assert (
        api.post(
            close, json={"resolution": "done"}, headers=person(Role.QUANTITY_SURVEYOR).headers
        ).status_code
        == 403
    )
    listed = api.get(f"/api/v1/projects/{report_project.id}/report-actions", headers=manager.headers).json()
    assert [(a["kind"], a["can_close"]) for a in listed] == [("stop_work", True)]

    cleared = api.post(close, json={"resolution": "done"}, headers=manager.headers)

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["status"] == "done"
    assert api.post(close, json={"resolution": "done"}, headers=manager.headers).status_code == 409
    assert (
        api.get(f"/api/v1/projects/{report_project.id}/report-actions", headers=manager.headers).json() == []
    )
    assert db.scalar(select(AuditLog).where(AuditLog.action == "report_action.closed")) is not None


@pytest.mark.parametrize(
    ("problems", "action", "message"),
    [
        ("Crane down", "material_request", "material delay"),
        ("Crane needs servicing soon", "pm_alert", "high-severity"),
        ("Cement late", "stop_work", "safety issue"),
    ],
)
def test_follow_ups_must_match_a_confirmed_issue(
    api: TestClient, report_project: Project, engineer: Person, problems: str, action: str, message: str
) -> None:
    report_id = file_report(api, report_project, engineer, problems)
    [issue] = analyze(api, report_id, engineer)["issues"]

    response = confirm(api, report_id, engineer, [keep(issue, severity="low")], **{action: True})

    assert response.status_code == 422
    assert message in response.json()["error"]["message"]


def test_a_material_request_raised_from_a_follow_up_closes_it(
    api: TestClient, db: Session, boq: Boq, se: Who, qs: Who
) -> None:
    report_id = file_report(api, boq.project, se, "Cement not delivered again")
    [issue] = analyze(api, report_id, se)["issues"]
    [action] = confirm(api, report_id, se, [keep(issue)], material_request=True).json()["actions"]
    assert (action["kind"], action["status"], action["can_close"]) == ("material_request", "open", True)
    assert "Cement not delivered again" in action["summary"]
    request_body = {
        "project_id": str(boq.project.id), "boq_item_id": str(boq.cement.id), "quantity": "50",
        "needed_by": needed_by(), "report_action_id": action["id"],
    }  # fmt: skip

    created = api.post("/api/v1/material-requests", json=request_body, headers=se.headers)

    assert created.status_code == 201, created.text
    stored = db.get(ReportAction, uuid.UUID(action["id"]))
    assert stored is not None
    db.refresh(stored)
    assert (stored.status, str(stored.request_id)) == ("done", created.json()["id"])
    # The follow-up is used up: it cannot start a second request.
    again = api.post("/api/v1/material-requests", json=request_body, headers=se.headers)
    assert again.status_code == 422
    assert "not an open material request" in again.json()["error"]["message"]


def test_a_follow_up_from_another_project_cannot_be_used(
    api: TestClient, db: Session, boq: Boq, se: Who
) -> None:
    other = Project(
        code="OT-1", name="Other", site_id=boq.project.site_id, client_name="C", project_type="commercial",
        status="active", contract_value=Decimal("5000000"), start_date=boq.project.start_date,
        planned_end=boq.project.planned_end,
    )  # fmt: skip
    db.add(other)
    db.commit()
    report_id = file_report(api, other, se, "Cement not delivered again")
    [issue] = analyze(api, report_id, se)["issues"]
    [action] = confirm(api, report_id, se, [keep(issue)], material_request=True).json()["actions"]
    body = {"project_id": str(boq.project.id), "boq_item_id": str(boq.cement.id), "quantity": "5",
            "needed_by": needed_by(), "report_action_id": action["id"]}  # fmt: skip

    assert api.post("/api/v1/material-requests", json=body, headers=se.headers).status_code == 422


def test_the_author_may_dismiss_a_material_follow_up(
    api: TestClient, report_project: Project, engineer: Person
) -> None:
    report_id = file_report(api, report_project, engineer, "Cement not delivered again")
    [issue] = analyze(api, report_id, engineer)["issues"]
    [action] = confirm(api, report_id, engineer, [keep(issue)], material_request=True).json()["actions"]

    response = api.post(
        f"/api/v1/report-actions/{action['id']}/close",
        json={"resolution": "dismissed"},
        headers=engineer.headers,
    )

    assert response.json()["status"] == "dismissed"
    assert (
        api.post(
            f"/api/v1/report-actions/{uuid.uuid4()}/close",
            json={"resolution": "done"},
            headers=engineer.headers,
        ).status_code
        == 404
    )


# --- Risk inputs -------------------------------------------------------------------------------------------


def test_only_confirmed_issues_in_the_last_14_days_count(
    api: TestClient, db: Session, report_project: Project, engineer: Person
) -> None:
    report_id = file_report(
        api,
        report_project,
        engineer,
        "Mixer broke down. A worker fell from the ladder. Beam detail clashes with the duct.",
    )
    issues = analyze(api, report_id, engineer)["issues"]
    today = clock.site_today()
    assert (
        build_features(db, report_project, today).values["issues_safety_14"] == 0
    )  # suggestions do not count

    confirm(api, report_id, engineer, [keep(i) for i in issues])

    values = build_features(db, report_project, today).values
    assert (values["issues_safety_14"], values["issues_design_14"], values["issues_material_14"]) == (1, 1, 0)
    assert build_features(db, report_project, today + timedelta(days=14)).values["issues_safety_14"] == 0


def test_get_issues_for_a_reader(
    api: TestClient, report_project: Project, engineer: Person, manager: Person
) -> None:
    report_id = file_report(api, report_project, engineer, "Crane down")
    analyze(api, report_id, engineer)

    body = api.get(f"/api/v1/reports/{report_id}/issues", headers=manager.headers).json()

    assert body["can_confirm"] is False  # not the author
    assert body["issues"][0]["status"] == "suggested"
    assert body["low_confidence_below"] == LOW_CONFIDENCE


def test_stop_work_names_its_tasks_or_the_whole_project(
    api: TestClient, db: Session, report_project: Project, engineer: Person, manager: Person
) -> None:
    """BR-11 (Phase 9): the author picks the stopped tasks, or the whole project."""
    from datetime import date as day

    from app.models import Task

    slab = Task(project_id=report_project.id, code="T-1", name="Slab", planned_start=day(2026, 1, 5),
                planned_end=day(2026, 12, 31), weight=Decimal("50"), position=1)  # fmt: skip
    db.add(slab)
    db.commit()
    report_id = file_report(api, report_project, engineer, "A helper fell from the scaffold")
    [issue] = analyze(api, report_id, engineer)["issues"]

    none_chosen = confirm(api, report_id, engineer, [keep(issue)], stop_work=True)
    stranger = confirm(api, report_id, engineer, [keep(issue)], stop_work=True,
                       stop_work_task_ids=[str(uuid.uuid4())])  # fmt: skip
    chosen = confirm(
        api, report_id, engineer, [keep(issue)], stop_work=True, stop_work_task_ids=[str(slab.id)]
    )

    assert none_chosen.status_code == 422
    assert "Choose the tasks" in none_chosen.json()["error"]["message"]
    assert stranger.status_code == 422
    [action] = chosen.json()["actions"]
    assert (action["stop_scope"], action["stop_task_ids"], action["can_edit_scope"]) == (
        "tasks",
        [str(slab.id)],
        False,
    )
    listed = api.get(f"/api/v1/projects/{report_project.id}/report-actions", headers=manager.headers).json()
    assert listed[0]["can_edit_scope"] is True
