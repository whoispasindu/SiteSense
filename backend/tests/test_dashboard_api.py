"""Phase 11: the portfolio endpoint, the weekly PDF and email preferences, against a real database."""

from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, DailyReport, NotificationPreference
from tests.dashboard_fixtures import PEOPLE, World


def portfolio(api: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = api.get("/api/v1/analytics/portfolio", headers=headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


# --- KPIs and sections --------------------------------------------------------------------------------


def test_portfolio_kpis_from_live_data(api: TestClient, world: World) -> None:
    result = portfolio(api, world.pm.headers)
    k = result["kpis"]
    assert result["as_of"] == world.today.isoformat()
    assert k["total_projects"] == 1  # the other site's project is not counted (BR-03)
    assert k["active_projects"] == 1
    assert k["reports_due_today"] == 1
    assert k["reports_filed_today"] == 1
    assert k["issues_this_week"] == 2  # confirmed only: the removed suggestion does not count
    assert k["stop_work_open"] == 1
    assert k["high_risk"] == 1
    assert k["waiting_for_you"] == 1  # the material request at the PM's stage
    assert k["average_actual_pct"] == 20.0
    assert k["average_planned_pct"] is not None
    assert k["average_planned_pct"] > 20
    assert k["behind_plan"] == 1


def test_cost_against_plan_shows_the_model_range(api: TestClient, world: World) -> None:
    cost = portfolio(api, world.pm.headers)["cost"]
    [point] = cost["projects"]
    assert point["code"] == "HR-1"
    assert Decimal(point["budget"]) == Decimal("2000000.00")
    # The risk model's likely final cost: the budget moved by its overrun range (1.5% to 9%).
    assert Decimal(point["model_final_range"]["low"]) == Decimal("2030000.00")
    assert Decimal(point["model_final_range"]["high"]) == Decimal("2180000.00")
    assert Decimal(cost["totals"]["budget"]) == Decimal("2000000.00")


def test_roles_without_cost_or_risk_get_neither(api: TestClient, world: World) -> None:
    for member in (world.se, world.buyer):
        result = portfolio(api, member.headers)
        assert result["cost"] is None
        assert result["risk"] is None
        assert result["kpis"]["high_risk"] is None
        assert "budget" not in str(result)
        assert "forecast_final" not in str(result)


def test_risk_ranking_carries_ranges(api: TestClient, world: World) -> None:
    [row] = portfolio(api, world.qs.headers)["risk"]
    assert row["score"] == 78
    assert row["ranges"]["score"] == {"low": 71, "high": 84}


def test_issue_trend_covers_eight_weeks(api: TestClient, world: World) -> None:
    trend = portfolio(api, world.pm.headers)["issue_trend"]
    assert len(trend) == 8
    assert trend[-1]["total"] == 2
    assert trend[-1]["by_category"]["safety"] == 1
    assert trend[-1]["by_category"]["material_delay"] == 1
    assert sum(w["total"] for w in trend[:-1]) == 0
    assert set(trend[0]["by_category"]) == {
        "material_delay", "labour", "weather", "equipment", "safety", "design", "quality", "other",
    }  # fmt: skip


def test_weather_comes_from_the_saved_forecast(api: TestClient, world: World) -> None:
    [site] = portfolio(api, world.pm.headers)["weather"]
    assert site["site_code"] == "COL-11"
    assert site["available"] is True
    assert site["stale"] is False
    assert len(site["days"]) == 5
    assert site["days"][1]["rain_mm"] == "14.0"
    assert site["heavy_rain_threshold_mm"] == "10.0"


def test_reports_filed_counts_only_today(api: TestClient, db: Session, world: World) -> None:
    db.query(DailyReport).filter(DailyReport.project_id == world.project.id).update(
        {DailyReport.report_date: world.today.replace(day=1) if world.today.day > 1 else world.today}
    )
    db.commit()
    expected = 1 if world.today.day == 1 else 0
    assert portfolio(api, world.pm.headers)["kpis"]["reports_filed_today"] == expected


# --- The approval queue -----------------------------------------------------------------------------------


def test_each_role_sees_what_waits_for_it(api: TestClient, db: Session, world: World) -> None:
    pm = portfolio(api, world.pm.headers)["approvals"]
    assert [(a["kind"], a["number"]) for a in pm] == [("material_request", "MR-9001")]
    assert pm[0]["link"] == f"/materials/{world.request.id}"
    assert pm[0]["title"] == "SECRET-BOQ-ITEM cement"

    qs = portfolio(api, world.qs.headers)["approvals"]
    assert [(a["kind"], a["number"]) for a in qs] == [("variation", "VO-9001")]  # to price

    assert portfolio(api, world.se.headers)["approvals"] == []
    assert portfolio(api, world.buyer.headers)["approvals"] == []

    world.request.status = "approved"
    db.commit()
    buyer = portfolio(api, world.buyer.headers)["approvals"]
    assert [(a["kind"], a["title"]) for a in buyer] == [
        ("purchase_order", "Ready to order: SECRET-BOQ-ITEM cement")
    ]


def test_nobody_approves_their_own_request(api: TestClient, db: Session, world: World) -> None:
    world.request.requested_by = world.pm.user.id
    db.commit()
    assert portfolio(api, world.pm.headers)["approvals"] == []


def test_the_approval_queue_carries_no_amounts(api: TestClient, world: World) -> None:
    for member in (world.pm, world.qs):
        for item in portfolio(api, member.headers)["approvals"]:
            assert "LKR" not in item["title"]
            assert set(item) == {
                "kind",
                "id",
                "number",
                "project_id",
                "project_code",
                "title",
                "status",
                "since",
                "link",
            }


# --- The weekly PDF ---------------------------------------------------------------------------------------


def test_the_weekly_pdf_for_cost_roles(api: TestClient, db: Session, world: World) -> None:
    response = api.get("/api/v1/reports/weekly.pdf", headers=world.pm.headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="sitesense-weekly-{world.today.isoformat()}.pdf"'
    )
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 2000
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "report.weekly_downloaded")).one()
    assert entry.actor_id == world.pm.user.id


