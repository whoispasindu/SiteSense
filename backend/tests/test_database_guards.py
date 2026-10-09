"""Database-level protections that hold even if application code is wrong or compromised."""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, ProgrammingError


def _expect_denied(connection: Connection, sql: str) -> None:
    savepoint = connection.begin_nested()
    with pytest.raises(ProgrammingError, match=r"permission denied|must be owner"):
        connection.execute(text(sql))
    savepoint.rollback()


def test_app_role_cannot_rewrite_the_audit_log(db_connection: Connection) -> None:
    db_connection.execute(
        text("INSERT INTO audit_logs (id, action) VALUES (gen_random_uuid(), 'test.event')")
    )

    _expect_denied(db_connection, "UPDATE audit_logs SET action = 'tampered'")
    _expect_denied(db_connection, "DELETE FROM audit_logs")


def test_app_role_cannot_change_reference_roles(db_connection: Connection) -> None:
    assert db_connection.execute(text("SELECT count(*) FROM roles")).scalar_one() == 6
    _expect_denied(db_connection, "INSERT INTO roles VALUES ('root', 'Root', 'x')")
    _expect_denied(db_connection, "UPDATE roles SET name = 'x'")


def test_app_role_cannot_change_the_schema(db_connection: Connection) -> None:
    _expect_denied(db_connection, "CREATE TABLE sneaky (id int)")
    _expect_denied(db_connection, "DROP TABLE users")


def test_email_must_be_stored_lowercase(db_connection: Connection) -> None:
    savepoint = db_connection.begin_nested()
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO users (id, email, full_name, password_hash, role) "
                "VALUES (gen_random_uuid(), 'Mixed@Case.lk', 'X', 'h', 'client')"
            )
        )
    savepoint.rollback()
