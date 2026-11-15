"""Set up SiteSense on this machine in one step (docs/self-hosting.md, ADR 0019).

    python setup.py                      # asks a few questions
    python setup.py --non-interactive --domain sitesense.example.com --admin-email you@example.com \\
        --admin-name "Your Name" --country GB --time-zone Europe/London --currency GBP \\
        --risk-lkr-per-unit 400

1. Asks for the domain, the first admin, and the company's country, time zone and currency.
2. Writes the settings file (.env.prod) with a strong random value for every secret. It never
   overwrites an existing one: that file holds the keys to the data.
3. Pulls the release images and starts SiteSense (docker compose), and waits until it is healthy.
4. Creates the first Company Admin and prints their one-time password.

Needs Docker with Compose v2 and Python 3.9 or later; nothing else (no packages to install). Without
Python on the server, run it in a container (see docs/self-hosting.md).
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPOSE_FILE = "docker-compose.prod.yml"
BUILD_FILE = "docker-compose.build.yml"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})

# A starting point for the questions; any ISO code is accepted.
CURRENCIES = {
    "LK": "LKR", "GB": "GBP", "US": "USD", "IN": "INR", "AU": "AUD", "NZ": "NZD", "CA": "CAD",
    "AE": "AED", "QA": "QAR", "SA": "SAR", "OM": "OMR", "KW": "KWD", "BH": "BHD", "SG": "SGD",
    "MY": "MYR", "MV": "MVR", "BD": "BDT", "PK": "PKR", "NP": "NPR", "KE": "KES", "NG": "NGN",
    "ZA": "ZAR", "IE": "EUR", "DE": "EUR", "FR": "EUR", "NL": "EUR", "ES": "EUR", "IT": "EUR",
}  # fmt: skip
TIME_ZONES = {
    "LK": "Asia/Colombo", "GB": "Europe/London", "IN": "Asia/Kolkata", "AE": "Asia/Dubai",
    "QA": "Asia/Qatar", "SA": "Asia/Riyadh", "SG": "Asia/Singapore", "MY": "Asia/Kuala_Lumpur",
    "MV": "Indian/Maldives", "BD": "Asia/Dhaka", "PK": "Asia/Karachi", "NP": "Asia/Kathmandu",
    "NZ": "Pacific/Auckland", "IE": "Europe/Dublin", "KE": "Africa/Nairobi", "ZA": "Africa/Johannesburg",
}  # fmt: skip

HOSTNAME = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TIME_ZONE = re.compile(r"^[A-Za-z]+(?:/[A-Za-z0-9_+\-]+)+$|^UTC$")
LOCALE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


class SetupError(Exception):
    """A wrong answer or a step that failed; the message says what to do."""


@dataclass
class Answers:
    domain: str
    admin_email: str
    admin_name: str
    country: str
    time_zone: str
    currency: str
    number_locale: str
    risk_lkr_per_unit: str = ""
    tls_email: str = ""
    version: str = "latest"
    image_prefix: str = "ghcr.io/whoispasindu/sitesense"
    smtp: dict[str, str] = field(default_factory=dict)
    anthropic_api_key: str = ""

    @property
    def local(self) -> bool:
        return self.domain in LOCAL_HOSTS


# --- Checking answers ----------------------------------------------------------------------------


def check_domain(value: str) -> str:
    value = value.strip().lower()
    if value in LOCAL_HOSTS or HOSTNAME.match(value):
        return value
    raise SetupError(f"{value!r} is not a domain name (for example sitesense.example.com, or localhost).")


def check_email(value: str) -> str:
    value = value.strip()
    if EMAIL.match(value):
        return value
    raise SetupError(f"{value!r} is not an email address.")


def check_name(value: str) -> str:
    value = " ".join(value.split())
    if 2 <= len(value) <= 120:
        return value
    raise SetupError("The admin's name needs 2 to 120 characters.")


def check_country(value: str) -> str:
    value = value.strip().upper()
    if re.fullmatch(r"[A-Z]{2}", value):
        return value
    raise SetupError(f"{value!r} is not a two-letter country code (for example LK, GB, AE).")


def check_currency(value: str) -> str:
    value = value.strip().upper()
    if re.fullmatch(r"[A-Z]{3}", value):
        return value
    raise SetupError(f"{value!r} is not a three-letter currency code (for example LKR, GBP, AED).")


def check_time_zone(value: str) -> str:
    value = value.strip()
    if not TIME_ZONE.match(value):
        raise SetupError(f"{value!r} is not a time zone name (for example Asia/Colombo, Europe/London).")
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        ZoneInfo(value)
    except ImportError:  # Python 3.8: the API checks it at start
        return value
    except (ZoneInfoNotFoundError, ValueError):
        if Path("/usr/share/zoneinfo").is_dir():  # with no time zone data here, the API checks it
            raise SetupError(
                f"Unknown time zone {value!r} (for example Asia/Colombo, Europe/London)."
            ) from None
    return value


def check_locale(value: str) -> str:
    value = value.strip()
    if LOCALE.match(value):
        return value
    raise SetupError(f"{value!r} is not a number format such as en-GB or de-DE.")


def check_rate(value: str) -> str:
    try:
        rate = float(value)
    except ValueError:
        raise SetupError(f"{value!r} is not a number.") from None
    if not 0 < rate <= 1_000_000:
        raise SetupError("The rate must be a positive number (Sri Lankan rupees per unit of your currency).")
    return value.strip()


def check_answers(a: Answers) -> Answers:
    a.domain = check_domain(a.domain)
    a.admin_email = check_email(a.admin_email)
    a.admin_name = check_name(a.admin_name)
    a.country = check_country(a.country)
    a.time_zone = check_time_zone(a.time_zone)
    a.currency = check_currency(a.currency)
    a.number_locale = check_locale(a.number_locale)
    if a.currency == "LKR":
        a.risk_lkr_per_unit = ""
    elif not a.risk_lkr_per_unit:
        raise SetupError(
            f"How many Sri Lankan rupees is one {a.currency} worth? The risk model was trained on contract "
            "values in LKR, so it needs the rate (--risk-lkr-per-unit)."
        )
    else:
        a.risk_lkr_per_unit = check_rate(a.risk_lkr_per_unit)
    if not a.local:
        a.tls_email = check_email(a.tls_email or a.admin_email)
    return a


# --- The settings file ---------------------------------------------------------------------------


def secret(length: int = 48) -> str:
    """URL-safe random text: safe inside the database URLs the compose file builds."""
    return secrets.token_urlsafe(length)


def build_env(a: Answers) -> dict[str, str]:
    """Every setting docker-compose.prod.yml reads, for a real company (never demo mode)."""
    smtp = a.smtp
    return {
        "SITESENSE_DOMAIN": a.domain,
        "SITESENSE_TLS": "internal" if a.local else a.tls_email,
        "SITESENSE_BIND": "127.0.0.1" if a.local else "0.0.0.0",  # noqa: S104 - a server must be reachable
        "SITESENSE_VERSION": a.version,
        "SITESENSE_IMAGE_PREFIX": a.image_prefix,
        "POSTGRES_PASSWORD": secret(32),
        "SITESENSE_OWNER_PASSWORD": secret(32),
        "SITESENSE_APP_PASSWORD": secret(32),
        "SITESENSE_JWT_SECRET": secret(),
        "SITESENSE_MFA_KEY": secret(),
        "SITESENSE_COUNTRY": a.country,
        "SITESENSE_TIME_ZONE": a.time_zone,
        "SITESENSE_CURRENCY": a.currency,
        "SITESENSE_NUMBER_LOCALE": a.number_locale,
        "SITESENSE_RISK_LKR_PER_UNIT": a.risk_lkr_per_unit,
        "SITESENSE_DEMO_MODE": "false",
        "SITESENSE_DEMO_PASSWORD": "",
        "SITESENSE_DEMO_RESET_DATABASE_URL": "",
        "WEB_CONCURRENCY": "4",
        "SITESENSE_ANTHROPIC_API_KEY": a.anthropic_api_key,
        "SITESENSE_SMTP_HOST": smtp.get("host", ""),
        "SITESENSE_SMTP_PORT": smtp.get("port", "587"),
        "SITESENSE_SMTP_SECURITY": smtp.get("security", "starttls"),
        "SITESENSE_SMTP_USERNAME": smtp.get("username", ""),
        "SITESENSE_SMTP_PASSWORD": smtp.get("password", ""),
        "SITESENSE_EMAIL_FROM": smtp.get("from", f"SiteSense <no-reply@{a.domain}>"),
    }


def render_env(values: dict[str, str]) -> str:
    lines = [
        "# SiteSense settings, written by setup.py. Keep this file safe and back it up with the data:",
        "# SITESENSE_MFA_KEY decrypts every two-step enrolment, and the passwords open the database.",
        "# The comments in .env.prod.example explain each setting.",
        "",
    ]
    for key, value in values.items():
        if "\n" in value or "\r" in value:
            raise SetupError(f"{key} cannot contain a line break.")
        # Compose reads the value literally inside single quotes (no $ interpolation).
        lines.append(f"{key}='{value}'" if value and "'" not in value else f"{key}={value}")
    return "\n".join(lines) + "\n"


def write_env(path: Path, values: dict[str, str]) -> None:
    if path.exists():
        raise SetupError(
            f"{path} already exists. It holds this installation's secrets, so setup never overwrites it. "
            "To start again, move it away (and remove the old data volumes); to upgrade, see "
            "docs/self-hosting.md."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)  # readable by its owner only
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_env(values))


# --- Docker --------------------------------------------------------------------------------------


@dataclass
class Compose:
    directory: Path
    env_file: Path
    build: bool = False
    project: str | None = None

    def base(self) -> list[str]:
        command = ["docker", "compose"]
        if self.project:
            command += ["-p", self.project]
        command += ["-f", str(self.directory / COMPOSE_FILE)]
        if self.build:
            command += ["-f", str(self.directory / BUILD_FILE)]
        return [*command, "--env-file", str(self.env_file)]

    def pull(self) -> list[str]:
        return [*self.base(), "pull", "--quiet"]

    def up(self) -> list[str]:
        return [*self.base(), "up", "-d", "--wait", *(["--build"] if self.build else [])]

    def create_admin(self, email: str, name: str) -> list[str]:
        return [*self.base(), "run", "--rm", "-T", "backend", "python", "-m", "app.cli", "create-admin",
                "--email", email, "--name", name]  # fmt: skip


def find_directory(explicit: Path | None) -> Path:
    """The folder with docker-compose.prod.yml: the bundle's own, or the repository root."""
    for candidate in [explicit] if explicit else [HERE, HERE.parent]:
        if candidate is not None and (candidate / COMPOSE_FILE).is_file():
            return candidate.resolve()
    raise SetupError(f"Cannot find {COMPOSE_FILE}. Run setup from the release bundle, or pass --dir.")


