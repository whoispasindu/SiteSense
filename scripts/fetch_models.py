"""Fetch the model files that are too large for the repository, and verify them.

    python scripts/fetch_models.py             # download from the GitHub Release (needs gh, signed in)
    python scripts/fetch_models.py --from DIR  # or copy from a local folder (ml/models/report-nlp/onnx)

Each committed manifest (backend/app/ai/*/models/*.manifest.json) names a GitHub Release and pins the
files' SHA-256 and size. Files are downloaded to a temporary folder, checked, and only then moved
into place; a file that does not match is refused. Files already present and correct are kept.

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = sorted((ROOT / "backend" / "app" / "ai").glob("*/models/*.manifest.json"))
REPOSITORY = "whoispasindu/SiteSense"


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


def download(tag: str, name: str, into: Path) -> Path:
    gh = shutil.which("gh") or shutil.which("gh.exe")
    if gh is None:
        sys.exit("The GitHub CLI (gh) is needed to download model files, or use --from DIR.")
    subprocess.run(  # noqa: S603 - fixed program and arguments, no shell
        [gh, "release", "download", tag, "--repo", REPOSITORY, "--pattern", name, "--dir", str(into)],
        check=True,
    )
    return into / name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--from", dest="source", type=Path, help="copy the files from this folder instead")
    args = parser.parse_args(argv)
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
