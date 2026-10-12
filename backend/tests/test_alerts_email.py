"""Phase 11: alerts by email. Urgent ones at once, the rest in an evening digest, the weekly PDF on Monday.

Sending is mocked: no test talks to a mail server. Emails carry a notification's title, a fixed
sentence and links, never its body (which can hold a comment, a name, an amount or report text).
"""

import smtplib
import uuid
from collections.abc import Callable
from datetime import timedelta
from email.message import EmailMessage
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.permissions import Role
from app.integrations import email as email_client
from app.models import EmailOutbox, Notification, NotificationPreference, User
from app.services import alerts, channels, notification_service, weekly_report
from app.services.notification_service import NewNotification
from tests.conftest import make_settings
from tests.dashboard_fixtures import World

SECRET_BODY = "Kamal Perera's comment: LKR 9,876,543 over, SECRET-BODY"


def notify(db: Session, user: User, kind: str, title: str = "HR-1 is now high risk (78)") -> None:
    notification_service.send(
        db,
        [NewNotification(user_id=user.id, kind=kind, title=title, body=SECRET_BODY, link="/projects/x",
                         dedupe_key=f"{kind}:{uuid.uuid4()}")],
    )  # fmt: skip
    db.commit()


def outbox(db: Session, user: User | None = None) -> list[EmailOutbox]:
    stmt = select(EmailOutbox).order_by(EmailOutbox.created_at)
    if user is not None:
        stmt = stmt.where(EmailOutbox.user_id == user.id)
    return list(db.scalars(stmt))


def set_prefs(db: Session, user: User, **values: Any) -> None:
    prefs = db.get(NotificationPreference, user.id) or NotificationPreference(
        user_id=user.id, email_urgent=True, email_digest=True, weekly_report=None, updated_at=clock.utcnow()
    )
    for key, value in values.items():
        setattr(prefs, key, value)
    db.add(prefs)
    db.commit()


@pytest.fixture
def pm(make_user: Callable[..., User]) -> User:
    return make_user(Role.PROJECT_MANAGER)


# --- Urgent alerts ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(alerts.URGENT_KINDS))
def test_urgent_kinds_are_emailed_at_once(db: Session, pm: User, kind: str) -> None:
    notify(db, pm, kind)
    [mail] = outbox(db, pm)
    assert mail.kind == "urgent"
    assert mail.subject == "SiteSense: HR-1 is now high risk (78)"
    assert mail.body.startswith("HR-1 is now high risk (78)\n\n" + alerts.SENTENCES[kind])
    assert "Open it in SiteSense: http://localhost:5173/projects/x" in mail.body
    assert "http://localhost:5173/settings/notifications" in mail.body


@pytest.mark.parametrize(
    "kind", ["report_submitted", "request_approved", "variation_approved", "cost_variance"]
)
def test_other_kinds_wait_for_the_digest(db: Session, pm: User, kind: str) -> None:
    notify(db, pm, kind)
    assert outbox(db, pm) == []


def test_an_email_never_carries_the_notification_body(db: Session, pm: User) -> None:
    for kind in sorted(alerts.URGENT_KINDS):
        notify(db, pm, kind)
    alerts.queue_digests(db, clock.utcnow())  # urgent kinds only: no digest
    notify(db, pm, "report_submitted", "Daily report: Havelock")
    alerts.queue_digests(db, clock.utcnow() + timedelta(minutes=1))
    mails = outbox(db, pm)
    assert len(mails) == len(alerts.URGENT_KINDS) + 1
    for mail in mails:
        for fragment in ("Kamal", "Perera", "9,876,543", "SECRET-BODY", "LKR"):
            assert fragment not in mail.body
            assert fragment not in mail.subject


def test_urgent_email_can_be_turned_off_but_not_for_stop_work(db: Session, pm: User) -> None:
    set_prefs(db, pm, email_urgent=False)
    notify(db, pm, "risk_high")
    notify(db, pm, "pour_rain")
    assert outbox(db, pm) == []
    notify(db, pm, "stop_work", "Stop-work flagged on HR-1")
    [mail] = outbox(db, pm)
    assert mail.subject == "SiteSense: Stop-work flagged on HR-1"


def test_inactive_users_get_no_email(db: Session, make_user: Callable[..., User]) -> None:
    gone = make_user(Role.PROJECT_MANAGER, active=False)
    assert alerts.queue_urgent(db, gone.id, "stop_work", "Stop-work flagged on HR-1", "/x") is False
    assert alerts.queue_urgent(db, uuid.uuid4(), "stop_work", "Stop-work flagged on HR-1", "/x") is False