def check_docker() -> None:
    if shutil.which("docker") is None:
        raise SetupError("Docker is not installed (https://docs.docker.com/engine/install/).")
    result = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, check=False)  # noqa: S607
    if result.returncode != 0:
        raise SetupError("Docker Compose v2 is needed (`docker compose version` failed).")


def run(command: list[str], *, capture: bool = False) -> str:
    print(f"\n$ {' '.join(command)}", flush=True)
    result = subprocess.run(command, capture_output=capture, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-2000:] if capture else ""
        raise SetupError(f"That step failed (exit {result.returncode}). {detail}".strip())
    return result.stdout if capture else ""


def start(compose: Compose, answers: Answers) -> str:
    if not compose.build:
        run(compose.pull())
    run(compose.up())  # --wait: until every service is running and healthy
    return run(compose.create_admin(answers.admin_email, answers.admin_name), capture=True)


# --- Questions -----------------------------------------------------------------------------------


def ask(question: str, default: str = "", *, check=None, secret_input: bool = False, optional: bool = False):  # type: ignore[no-untyped-def]
    while True:
        prompt = f"{question}" + (f" [{default}]" if default else "") + ": "
        raw = (getpass.getpass(prompt) if secret_input else input(prompt)).strip() or default
        if not raw:
            if optional:
                return ""
            print("  An answer is needed.")
            continue
        try:
            return check(raw) if check else raw
        except SetupError as exc:
            print(f"  {exc}")


