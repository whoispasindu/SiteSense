"""SiteSense load test (Phase 13): 50 people using the demo company at once.

    pip install -r loadtest/requirements.txt
    locust -f loadtest/locustfile.py --host https://localhost --headless -u 50 -r 5 -t 5m \
        --csv loadtest/results/run --only-summary

Against the production stack (docker-compose.prod.yml) in demo mode, seeded with ``seed-dev``. Every
simulated person signs in once with a demo account, then works like that role does: mostly reading,
some writes, and now and then one of the heavy endpoints. Request names start with the class the
targets are set for, so the results split cleanly:

    R  reads                 95% under 500 ms
    W  writes                95% under 1 s
    H  heavy (what-if, weekly PDF, report analysis), measured separately: 95% under 2 s
    and 0 errors overall

At the end the run writes ``<csv prefix>_classes.json`` with each class's count, errors and
percentiles (from every individual response time, not averages of averages).
"""

from __future__ import annotations

import json
import os
import random
import threading
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

import urllib3
from locust import HttpUser, between, events, task

# Caddy's local certificate is self-signed; the test only ever talks to your own machine.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PASSWORD = os.environ.get("SITESENSE_DEMO_PASSWORD", "SiteSense-Demo-2026!")
HAVELOCK = "HR-2026-01"
TARGETS_MS = {"R": 500, "W": 1000, "H": 2000}
# Sri Lanka time (UTC+5:30, no daylight saving): the API's "today" for daily reports.
SITE_TODAY = lambda: datetime.now(timezone(timedelta(hours=5, minutes=30))).date()  # noqa: E731
ACTIONS = ["add_crew", "work_sundays", "expedite_materials", "weather_protection"]

_times: dict[str, list[float]] = defaultdict(list)
_errors: dict[str, int] = defaultdict(int)
_lock = threading.Lock()