def test_a_duplicate_notification_sends_no_second_email(db: Session, pm: User) -> None:
    item = NewNotification(user_id=pm.id, kind="risk_high", title="HR-1 is now high risk (78)", body="b",
                           dedupe_key="risk-high:once")  # fmt: skip
    notification_service.send(db, [item])
    notification_service.send(db, [item])
    db.commit()
    assert len(outbox(db, pm)) == 1


def test_urgent_email_without_a_link_points_at_the_app(db: Session, pm: User) -> None:
    subject, body = alerts.urgent_email("X", "unknown_kind", None)
    assert subject == "SiteSense: X"
    assert alerts.GENERIC_SENTENCE in body
    assert "Open it in SiteSense: http://localhost:5173/\n" in body


# --- The evening digest ----------------------------------------------------------------------------------


def test_the_digest_lists_titles_since_the_last_one(db: Session, pm: User) -> None:
    notify(db, pm, "report_submitted", "Daily report: Havelock")
    notify(db, pm, "request_approved", "MR-0001 approved")
    notify(db, pm, "risk_high")  # urgent: already emailed, not repeated
    assert alerts.queue_digests(db, clock.utcnow() + timedelta(minutes=1)) == 1
    [_, digest] = outbox(db, pm)
    assert digest.kind == "digest"
    assert digest.subject == "SiteSense: your daily updates"
    assert "(2):" in digest.body
    assert "- MR-0001 approved\n- Daily report: Havelock" in digest.body
    assert "high risk" not in digest.body


def test_no_digest_when_nothing_is_new(db: Session, pm: User) -> None:
    assert alerts.queue_digests(db, clock.utcnow()) == 0
    notify(db, pm, "report_submitted", "Daily report: Havelock")
    later = clock.utcnow() + timedelta(minutes=1)
    assert alerts.queue_digests(db, later) == 1
    assert alerts.queue_digests(db, later + timedelta(hours=24)) == 0  # nothing since the last digest
    assert [m.kind for m in outbox(db, pm)] == ["digest"]


def test_the_first_digest_covers_one_day_only(db: Session, pm: User) -> None:
    db.add(
        Notification(user_id=pm.id, kind="report_submitted", title="Old news", body="b",
                     created_at=clock.utcnow() - timedelta(days=3))
    )  # fmt: skip
    db.commit()
    assert alerts.queue_digests(db, clock.utcnow()) == 0


def test_the_digest_can_be_turned_off(db: Session, pm: User) -> None:
    set_prefs(db, pm, email_digest=False)
    notify(db, pm, "report_submitted", "Daily report: Havelock")
    assert alerts.queue_digests(db, clock.utcnow() + timedelta(minutes=1)) == 0


def test_a_long_digest_is_cut_short(db: Session, pm: User) -> None:
    for i in range(alerts.DIGEST_LIMIT + 3):
        notify(db, pm, "request_approved", f"MR-{i:04d} approved")
    alerts.queue_digests(db, clock.utcnow() + timedelta(minutes=1))
    [digest] = outbox(db, pm)
    assert f"({alerts.DIGEST_LIMIT}+):" in digest.body
    assert "(and more in the app)" in digest.body
    assert digest.body.count("\n- ") == alerts.DIGEST_LIMIT


# --- Sending ---------------------------------------------------------------------------------------------


class FakeSMTP:
    """Stands in for smtplib.SMTP and SMTP_SSL."""

    instances: ClassVar[list["FakeSMTP"]] = []
    fail: ClassVar[bool] = False

    def __init__(self, host: str, port: int, timeout: float, context: object = None) -> None:
        self.host, self.port, self.timeout, self.ssl = host, port, timeout, context is not None
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: object) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}:{password}")

    def send_message(self, message: EmailMessage) -> None:
        if FakeSMTP.fail:
            raise OSError("connection reset")
        self.sent.append(message)


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    FakeSMTP.fail = False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


SMTP_SETTINGS = {"smtp_host": "mail.test", "smtp_username": "sitesense", "smtp_password": SecretStr("pw")}


def test_without_smtp_settings_emails_are_logged_not_sent(
    db: Session, pm: User, smtp: type[FakeSMTP], monkeypatch: pytest.MonkeyPatch
) -> None:
    logged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(channels.log, "info", lambda event, **kw: logged.append((event, kw)))
    notify(db, pm, "risk_high")
    assert channels.send_pending(db, make_settings()) == (1, 0)
    assert smtp.instances == []
    [mail] = outbox(db, pm)
    assert mail.sent_at is not None
    [(event, fields)] = logged
    assert event == "email_logged_not_sent"
    assert fields["subject"] == "SiteSense: HR-1 is now high risk (78)"
    assert "SECRET-BODY" not in fields["body"]


