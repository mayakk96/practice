#!/usr/bin/env python3
"""Export the storefront for static review; the complete app still uses Flask.

Run from any directory with ``python tools/export_preview.py``. The output is
``dist/``, including a browser-local demo API and a complete source archive.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
EXCLUDED_DIRECTORIES = {
    ".git", ".openai", ".venv", "venv", "instance", "work", "dist", "__pycache__",
    ".pytest_cache", "node_modules", ".mypy_cache", ".ruff_cache",
}


def include_source(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
        return False
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return False
    if path.name == ".DS_Store" or path.suffix in {".pyc", ".pyo", ".zip", ".sqlite3"}:
        return False
    if ".sqlite3-" in path.name:
        return False
    return path.is_file() and not path.is_symlink()


def export() -> None:
    catalog = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))
    if not isinstance(catalog, list) or len(catalog) != 47:
        raise ValueError("The review export requires the complete 47-product catalog.")
    identifiers = [product["id"] for product in catalog]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Product identifiers must be unique.")
    if any(not identifier or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in identifier)
           for identifier in identifiers):
        raise ValueError("Product identifiers must be safe lowercase URL slugs.")

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copytree(ROOT / "static", DIST / "static")
    shell = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    application_tag = '<script src="/static/js/app.js" defer></script>'
    if shell.count(application_tag) != 1:
        raise ValueError("Expected exactly one storefront application script.")
    shell = shell.replace(application_tag,
                          '<script src="/preview-runtime.js" defer></script>\n  ' + application_tag)
    (DIST / "index.html").write_text(shell, encoding="utf-8")
    for route in ["shop", "checkout", *(f"product/{identifier}" for identifier in identifiers)]:
        route_directory = DIST / route
        route_directory.mkdir(parents=True, exist_ok=True)
        (route_directory / "index.html").write_text(shell, encoding="utf-8")

    runtime = (ROOT / "tools" / "preview-runtime.js").read_text(encoding="utf-8")
    marker = "__ODD_ORBIT_CATALOG__"
    if runtime.count(marker) != 1:
        raise ValueError("The static review runtime needs exactly one catalog placeholder.")
    runtime = runtime.replace(marker, json.dumps(catalog, ensure_ascii=False, separators=(",", ":")))
    (DIST / "preview-runtime.js").write_text(runtime, encoding="utf-8")

    archive = DIST / "odd-orbit-project.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(ROOT.rglob("*")):
            if include_source(path):
                package.write(path, Path("odd-orbit") / path.relative_to(ROOT))
    print(f"Static review exported: {DIST}")
    print(f"Products: {len(catalog)}; source archive: {archive.stat().st_size:,} bytes")


if __name__ == "__main__":
    export()
