"""Which code may call out of the server (issue #23).

Report text can name workers, and redaction cannot catch every name. So the server makes outbound
calls from as few places as possible, and none of them may carry report text that has not been
through ``app.ai.nlp.text.redact``. This test lists every module that imports a network client; a
new one fails it until someone has checked what it sends and added it here.
"""

import ast
from pathlib import Path

APP = Path(__file__).parents[1] / "app"
NETWORK_CLIENTS = {"httpx", "requests", "urllib3", "aiohttp", "socket", "smtplib", "ftplib", "http.client"}

# Module -> what it sends. Report text: never, unless redacted first and tested.
ALLOWED = {
    "integrations/weather.py": "a site's stored coordinates to Open-Meteo; no report text",
}


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _uses_network(imports: set[str]) -> bool:
    return any(
        name == client or name.startswith(f"{client}.") or name == "urllib.request"
        for name in imports
        for client in NETWORK_CLIENTS
    )


def test_only_reviewed_modules_call_out_of_the_server() -> None:
    calling_out = {
        path.relative_to(APP).as_posix() for path in APP.rglob("*.py") if _uses_network(_imports(path))
    }

    assert calling_out == set(ALLOWED), (
        "A module now imports a network client. If it can send report text, pass the text through "
        "app.ai.nlp.text.redact first and test that, then list the module in ALLOWED."
    )


def test_the_check_recognises_network_clients() -> None:
    assert _uses_network({"httpx"})
    assert _uses_network({"urllib.request"})
    assert _uses_network({"http.client.HTTPSConnection"})
    assert not _uses_network({"json", "app.services.issue_service"})
