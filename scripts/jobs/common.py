"""Set-up shared by the broker scripts: import paths, ``.env``, logging, and running a list of jobs."""

import logging
import os
import sys
import time
from collections.abc import Callable

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")
for _path in (ROOT, SCRIPTS):
    if _path not in sys.path:
        sys.path.insert(0, _path)

logger = logging.getLogger("jobs")

#: (label, zero-argument callable returning an exit code)
Job = tuple[str, Callable[[], int]]


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


def _run_once(jobs: list[Job]) -> dict[str, tuple[int, float]]:
    """Run each job in order; ``{label: (exit code, seconds)}``."""
    outcomes: dict[str, tuple[int, float]] = {}
    for label, job in jobs:
        logger.info("\n== %s", label)
        started = time.monotonic()
        try:
            code = job()
        except Exception as exc:  # noqa: BLE001 - report it and carry on with the next job
            logger.exception("%s failed: %s", label, exc)
            code = 1
        outcomes[label] = (code, time.monotonic() - started)
    return outcomes


def run_jobs(jobs: list[Job], retries: int = 0, retry_gap: float = 600.0,
             sleep: Callable[[float], None] = time.sleep, deadline: float | None = None,
             clock: Callable[[], float] = time.monotonic) -> int:
    """Run every job in order, even after one fails, and return the worst exit code.

    One job failing (a network error, a missing session) must not stop the others: a stale
    instrument list is no reason to skip storing today's closes.

    ``retries``: run the jobs that FAILED (exit 1) again, at most this many more times, waiting
    ``retry_gap`` seconds first. "Partial" (exit 2) is not retried: the next day's run catches
    the missing stocks up. The cap is the point - a job that keeps failing because the broker has
    no data must give up, not loop.

    ``deadline`` (a ``clock()`` value): no retry starts unless its wait plus the failed jobs' last
    run time fits before it, so the caller's own time limit never kills a run mid-job.
    """
    outcomes = _run_once(jobs)
    for attempt in range(1, retries + 1):
        failed = [(label, job) for label, job in jobs if outcomes[label][0] == 1]
        if not failed:
            break
        needed = retry_gap + sum(outcomes[label][1] for label, _ in failed)
        if deadline is not None and clock() + needed > deadline:
            logger.info("\n== No time left for retry %d (needs about %.0f s) - stopping here", attempt, needed)
            break
        logger.info("\n== Retry %d of %d in %.0f s: %s", attempt, retries, retry_gap,
                    ", ".join(label for label, _ in failed))
        sleep(retry_gap)
        outcomes.update(_run_once(failed))
    if len(outcomes) > 1:
        logger.info("\n== Summary")
        for label, (code, seconds) in outcomes.items():
            logger.info("  %-28s %-8s %5.0f s", label, {0: "ok", 2: "partial"}.get(code, "FAILED"), seconds)
    return max((code for code, _ in outcomes.values()), default=0)
