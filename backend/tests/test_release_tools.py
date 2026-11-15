"""The self-hosting tools (ADR 0019): scripts/setup.py and scripts/make_bundle.py.

They live outside the backend (they run on a server with no SiteSense code), so they are loaded from
the repository by path. The key check: what setup writes passes the API's own production checks.
"""

import importlib.util
import re
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

from app.core.config import Settings

REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"sitesense_{name}", REPO / "scripts" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


setup = _load("setup")
bundle = _load("make_bundle")


def answers(**overrides: object) -> object:
    values: dict[str, object] = {
        "domain": "sitesense.example.com",
        "admin_email": "admin@example.com",
        "admin_name": "Ada Admin",
        "country": "GB",
        "time_zone": "Europe/London",
        "currency": "GBP",
        "number_locale": "en-GB",
        "risk_lkr_per_unit": "400",
    }
    values.update(overrides)
    return setup.check_answers(setup.Answers(**values))


def settings_from(env: dict[str, str]) -> Settings:
    """The API's settings as docker-compose.prod.yml builds them from the env file."""
    domain = env["SITESENSE_DOMAIN"]
    return Settings.model_validate(
        {
            "environment": "production",
            "database_url": f"postgresql+psycopg://sitesense_app:{env['SITESENSE_APP_PASSWORD']}@db:5432/sitesense",
            "cors_origins": [f"https://{domain}"],
            "allowed_hosts": [domain, "backend"],
            "app_base_url": f"https://{domain}",
            "jwt_secret": env["SITESENSE_JWT_SECRET"],
            "mfa_key": env["SITESENSE_MFA_KEY"],
            "demo_mode": env["SITESENSE_DEMO_MODE"] == "true",
            "country": env["SITESENSE_COUNTRY"],
            "time_zone": env["SITESENSE_TIME_ZONE"],
            "currency": env["SITESENSE_CURRENCY"],
            "number_locale": env["SITESENSE_NUMBER_LOCALE"],
            "risk_lkr_per_unit": env["SITESENSE_RISK_LKR_PER_UNIT"] or None,
            "smtp_host": env["SITESENSE_SMTP_HOST"] or None,
            "smtp_security": env["SITESENSE_SMTP_SECURITY"],
        }
    )


# --- setup.py: answers ---------------------------------------------------------------------------


def test_a_server_gets_lets_encrypt_and_listens_on_every_interface() -> None:
    env = setup.build_env(answers())
    assert env["SITESENSE_TLS"] == "admin@example.com"
    assert env["SITESENSE_BIND"] == "0.0.0.0"  # noqa: S104


