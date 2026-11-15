"""Fetch the model files that are too large for the repository, and verify them.

    python scripts/fetch_models.py             # download from the GitHub Release
    python scripts/fetch_models.py --via https # plain HTTPS, no GitHub CLI or account (public repo)
    python scripts/fetch_models.py --via gh    # the GitHub CLI, signed in (while the repo is private)
    python scripts/fetch_models.py --from DIR  # or copy from a local folder (ml/models/report-nlp/onnx)

Each committed manifest (backend/app/ai/*/models/*.manifest.json) names a GitHub Release and pins the
files' SHA-256 and size. Files are downloaded to a temporary folder, checked, and only then moved
into place; a file that does not match is refused. Files already present and correct are kept.

By default the GitHub CLI is used when it is installed, and plain HTTPS otherwise. HTTPS downloads go
to github.com only (its release downloads redirect to GitHub's own storage), are capped at the size the
manifest pins, and are checked like any other. The release images already contain the files.

In CI, GH_TOKEN is the workflow token (contents: read is enough for a release of the same repository).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = sorted((ROOT / "backend" / "app" / "ai").glob("*/models/*.manifest.json"))
REPOSITORY = "whoispasindu/SiteSense"
RELEASE_HOST = "github.com"
# github.com redirects a release download to its own storage; nothing else is followed.
ALLOWED_REDIRECT_HOSTS = frozenset(
    {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def matches(path: Path, entry: dict[str, object]) -> bool:
    return path.is_file() and path.stat().st_size == entry["bytes"] and sha256(path) == entry["sha256"]


def target_dir(manifest_path: Path, manifest: dict[str, object]) -> Path:
    # backend/app/ai/nlp/models/report-issues-category-v1.1.0.manifest.json -> models/report-issues-category/
    return manifest_path.parent / str(manifest["name"])


class _GitHubOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_REDIRECT_HOSTS:
            raise urllib.error.HTTPError(newurl, code, f"refused redirect to {parsed.hostname}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def release_url(tag: str, name: str) -> str:
    return (
        f"https://{RELEASE_HOST}/{REPOSITORY}/releases/download/"
        f"{urllib.parse.quote(tag)}/{urllib.parse.quote(name)}"
    )


def download_https(tag: str, name: str, into: Path, max_bytes: int) -> Path:
    opener = urllib.request.build_opener(_GitHubOnly)
    # A fixed https URL on github.com (release_url); redirects are limited to GitHub's storage.
    request = urllib.request.Request(  # noqa: S310
        release_url(tag, name), headers={"User-Agent": "SiteSense-fetch-models"}
    )
    target = into / name
    try:
        with opener.open(request, timeout=60) as response, target.open("wb") as out:
            written = 0
            for block in iter(lambda: response.read(1 << 20), b""):
                written += len(block)
                if written > max_bytes:
                    break  # larger than the manifest says: the size check refuses it
                out.write(block)
    except urllib.error.HTTPError as exc:
        hint = " (is the repository public? otherwise use --via gh)" if exc.code == 404 else ""
        sys.exit(f"Could not download {name}: HTTP {exc.code}{hint}.")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        sys.exit(f"Could not download {name}: {exc}.")
    return target


def download(tag: str, name: str, into: Path) -> Path:
    gh = shutil.which("gh") or shutil.which("gh.exe")
    if gh is None:
        sys.exit("The GitHub CLI (gh) is not installed: use --via https, or --from DIR.")
    subprocess.run(  # noqa: S603 - fixed program and arguments, no shell
        [gh, "release", "download", tag, "--repo", REPOSITORY, "--pattern", name, "--dir", str(into)],
        check=True,
    )
    return into / name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--from", dest="source", type=Path, help="copy the files from this folder instead")
    parser.add_argument(
        "--via",
        choices=("auto", "gh", "https"),
        default="auto",
        help="how to download: the GitHub CLI, plain HTTPS, or the CLI when installed (default)",
    )
    args = parser.parse_args(argv)
    via = args.via
    if via == "auto":
        via = "gh" if (shutil.which("gh") or shutil.which("gh.exe")) else "https"
    if not MANIFESTS:
        print("No model manifests found.")
        return 0
    failures = 0
    for manifest_path in MANIFESTS:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        destination = target_dir(manifest_path, manifest)
        destination.mkdir(parents=True, exist_ok=True)
        for entry in manifest["files"].values():
            name = str(entry["name"])
            final = destination / name
            if matches(final, entry):
                print(f"ok      {final.relative_to(ROOT)}")
                continue
            with tempfile.TemporaryDirectory() as tmp:
                if args.source is not None:
                    fetched = Path(tmp) / name
                    shutil.copy(args.source / name, fetched)
                elif via == "https":
                    fetched = download_https(
                        str(manifest["release_tag"]), name, Path(tmp), int(str(entry["bytes"]))
                    )
                else:
                    fetched = download(str(manifest["release_tag"]), name, Path(tmp))
                if not matches(fetched, entry):
                    print(f"REFUSED {name}: does not match {manifest_path.name}", file=sys.stderr)
                    failures += 1
                    continue
                shutil.move(str(fetched), final)
                print(f"fetched {final.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