def test_no_weekly_pdf_without_cost_access(api: TestClient, world: World) -> None:
    for member in (world.se, world.buyer):
        assert api.get("/api/v1/reports/weekly.pdf", headers=member.headers).status_code == 403


def test_weekly_pdf_is_not_mistaken_for_a_report_id(api: TestClient, world: World) -> None:
    # The dashboard router is mounted first; otherwise this path would be a 422 for a bad report ID.
    assert api.get("/api/v1/reports/weekly.pdf", headers=world.qs.headers).status_code == 200


def test_the_pdf_escapes_what_it_prints(db: Session, world: World) -> None:
    from app.services import weekly_report

    world.project.name = "Havelock <b>& </para> Residences"
    db.commit()
    assert weekly_report.build_for(db, world.pm.user).startswith(b"%PDF-")


# --- Email preferences ------------------------------------------------------------------------------------


def preferences(api: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = api.get("/api/v1/me/notification-preferences", headers=headers)
    assert response.status_code == 200
    result: dict[str, Any] = response.json()
    return result


def put(api: TestClient, headers: dict[str, str], **body: object) -> Any:
    return api.put("/api/v1/me/notification-preferences", json=body, headers=headers)


def test_default_preferences_follow_the_role(api: TestClient, world: World) -> None:
    pm = preferences(api, world.pm.headers)
    assert pm == {
        "email_urgent": True,
        "email_digest": True,
        "weekly_report": True,
        "weekly_report_available": True,
        "stop_work_always": True,
        "email_configured": False,
        "digest_time": "18:30",
        "weekly_time": "Monday 07:00",
    }
    qs = preferences(api, world.qs.headers)
    assert (qs["weekly_report"], qs["weekly_report_available"]) == (False, True)
    se = preferences(api, world.se.headers)
    assert (se["weekly_report"], se["weekly_report_available"]) == (False, False)


def test_saving_preferences_is_audited(api: TestClient, db: Session, world: World) -> None:
    response = put(api, world.qs.headers, email_urgent=False, email_digest=True, weekly_report=True)
    assert response.status_code == 200, response.text
    assert response.json()["weekly_report"] is True
    assert response.json()["email_urgent"] is False
    stored = db.get(NotificationPreference, world.qs.user.id)
    assert stored is not None
    assert (stored.email_urgent, stored.weekly_report) == (False, True)
    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "user.notification_preferences_changed")
    ).one()
    assert entry.details["after"] == {"email_urgent": False, "email_digest": True, "weekly": True}

    # Saving the same choices again changes nothing and records nothing.
    put(api, world.qs.headers, email_urgent=False, email_digest=True, weekly_report=True)
    assert (
        len(
            db.scalars(
                select(AuditLog).where(AuditLog.action == "user.notification_preferences_changed")
            ).all()
        )
        == 1
    )


def test_a_pm_can_opt_out_of_the_weekly_report(api: TestClient, world: World) -> None:
    put(api, world.pm.headers, email_urgent=True, email_digest=True, weekly_report=False)
    assert preferences(api, world.pm.headers)["weekly_report"] is False


def test_roles_without_cost_cannot_take_the_weekly_report(api: TestClient, world: World) -> None:
    response = put(api, world.se.headers, email_urgent=True, email_digest=True, weekly_report=True)
    assert response.status_code == 422
    assert "cost figures" in response.json()["error"]["message"]
    # Saying no is fine.
    assert (
        put(api, world.se.headers, email_urgent=True, email_digest=False, weekly_report=False).status_code
        == 200
    )


def test_preferences_reject_unknown_fields_and_loose_types(api: TestClient, world: World) -> None:
    assert (
        put(api, world.pm.headers, email_urgent=True, email_digest=True, stop_work=False).status_code == 422
    )
    assert put(api, world.pm.headers, email_urgent="no", email_digest=True).status_code == 422


def test_preferences_are_your_own(api: TestClient, db: Session, world: World) -> None:
    put(api, world.pm.headers, email_urgent=False, email_digest=False)
    assert db.get(NotificationPreference, world.qs.user.id) is None
    assert preferences(api, world.qs.headers)["email_urgent"] is True


def test_the_dashboard_never_returns_report_text_or_names(api: TestClient, world: World) -> None:
    # Site names, the approval queue's item and variation titles, and the risk ranking's top driver
    # are meant to be on the dashboard. Report text, comments, notes and people's names are not.
    private = [
        *PEOPLE.values(), "SECRET-WORKDONE", "SECRET-PROBLEMS", "SECRET-SNIPPET", "SECRET-ACTION",
        "SECRET-NOTES", "SECRET-COMMENT", "SECRET-VARIATION-DESC", "SECRET-NOTIFICATION", "SECRET-CLIENT",
    ]  # fmt: skip
    for member in (world.pm, world.qs, world.se, world.buyer):
        text = str(portfolio(api, member.headers))
        for secret in private:
            assert secret not in text, secret