def test_starttls_delivery(db: Session, pm: User, smtp: type[FakeSMTP]) -> None:
    notify(db, pm, "stop_work", "Stop-work flagged on HR-1")
    assert channels.send_pending(db, make_settings(**SMTP_SETTINGS)) == (1, 0)
    [server] = smtp.instances
    assert (server.host, server.port, server.ssl) == ("mail.test", 587, False)
    assert server.calls == ["starttls", "login:sitesense:pw", "quit"]
    [message] = server.sent
    assert message["To"] == pm.email
    assert message["Subject"] == "SiteSense: Stop-work flagged on HR-1"
    assert message["From"] == "SiteSense <no-reply@sitesense.example>"
    assert outbox(db, pm)[0].attempts == 1


def test_implicit_tls_delivery(db: Session, pm: User, smtp: type[FakeSMTP]) -> None:
    notify(db, pm, "risk_high")
    channels.send_pending(db, make_settings(**SMTP_SETTINGS, smtp_security="ssl", smtp_port=465))
    [server] = smtp.instances
    assert server.ssl
    assert server.calls == ["login:sitesense:pw", "quit"]


def test_a_failure_is_recorded_and_retried_up_to_five_times(
    db: Session, pm: User, smtp: type[FakeSMTP]
) -> None:
    notify(db, pm, "risk_high")
    smtp.fail = True
    settings = make_settings(**SMTP_SETTINGS)
    for attempt in range(1, channels.MAX_ATTEMPTS + 1):
        assert channels.send_pending(db, settings) == (0, 1)
        [mail] = outbox(db, pm)
        assert (mail.attempts, mail.last_error, mail.sent_at) == (attempt, "OSError", None)
    assert channels.send_pending(db, settings) == (0, 0)  # given up
    smtp.fail = False
    assert channels.send_pending(db, settings) == (0, 0)


def test_emails_to_a_deactivated_user_are_dropped(db: Session, pm: User, smtp: type[FakeSMTP]) -> None:
    notify(db, pm, "risk_high")
    pm.is_active = False
    db.commit()
    assert channels.send_pending(db, make_settings(**SMTP_SETTINGS)) == (0, 0)
    [mail] = outbox(db, pm)
    assert (mail.attempts, mail.last_error) == (channels.MAX_ATTEMPTS, "recipient inactive")
    assert smtp.instances == []


def test_message_headers_cannot_be_injected() -> None:
    message = email_client.build(
        make_settings(**SMTP_SETTINGS),
        email_client.OutboundEmail(to="pm@x.example", subject="Hi\r\nBcc: evil@x.example", body="b"),
    )
    assert message["Bcc"] is None
    assert "\n" not in str(message["Subject"])


def test_unconfigured_send_refuses() -> None:
    with pytest.raises(RuntimeError):
        email_client.send(
            make_settings(), email_client.OutboundEmail(to="a@b.example", subject="s", body="b")
        )


# --- The weekly PDF by email -----------------------------------------------------------------------------


def test_the_monday_email_goes_to_pms_and_opted_in_qss(
    db: Session, world: World, smtp: type[FakeSMTP]
) -> None:
    assert weekly_report.queue_weekly(db) == 1  # the PM by default; the QS has not opted in
    set_prefs(db, world.qs.user, weekly_report=True)
    set_prefs(db, world.se.user, weekly_report=True)  # cannot be stored through the API; ignored anyway
    assert weekly_report.queue_weekly(db) == 1  # the QS now; the PM's copy is not repeated this week
    mails = [m for m in outbox(db) if m.kind == "weekly_report"]
    assert {m.user_id for m in mails} == {world.pm.user.id, world.qs.user.id}
    mail = mails[0]
    assert mail.attachment is not None
    assert mail.attachment.startswith(b"%PDF-")
    assert mail.attachment_name == f"sitesense-weekly-{clock.site_today().isoformat()}.pdf"
    assert "attached as a PDF" in mail.body

    channels.send_pending(db, make_settings(**SMTP_SETTINGS))
    sent = [m for server in smtp.instances for m in server.sent]
    attachments = [part for m in sent for part in m.iter_attachments()]
    assert [a.get_content_type() for a in attachments] == ["application/pdf", "application/pdf"]


def test_a_pm_who_opted_out_gets_no_weekly_email(db: Session, world: World) -> None:
    set_prefs(db, world.pm.user, weekly_report=False)
    assert weekly_report.queue_weekly(db) == 0


def test_only_cost_roles_can_receive_the_pdf(world: World) -> None:
    assert weekly_report.can_receive(world.pm.user)
    assert weekly_report.can_receive(world.qs.user)
    assert not weekly_report.can_receive(world.se.user)
    assert not weekly_report.can_receive(world.buyer.user)
    prefs = NotificationPreference(user_id=world.se.user.id, weekly_report=True)
    assert alerts.wants_weekly_report(world.se.user, prefs) is False
