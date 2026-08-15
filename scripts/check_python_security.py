"""Run Bandit against exactly the Python files Git can publish."""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def public_python_files() -> list[str]:
    # Fixed arguments are passed directly to Git without a shell.
    completed = subprocess.run(  # nosec B603 B607
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.py"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    files = []
    for relative in completed.stdout.splitlines():
        if relative and "tests" not in {part.casefold() for part in Path(relative).parts}:
            files.append(relative)
    return files


def main() -> int:
    files = public_python_files()
    if not files:
        print("[FAIL] No se encontraron módulos Python publicables para analizar.")
        return 1
    # sys.executable, the Bandit module and every target are fixed or obtained
    # from Git's own public-file inventory; shell execution is never enabled.
    completed = subprocess.run(  # nosec B603
        [sys.executable, "-m", "bandit", "-q", *files],
        cwd=REPO_ROOT,
        check=False,
    )
    if completed.returncode == 0:
        print(f"Bandit OK: {len(files)} módulos Python publicables analizados.")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
