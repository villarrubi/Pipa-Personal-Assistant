"""Validate the public documentation contract without network access."""

from __future__ import annotations

import re
import subprocess  # nosec B404
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DOCUMENTS = (
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "docs/PUBLICATION_CHECKLIST.md",
    "firmware/THIRD_PARTY_NOTICES.md",
    "LICENSE",
    "CITATION.cff",
)
REQUIRED_README_HEADINGS = (
    "## Estado del proyecto",
    "## Inicio rápido sin hardware",
    "## Validación",
    "## Seguridad",
    "## Licencia",
)
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
EXTERNAL_SCHEMES = ("http://", "https://", "mailto:")


def public_markdown_files() -> list[Path]:
    # Fixed arguments are passed directly to Git without a shell.
    completed = subprocess.run(  # nosec B603 B607
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.md"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [REPO_ROOT / line for line in completed.stdout.splitlines() if line]


def local_link_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if not target or target.startswith("#") or target.lower().startswith(EXTERNAL_SCHEMES):
        return None
    # Markdown permits an optional quoted title after a whitespace separator.
    target = target.split(maxsplit=1)[0].strip("<>")
    return unquote(target.split("#", 1)[0]) or None


def main() -> int:
    failures: list[str] = []

    for relative in REQUIRED_DOCUMENTS:
        if not (REPO_ROOT / relative).is_file():
            failures.append(f"Falta el documento publico requerido: {relative}")

    readme_path = REPO_ROOT / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    for heading in REQUIRED_README_HEADINGS:
        if heading not in readme:
            failures.append(f"README.md no contiene la seccion requerida: {heading}")

    license_path = REPO_ROOT / "LICENSE"
    if license_path.is_file():
        license_text = license_path.read_text(encoding="utf-8")
        for marker in ("MIT License", "Copyright (c) 2026 villarrubi"):
            if marker not in license_text:
                failures.append(f"LICENSE no contiene el marcador requerido: {marker}")

    citation_path = REPO_ROOT / "CITATION.cff"
    if citation_path.is_file():
        citation = citation_path.read_text(encoding="utf-8")
        for marker in ("cff-version: 1.2.0", 'name: "villarrubi"', "license: MIT"):
            if marker not in citation:
                failures.append(f"CITATION.cff no contiene el marcador requerido: {marker}")

    markdown_files = public_markdown_files()
    checked_links = 0
    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        for match in LINK_PATTERN.finditer(text):
            target = local_link_target(match.group(1))
            if target is None:
                continue
            checked_links += 1
            destination = (path.parent / target).resolve()
            try:
                destination.relative_to(REPO_ROOT)
            except ValueError:
                failures.append(f"Enlace fuera del repositorio: {path.relative_to(REPO_ROOT)} -> {target}")
                continue
            if not destination.exists():
                failures.append(f"Enlace local roto: {path.relative_to(REPO_ROOT)} -> {target}")

    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1

    print(
        "Documentacion OK: "
        f"{len(markdown_files)} archivos Markdown y {checked_links} enlaces locales comprobados."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
