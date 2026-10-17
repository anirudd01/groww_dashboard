"""Set-up shared by the broker scripts: import paths, ``.env``, logging, and running a list of jobs."""

import logging
import os
import sys
import time
from typing import Callable, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")
for _path in (ROOT, SCRIPTS):
    if _path not in sys.path:
        sys.path.insert(0, _path)

logger = logging.getLogger("jobs")

#: (label, zero-argument callable returning an exit code)
Job = Tuple[str, Callable[[], int]]


def setup(verbose: bool = False) -> None:
    """Log to the console and load ``.env`` (broker credentials)."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(message)s")
    logging.getLogger("market").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"), override=True)
    except ImportError:
        pass


def run_jobs(jobs: List[Job]) -> int:
    """Run every job in order, even after one fails, and return the worst exit code.

    One job failing (a network error, a missing session) must not stop the others: a stale
    instrument list is no reason to skip storing today's closes.
    """
    worst, outcomes = 0, []
    for label, job in jobs:
        logger.info("\n== %s", label)
        started = time.monotonic()
        try:
            code = job()
        except Exception as exc:  # noqa: BLE001 - report it and carry on with the next job
            logger.exception("%s failed: %s", label, exc)
            code = 1
        outcomes.append((label, code, time.monotonic() - started))
        worst = max(worst, code)
    if len(outcomes) > 1:
        logger.info("\n== Summary")
        for label, code, seconds in outcomes:
            logger.info("  %-28s %-8s %5.0f s", label, {0: "ok", 2: "partial"}.get(code, "FAILED"), seconds)
    return worst