def test_localhost_keeps_caddys_own_certificate_and_this_machine_only() -> None:
    env = setup.build_env(answers(domain="localhost", country="LK", time_zone="Asia/Colombo", currency="LKR",
                                  number_locale="en-LK", risk_lkr_per_unit="200"))  # fmt: skip
    assert env["SITESENSE_TLS"] == "internal"
    assert env["SITESENSE_BIND"] == "127.0.0.1"
    assert env["SITESENSE_RISK_LKR_PER_UNIT"] == ""  # LKR needs no rate


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"domain": "not a domain"}, "not a domain"),
        ({"admin_email": "nobody"}, "not an email"),
        ({"admin_name": "A"}, "2 to 120"),
        ({"country": "GBR"}, "two-letter"),
        ({"currency": "pounds"}, "three-letter"),
        ({"time_zone": "London"}, "time zone"),
        ({"number_locale": "en_GB"}, "number format"),
        ({"risk_lkr_per_unit": ""}, "Sri Lankan rupees"),
        ({"risk_lkr_per_unit": "-3"}, "positive"),
    ],
)
def test_wrong_answers_are_explained(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(setup.SetupError, match=message):
        answers(**overrides)


def test_every_secret_is_long_random_and_different() -> None:
    first, second = setup.build_env(answers()), setup.build_env(answers())
    keys = ["POSTGRES_PASSWORD", "SITESENSE_OWNER_PASSWORD", "SITESENSE_APP_PASSWORD",
            "SITESENSE_JWT_SECRET", "SITESENSE_MFA_KEY"]  # fmt: skip
    values = [first[k] for k in keys]
    assert len(set(values)) == len(values)
    assert all(len(v) >= 40 and re.fullmatch(r"[A-Za-z0-9_-]+", v) for v in values)
    assert all(first[k] != second[k] for k in keys)
    assert first["SITESENSE_DEMO_MODE"] == "false"
    assert first["SITESENSE_DEMO_RESET_DATABASE_URL"] == ""  # no process holds the owner password


def test_what_setup_writes_passes_the_apis_production_checks() -> None:
    settings = settings_from(setup.build_env(answers()))
    assert settings.is_production
    assert settings.currency == "GBP"
    assert str(settings.lkr_per_unit) == "400"


# --- setup.py: the settings file -----------------------------------------------------------------


def test_the_settings_file_is_private_and_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / ".env.prod"
    env = setup.build_env(answers())
    setup.write_env(path, env)
    text = path.read_text(encoding="utf-8")
    assert f"SITESENSE_MFA_KEY='{env['SITESENSE_MFA_KEY']}'" in text
    assert "SITESENSE_EMAIL_FROM='SiteSense <no-reply@sitesense.example.com>'" in text
    if hasattr(path.stat(), "st_mode") and __import__("os").name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(setup.SetupError, match="never overwrites"):
        setup.write_env(path, setup.build_env(answers()))
    assert path.read_text(encoding="utf-8") == text


def test_main_refuses_before_asking_anything_when_settings_exist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "docker-compose.prod.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / ".env.prod").write_text("KEEP=me\n", encoding="utf-8")
    assert setup.main(["--dir", str(tmp_path), "--no-start"]) == 1
    assert "never overwrites" in capsys.readouterr().err
    assert (tmp_path / ".env.prod").read_text(encoding="utf-8") == "KEEP=me\n"


def test_non_interactive_writes_the_file(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.prod.yml").write_text("services: {}\n", encoding="utf-8")
    code = setup.main(["--dir", str(tmp_path), "--no-start", "--non-interactive", "--domain", "localhost",
                       "--admin-email", "you@example.com", "--admin-name", "You There"])  # fmt: skip
    assert code == 0
    text = (tmp_path / ".env.prod").read_text(encoding="utf-8")
    assert "SITESENSE_TIME_ZONE='Asia/Colombo'" in text
    assert "SITESENSE_CURRENCY='LKR'" in text
    assert "SITESENSE_VERSION='latest'" in text  # a checkout has no VERSION file


def test_non_interactive_needs_the_admin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "docker-compose.prod.yml").write_text("services: {}\n", encoding="utf-8")
    assert setup.main(["--dir", str(tmp_path), "--no-start", "--non-interactive"]) == 1
    assert "--admin-email, --admin-name" in capsys.readouterr().err
    assert not (tmp_path / ".env.prod").exists()


def test_compose_and_setup_agree_on_every_setting() -> None:
    compose = (REPO / "docker-compose.prod.yml").read_text(encoding="utf-8")
    read_by_compose = set(re.findall(r"\$\{([A-Z_]+)(?::[-?][^}]*)?\}", compose)) - {"WEB_CONCURRENCY"}
    written = set(setup.build_env(answers())) - {"WEB_CONCURRENCY"}
    # Read with sensible defaults, so setup leaves them out.
    tuning = {
        "SITESENSE_LOG_LEVEL",
        "SITESENSE_WEATHER_ENABLED",
        "SITESENSE_LOGIN_RATE_PER_MINUTE",
        "SITESENSE_WRITE_RATE_PER_MINUTE",
        "SITESENSE_HEAVY_RATE_PER_MINUTE",
        "SITESENSE_ANALYZE_RATE_PER_MINUTE",
    }
    assert read_by_compose - written == tuning
    assert written - read_by_compose == set()


def test_the_compose_commands(tmp_path: Path) -> None:
    pulled = setup.Compose(tmp_path, tmp_path / ".env.prod")
    assert pulled.up()[-3:] == ["up", "-d", "--wait"]
    assert "docker-compose.build.yml" not in " ".join(pulled.up())
    built = setup.Compose(tmp_path, tmp_path / ".env.prod", build=True, project="trial")
    command = built.up()
    assert command[:4] == ["docker", "compose", "-p", "trial"]
    assert str(tmp_path / "docker-compose.build.yml") in command
    assert command[-1] == "--build"
    assert built.create_admin("a@b.co", "A B")[-6:] == [
        "app.cli",
        "create-admin",
        "--email",
        "a@b.co",
        "--name",
        "A B",
    ]


# --- make_bundle.py ------------------------------------------------------------------------------


def test_the_bundle_runs_the_images_it_was_released_with(tmp_path: Path) -> None:
    archive = bundle.write("1.2.3", "ExampleOrg", tmp_path)
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        compose = tar.extractfile("sitesense-1.2.3/docker-compose.prod.yml").read().decode()  # type: ignore[union-attr]
        version = tar.extractfile("sitesense-1.2.3/VERSION").read().decode()  # type: ignore[union-attr]
        setup_mode = tar.getmember("sitesense-1.2.3/setup.py").mode
    assert {
        "sitesense-1.2.3/setup.py",
        "sitesense-1.2.3/backup.py",
        "sitesense-1.2.3/README.md",
        "sitesense-1.2.3/.env.prod.example",
        "sitesense-1.2.3/infra/caddy/Caddyfile",
        "sitesense-1.2.3/infra/postgres/init/01-roles.sh",
        "sitesense-1.2.3/LICENSE",
    } <= names
    assert "${SITESENSE_VERSION:-1.2.3}" in compose
    assert "${SITESENSE_IMAGE_PREFIX:-ghcr.io/exampleorg/sitesense}" in compose
    assert "latest" not in compose
    assert version == "1.2.3\n"
    assert setup_mode == 0o755
    digest = (tmp_path / "sitesense-1.2.3.tar.gz.sha256").read_text(encoding="utf-8")
    assert digest.endswith("  sitesense-1.2.3.tar.gz\n")


def test_the_bundle_refuses_a_bad_version(tmp_path: Path) -> None:
    assert bundle.main(["--version", "1.2", "--owner", "x", "--out", str(tmp_path)]) == 2
