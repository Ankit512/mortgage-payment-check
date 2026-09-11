"""Build a clean Vercel project and companion worker source bundle; no credentials or model weights."""

import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _stage(target):
    vercel = target / "vercel"
    shutil.copytree(ROOT / "deployment" / "vercel", vercel,
                    ignore=shutil.ignore_patterns("__pycache__", ".vercel", ".env*"))
    shutil.copytree(ROOT / "app" / "static", vercel / "public" / "static")
    shutil.copy2(ROOT / "app" / "static" / "index.html", vercel / "public" / "index.html")
    companion = target / "worker"
    for folder in ("app", "data"):
        shutil.copytree(ROOT / folder, companion / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (companion / "deployment").mkdir()
    shutil.copy2(ROOT / "deployment" / "Dockerfile", companion / "deployment" / "Dockerfile")
    for filename in ("requirements.txt", "compose.yaml", ".dockerignore"):
        shutil.copy2(ROOT / filename, companion / filename)
    shutil.copy2(ROOT / "docs" / "DEPLOYMENT.md", target / "README.md")


def bundle(destination=None):
    target = Path(destination) if destination else ROOT / "dist" / "mortgage-payment-app"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="uc1-package-") as scratch:
        staged = Path(scratch) / target.name
        _stage(staged)
        # Archive only the fresh source copy, never local deployment settings.
        archive = shutil.make_archive(str(target), "zip", root_dir=scratch, base_dir=target.name)
        # Preserve an existing worker .env and Vercel link when rebuilding.
        shutil.copytree(staged, target, dirs_exist_ok=True)
    return target, Path(archive)


if __name__ == "__main__":
    target, archive = bundle()
    print(f"Vercel project: {target / 'vercel'}\nWorker bundle: {target / 'worker'}\nArchive: {archive}")
