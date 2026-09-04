#!/usr/bin/env python3
"""`npm run dev` — a fully browsable marketplace with zero manual setup steps
beyond `cp .env.example .env` (BUILD.md section 5).

Sequence: bring up the data plane, generate, migrate, seed, then run the API,
the worker and the portal together until interrupted.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._paths import REPO_ROOT  # noqa: E402
from services.common.config import (  # noqa: E402
    ConfigurationError,
    load_dotenv,
    validate_environment,
)

COMPOSE_WAIT_SECONDS = 60
POLL_SECONDS = 2


def _run(command: list[str], *, check: bool = True) -> int:
    print(f"  $ {' '.join(command)}")
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def _compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info"], cwd=REPO_ROOT, capture_output=True, check=False
    )
    return probe.returncode == 0


def _wait_for_database(database_url: str) -> None:
    import psycopg

    deadline = time.monotonic() + COMPOSE_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(database_url, connect_timeout=POLL_SECONDS):
                print("  database ready")
                return
        except Exception:  # noqa: BLE001 — any failure means "not ready yet"
            time.sleep(POLL_SECONDS)
    raise SystemExit("dev: database did not become ready; is the data plane running?")


def main() -> int:
    if not (REPO_ROOT / ".env").exists():
        shutil.copyfile(REPO_ROOT / ".env.example", REPO_ROOT / ".env")
        print("dev: created .env from .env.example")

    load_dotenv()
    try:
        validate_environment()
    except ConfigurationError as error:
        print(f"dev: refusing to start — {error}", file=sys.stderr)
        return 1

    print("dev: data plane")
    if _compose_available():
        _run(["docker", "compose", "up", "-d", "--wait"])
    else:
        print("  docker is unavailable; expecting an already-running Postgres and Redis")

    _wait_for_database(os.environ["DATABASE_URL"])

    print("dev: generate, migrate, seed")
    _run([sys.executable, "scripts/gen.py"])
    _run([sys.executable, "scripts/migrate.py"])
    _run([sys.executable, "scripts/seed.py"])

    print("dev: api, worker, portal")
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "services.api.main:app", "--port", "8000"],
            cwd=REPO_ROOT,
        ),
        subprocess.Popen([sys.executable, "-m", "services.worker.main"], cwd=REPO_ROOT),
        subprocess.Popen(["npm", "run", "--workspace", "portal", "dev"], cwd=REPO_ROOT),
    ]

    def terminate(_signum: int, _frame: object) -> None:
        for process in processes:
            process.terminate()

    signal.signal(signal.SIGINT, terminate)
    signal.signal(signal.SIGTERM, terminate)

    exit_code = 0
    for process in processes:
        code = process.wait()
        exit_code = exit_code or code
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
