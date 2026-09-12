"""Build a presentable one-box demo zip: dashboard, API and Qwen compose stack."""

import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEEP = (".env",)


def _stage(target):
    for folder in ("app", "data"):
        shutil.copytree(ROOT / folder, target / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (target / "deployment").mkdir()
    shutil.copy2(ROOT / "deployment" / "Dockerfile", target / "deployment" / "Dockerfile")
    for filename in ("requirements.txt", "compose.yaml", ".dockerignore"):
        shutil.copy2(ROOT / filename, target / filename)
    shutil.copy2(ROOT / "docs" / "DEMO_STACK.md", target / "README.md")
    shutil.copy2(ROOT / "docs" / "consumer-dashboard.png", target / "overview.png")
    vercel = target / "optional" / "vercel"
    shutil.copytree(ROOT / "deployment" / "vercel", vercel,
                    ignore=shutil.ignore_patterns("__pycache__", ".vercel", ".env*"))
    shutil.copytree(ROOT / "app" / "static", vercel / "public" / "static")
    shutil.copy2(ROOT / "app" / "static" / "index.html", vercel / "public" / "index.html")
    shutil.copy2(ROOT / "docs" / "DEPLOYMENT.md", vercel / "README.md")


def bundle(destination=None):
    target = Path(destination) if destination else ROOT / "dist" / "mortgage-payment-app"
    target.parent.mkdir(parents=True, exist_ok=True)
    kept = {}
    for name in KEEP:
        path = target / name
        if path.is_file():
            kept[name] = path.read_bytes()
    with tempfile.TemporaryDirectory(prefix="uc1-package-") as scratch:
        staged = Path(scratch) / target.name
        _stage(staged)
        archive = shutil.make_archive(str(target), "zip", root_dir=scratch, base_dir=target.name)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(staged, target)
    for name, data in kept.items():
        (target / name).write_bytes(data)
    return target, Path(archive)


if __name__ == "__main__":
    target, archive = bundle()
    print(
        f"Demo stack: {target}\n"
        f"Open {target / 'README.md'} then: docker compose up --build\n"
        f"Archive: {archive}"
    )
