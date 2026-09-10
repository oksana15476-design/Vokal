"""Команды разработчика. Точки входа объявлены в pyproject.

Каталог фиксируем сами: команды ставятся в venv и могут быть вызваны из
любого места, а пакет `app` и настройки в `.env` лежат рядом с pyproject.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]


def _run(command: list[str]) -> int:
    return subprocess.call(command, cwd=SERVER_ROOT)


def dev() -> int:
    host = os.environ.get("VOKAL_DEV_HOST", "127.0.0.1")
    port = os.environ.get("VOKAL_DEV_PORT", "8000")
    return _run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:create_app",
            "--factory",
            "--reload",
            "--host",
            host,
            "--port",
            port,
            *sys.argv[1:],
        ]
    )


def test() -> int:
    return _run([sys.executable, "-m", "pytest", *sys.argv[1:]])


def lint() -> int:
    checks = [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
    ]
    failed = 0
    for check in checks:
        failed = _run(check) or failed
    return failed