@events.request.add_listener
def _record(name: str, response_time: float, exception: BaseException | None, **_: Any) -> None:
    klass = name.split(" ", 1)[0]
    if klass not in TARGETS_MS:
        return  # sign-in and set-up requests are not part of the targets
    with _lock:
        _times[klass].append(response_time)
        if exception is not None:
            _errors[klass] += 1


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = max(0, min(len(ordered) - 1, -(-len(ordered) * pct // 100) - 1))
    return ordered[int(rank)]


@events.quitting.add_listener
def _summarise(environment: Any, **_: Any) -> None:
    summary: dict[str, Any] = {}
    for klass, limit in TARGETS_MS.items():
        values = _times.get(klass, [])
        p95 = _percentile(values, 95)
        summary[klass] = {
            "requests": len(values),
            "errors": _errors.get(klass, 0),
            "median_ms": round(_percentile(values, 50), 1),
            "p95_ms": round(p95, 1),
            "p99_ms": round(_percentile(values, 99), 1),
            "max_ms": round(max(values), 1) if values else 0.0,
            "target_p95_ms": limit,
            "met": bool(values) and p95 < limit and _errors.get(klass, 0) == 0,
        }
    total_failures = environment.stats.total.num_failures
    summary["all"] = {"requests": environment.stats.total.num_requests, "failures": total_failures}
    prefix = getattr(environment.parsed_options, "csv_prefix", None)
    if prefix:
        with open(f"{prefix}_classes.json", "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
    print(json.dumps(summary, indent=2))
    if total_failures or not all(summary[k]["met"] for k in TARGETS_MS):
        environment.process_exit_code = 1


class SiteSenseUser(HttpUser):
    abstract = True
    wait_time = between(1, 3)
    email = ""

    def on_start(self) -> None:
        self.client.verify = False
        origin = self.host or ""
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": PASSWORD},
            headers={"Origin": origin},
            name="sign in",
        )
        response.raise_for_status()
        body = response.json()
        if body.get("mfa_required"):
            raise RuntimeError("Run the load test in demo mode: the demo accounts skip two-step codes.")
        self.client.headers["Authorization"] = f"Bearer {body['access_token']}"
        self.client.headers["Origin"] = origin
        self.setup()

    def setup(self) -> None:
        """Look up the IDs this role works with."""

    def get(self, name: str, path: str) -> None:
        self.client.get(path, name=name)

    def havelock(self, path: str = "/api/v1/projects") -> str:
        projects = self.client.get(path, name="setup").json()
        items = projects["items"] if isinstance(projects, dict) else projects
        return str(next((p["id"] for p in items if p.get("code") == HAVELOCK), items[0]["id"]))

    def steel_item(self) -> str:
        items = self.client.get(f"/api/v1/projects/{self.project}/boq-items", name="setup").json()
        return str(next(i["id"] for i in items if i["item_code"] == "C.03"))


class ProjectManager(SiteSenseUser):
    fixed_count = 15
    email = "pm@sitesense.example"

    def setup(self) -> None:
        self.project = self.havelock()

    @task(4)
    def dashboard(self) -> None:
        self.get("R /risk/projects", "/api/v1/risk/projects")
        self.get("R /analytics/portfolio", "/api/v1/analytics/portfolio")
        self.get("R /briefing/today", "/api/v1/briefing/today")
        self.get("R /notifications", "/api/v1/notifications")

    @task(3)
    def project_page(self) -> None:
        p = self.project
        self.get("R /projects/{id}", f"/api/v1/projects/{p}")
        self.get("R /projects/{id}/risk", f"/api/v1/projects/{p}/risk")
        self.get("R /projects/{id}/network", f"/api/v1/projects/{p}/network")
        self.get("R /projects/{id}/progress", f"/api/v1/projects/{p}/progress")

    @task(2)
    def approvals(self) -> None:
        self.get("R /material-requests", "/api/v1/material-requests?limit=50")
        self.get("R /cost/overview", "/api/v1/cost/overview")
        self.get("R /projects/{id}/variations", f"/api/v1/projects/{self.project}/variations")

    @task(2)
    def small_writes(self) -> None:
        self.client.post("/api/v1/notifications/read-all", name="W /notifications/read-all")
        self.client.post(
            f"/api/v1/projects/{self.project}/handover/confirm", name="W /projects/{id}/handover/confirm"
        )

    @task(1)
    def what_if(self) -> None:
        self.client.post(
            f"/api/v1/projects/{self.project}/risk/what-if",
            json={"actions": [{"id": a} for a in random.sample(ACTIONS, 2)]},
            name="H /projects/{id}/risk/what-if",
        )

    @task(1)
    def weekly_pdf(self) -> None:
        self.get("H /reports/weekly.pdf", "/api/v1/reports/weekly.pdf")


class QuantitySurveyor(SiteSenseUser):
    fixed_count = 10
    email = "qs@sitesense.example"

    def setup(self) -> None:
        self.project = self.havelock()
        self.item = self.steel_item()

    @task(4)
    def costs(self) -> None:
        self.get("R /cost/overview", "/api/v1/cost/overview")
        self.get("R /projects/{id}/budget", f"/api/v1/projects/{self.project}/budget")
        self.get("R /projects/{id}/claims", f"/api/v1/projects/{self.project}/claims")

    @task(3)
    def boq(self) -> None:
        self.get("R /projects/{id}/boq", f"/api/v1/projects/{self.project}/boq")
        self.get("R /material-requests", "/api/v1/material-requests?limit=50")

    @task(2)
    def price_check(self) -> None:
        self.client.post(
            "/api/v1/material-requests/check",
            json={
                "project_id": self.project,
                "boq_item_id": self.item,
                "quantity": "500",
                "unit_price": "402",
            },
            name="W /material-requests/check",
        )
        self.client.put(
            "/api/v1/me/notification-preferences",
            json={"email_urgent": True, "email_digest": True, "weekly_report": True},
            name="W /me/notification-preferences",
        )

    @task(1)
    def weekly_pdf(self) -> None:
        self.get("H /reports/weekly.pdf", "/api/v1/reports/weekly.pdf")


class SiteEngineer(SiteSenseUser):
    fixed_count = 15
    email = "engineer@sitesense.example"

    def setup(self) -> None:
        self.project = self.havelock()
        self.item = self.steel_item()
        self.report = self.todays_report()

    def todays_report(self) -> str:
        """Report analysis only runs on a report its author filed today: the first engineer to arrive
        files Havelock's (the demo leaves it for you), the others find it already there (409)."""
        with self.client.post(
            f"/api/v1/projects/{self.project}/reports",
            json={
                "report_date": SITE_TODAY().isoformat(),
                "crew_count": 44,
                "work_done": "Formwork and rebar for the level 4 slab; blockwork on level 2.",
                "problems": "Cement delivery late again, the mixer stood idle until noon. Rain stopped the "
                "pour.",
            },
            name="setup",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                return str(response.json()["id"])
            if response.status_code == 409:
                response.success()
                return str(response.json()["error"]["details"][0]["report_id"])
            response.failure(f"could not file today's report: {response.status_code}")
            raise RuntimeError(response.text)

    @task(4)
    def site_day(self) -> None:
        self.get("R /reports/today", "/api/v1/reports/today")
        self.get("R /projects/{id}/tasks", f"/api/v1/projects/{self.project}/tasks")
        self.get("R /projects/{id}/weather", f"/api/v1/projects/{self.project}/weather")
        self.get("R /notifications", "/api/v1/notifications")

    @task(2)
    def reports(self) -> None:
        self.get("R /projects/{id}/reports", f"/api/v1/projects/{self.project}/reports?limit=20")
        self.get("R /reports/{id}", f"/api/v1/reports/{self.report}")
        self.get("R /reports/{id}/issues", f"/api/v1/reports/{self.report}/issues")

    @task(2)
    def request_material(self) -> None:
        needed = (date.today() + timedelta(days=14)).isoformat()
        self.client.post(
            "/api/v1/material-requests",
            json={"project_id": self.project, "boq_item_id": self.item, "quantity": "5", "needed_by": needed},
            name="W /material-requests",
        )

    @task(1)
    def analyse(self) -> None:
        self.client.post(f"/api/v1/reports/{self.report}/analyze", name="H /reports/{id}/analyze")


class ProcurementOfficer(SiteSenseUser):
    fixed_count = 5
    email = "procurement@sitesense.example"

    def setup(self) -> None:
        self.project = self.havelock()
        self.supplier = self.client.get("/api/v1/suppliers", name="setup").json()[0]

    @task(4)
    def orders(self) -> None:
        self.get("R /purchase-orders/ready", "/api/v1/purchase-orders/ready")
        self.get("R /purchase-orders", "/api/v1/purchase-orders?limit=50")
        self.get("R /suppliers", "/api/v1/suppliers")

    @task(2)
    def outlook(self) -> None:
        self.get("R /projects/{id}/supplier-outlook", f"/api/v1/projects/{self.project}/supplier-outlook")

    @task(1)
    def update_supplier(self) -> None:
        self.client.patch(
            f"/api/v1/suppliers/{self.supplier['id']}",
            json={"phone": self.supplier["phone"]},
            name="W /suppliers/{id}",
        )


class Client(SiteSenseUser):
    fixed_count = 5
    email = "client@sitesense.example"

    def setup(self) -> None:
        self.project = self.havelock("/api/v1/client/projects")

    @task(4)
    def portal(self) -> None:
        self.get("R /client/projects/{id}", f"/api/v1/client/projects/{self.project}")
        self.get("R /client/projects/{id}/claims", f"/api/v1/client/projects/{self.project}/claims")
        self.get("R /client/variations", "/api/v1/client/variations")

    @task(1)
    def mark_read(self) -> None:
        self.client.post("/api/v1/notifications/read-all", name="W /notifications/read-all")