def yes(question: str, default: bool = False) -> bool:
    raw = input(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not raw else raw in ("y", "yes")


def interview(args: argparse.Namespace) -> Answers:
    print("SiteSense setup. Press Enter to keep the suggestion in [brackets].\n")
    domain = ask(
        "Domain (localhost to try it on this machine)", args.domain or "localhost", check=check_domain
    )
    email = ask("First Company Admin's email", args.admin_email or "", check=check_email)
    name = ask("Their full name", args.admin_name or "", check=check_name)
    tls = ""
    if domain not in LOCAL_HOSTS:
        tls = ask("Email for the Let's Encrypt certificate", args.tls_email or email, check=check_email)
    country = ask("Country (two letters)", args.country or "LK", check=check_country)
    zone = ask("Time zone", args.time_zone or TIME_ZONES.get(country, ""), check=check_time_zone)
    currency = ask(
        "Currency (three letters)", args.currency or CURRENCIES.get(country, ""), check=check_currency
    )
    locale = ask("Number format", args.number_locale or f"en-{country}", check=check_locale)
    rate = ""
    if currency != "LKR":
        print("  The risk model was trained on contract values in Sri Lankan rupees (LKR).")
        rate = ask(f"How many LKR is one {currency} worth", args.risk_lkr_per_unit or "", check=check_rate)
    smtp: dict[str, str] = {}
    if yes("Send alert emails through your mail server now? (you can add it later)"):
        smtp["host"] = ask("SMTP host", check=check_domain)
        smtp["port"] = ask("SMTP port", "587")
        smtp["security"] = ask("starttls or ssl", "starttls", check=_security)
        smtp["username"] = ask("SMTP username", optional=True)
        smtp["password"] = ask("SMTP password", secret_input=True, optional=True)
        smtp["from"] = ask("Send as", f"SiteSense <no-reply@{domain}>")
    key = ask("Claude API key for the AI briefing (Enter to skip)", secret_input=True, optional=True)
    return Answers(
        domain,
        email,
        name,
        country,
        zone,
        currency,
        locale,
        rate,
        tls,
        args.version,
        args.image_prefix,
        smtp,
        key,
    )


def _security(value: str) -> str:
    if value in ("starttls", "ssl"):
        return value
    raise SetupError(f"{value!r}: choose starttls or ssl.")


def from_flags(args: argparse.Namespace) -> Answers:
    missing = [f"--{n.replace('_', '-')}" for n in ("admin_email", "admin_name") if not getattr(args, n)]
    if missing:
        raise SetupError(f"--non-interactive needs {', '.join(missing)}.")
    country = check_country(args.country or "LK")
    return Answers(
        domain=args.domain or "localhost",
        admin_email=args.admin_email,
        admin_name=args.admin_name,
        country=country,
        time_zone=args.time_zone or TIME_ZONES.get(country, ""),
        currency=args.currency or CURRENCIES.get(country, ""),
        number_locale=args.number_locale or f"en-{country}",
        risk_lkr_per_unit=args.risk_lkr_per_unit or "",
        tls_email=args.tls_email or "",
        version=args.version,
        image_prefix=args.image_prefix,
        anthropic_api_key=os.environ.get("SITESENSE_ANTHROPIC_API_KEY", ""),
    )


# --- Main ----------------------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set up SiteSense on this machine (docs/self-hosting.md).")
    parser.add_argument("--non-interactive", action="store_true", help="take every answer from the flags")
    parser.add_argument("--domain")
    parser.add_argument("--admin-email")
    parser.add_argument("--admin-name")
    parser.add_argument("--tls-email", help="for the Let's Encrypt certificate (default: the admin's email)")
    parser.add_argument("--country", help="two-letter code, default LK")
    parser.add_argument("--time-zone")
    parser.add_argument("--currency")
    parser.add_argument("--number-locale")
    parser.add_argument("--risk-lkr-per-unit", help="LKR per unit of the currency (required unless LKR)")
    parser.add_argument("--version", default=_bundled_version(), help="release to run (default: %(default)s)")
    parser.add_argument("--image-prefix", default="ghcr.io/whoispasindu/sitesense")
    parser.add_argument("--dir", type=Path, help="the folder with docker-compose.prod.yml")
    parser.add_argument("--env-file", type=Path, help="settings file to write (default: .env.prod there)")
    parser.add_argument("--project", help="docker compose project name (default: sitesense-prod)")
    parser.add_argument("--build", action="store_true", help="build the images from this checkout instead")
    parser.add_argument("--no-start", action="store_true", help="only write the settings file")
    return parser.parse_args(argv)


def _bundled_version() -> str:
    """The release bundle records its version next to this script; a checkout has none."""
    marker = HERE / "VERSION"
    return marker.read_text(encoding="utf-8").strip() if marker.is_file() else "latest"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        directory = find_directory(args.dir)
        env_file = (args.env_file or directory / ".env.prod").resolve()
        if env_file.exists():
            write_env(env_file, {})  # raises the explanation
        if not args.no_start:
            check_docker()
        answers = check_answers(from_flags(args) if args.non_interactive else interview(args))
        write_env(env_file, build_env(answers))
        print(f"\nWrote {env_file} (readable by you only). Back it up somewhere safe.")
        if args.no_start:
            return 0
        compose = Compose(directory, env_file, build=args.build, project=args.project)
        output = start(compose, answers)
    except SetupError as exc:
        print(f"\nSetup stopped: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nSetup cancelled.", file=sys.stderr)
        return 130
    url = "https://localhost" if answers.local else f"https://{answers.domain}"
    print(output.strip())
    print(
        f"\nSiteSense is running at {url}"
        + (" (accept the local certificate once)." if answers.local else ".")
        + "\nSign in with the email and one-time password above: you will choose a new password and set"
        "\nup two-step sign-in. Then add your sites, users and holidays (Admin)."
        "\n\nNext: back up the database and photos regularly (docs/self-hosting.md)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
