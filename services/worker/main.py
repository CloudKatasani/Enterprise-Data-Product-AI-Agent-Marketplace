"""Worker entry point.

Runs the durable job loop: workflow advancement, nightly mesh recompute, demo
validation, quality scoring and reconciliation. Jobs register themselves with
the runner as milestones land.
"""

from __future__ import annotations

import signal
import sys
import time

from services.common.config import ConfigurationError, get_settings

POLL_INTERVAL_SECONDS = 5


def main() -> int:
    try:
        settings = get_settings()
    except ConfigurationError as error:
        print(f"worker: refusing to start — {error}", file=sys.stderr)
        return 1

    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    print(f"worker: started for tenant {settings.tenant_id}")
    try:
        from services.worker.runner import JobRunner
    except ImportError:
        print("worker: no jobs registered yet")
        while running:
            time.sleep(POLL_INTERVAL_SECONDS)
        return 0

    runner = JobRunner(settings)
    while running:
        runner.tick()
        time.sleep(POLL_INTERVAL_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
