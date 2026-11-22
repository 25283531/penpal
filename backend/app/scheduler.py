"""Reply scheduler (Bug 1 fix): automatic reply generation, in-process.

Before this module, replies only happened when someone called
POST /api/v1/letters/process-due by hand — the App never calls it and
the backend had no timer, so a user who wrote a letter simply never
got a reply. This scheduler runs inside the same uvicorn process (the
Docker deployment is a single container, no host cron, no new service,
no new dependency):

- a daemon thread, started from the FastAPI lifespan in app/main.py;
- first pass immediately at startup, so a fresh deploy clears the
  backlog of already-due in-transit letters (including ones that have
  been waiting for days);
- then one pass every PENPAL_REPLY_INTERVAL_SECONDS (default 3600,
  i.e. hourly), sequential passes only — a slow pass is never run
  concurrently with the next one.

Each pass calls replies.process_all_due_replies (every device with a
due letter), logs the outcome, and records it in the scheduler_runs
table (counts only — see database.record_scheduler_run — surfaced in
the admin dashboard aggregates). A letter is only marked replied when
the LLM actually generated and stored a reply: with no LLM configured
the letter stays queued (llm_unavailable, counted, retried next pass);
an LLM error leaves the letter in_transit and the next pass retries
it. Nothing here ever fabricates a reply, and a failed pass never
silently drops a letter.

`process_fn` is injectable (tests / the thread both use it) so the
pass logic is testable without an LLM or a running thread.
"""
import logging
import os
import threading
from datetime import datetime, timezone

from . import database
from .replies import process_all_due_replies

logger = logging.getLogger("penpal.scheduler")

DEFAULT_INTERVAL_SECONDS = 3600


def interval_seconds() -> int:
    """Pass interval in seconds; env override for tests / ops."""
    try:
        value = int(os.environ.get(
            "PENPAL_REPLY_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS)
        ))
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS
    return max(1, value)


def run_scheduled_pass(day: str | None = None, process_fn=None) -> dict:
    """Run one scheduler pass synchronously and record it.

    Returns the aggregated result plus the persisted run's id and
    timestamps. Never raises for a per-device failure (those are
    counted); a top-level failure (e.g. the DB query itself) is
    recorded with `error` and re-raised nowhere — the thread logs it
    and carries on to the next pass.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    error = None
    try:
        result = process_all_due_replies(day=day, process_fn=process_fn)
    except Exception as e:  # noqa: BLE001 — a pass must not kill the scheduler
        logger.exception("penpal scheduler pass failed")
        error = str(e)[:500]
        result = {
            "day": day or datetime.now(timezone.utc).date().isoformat(),
            "devices": 0, "processed": 0, "replied": 0, "queued": 0,
            "failed": 0, "llm_unavailable": False, "error_counts": {},
            "details": [],
        }
    finished_at = datetime.now(timezone.utc).isoformat()
    record = database.record_scheduler_run({
        "started_at": started_at,
        "finished_at": finished_at,
        "day": result["day"],
        "devices": result["devices"],
        "processed": result["processed"],
        "replied": result["replied"],
        "queued": result["queued"],
        "failed": result["failed"],
        "llm_unavailable": result["llm_unavailable"],
        "error_counts": result["error_counts"],
        "error": error,
    })
    logger.info(
        "penpal scheduler pass: day=%s devices=%s processed=%s replied=%s "
        "queued=%s failed=%s llm_unavailable=%s errors=%s run_id=%s",
        result["day"], result["devices"], result["processed"],
        result["replied"], result["queued"], result["failed"],
        result["llm_unavailable"], result["error_counts"], record["id"],
    )
    return {**result, "run_id": record["id"], "started_at": started_at,
            "finished_at": finished_at, "error": error}


class ReplyScheduler:
    """Daemon-thread driver: first pass at once, then every interval."""

    def __init__(self, interval: int | None = None, process_fn=None):
        self.interval = interval if interval is not None else interval_seconds()
        self.process_fn = process_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> "ReplyScheduler":
        if self.running:
            return self
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="penpal-reply-scheduler", daemon=True,
        )
        self._thread.start()
        return self

    def _loop(self) -> None:
        # First pass immediately: a fresh deploy clears the backlog of
        # already-due letters instead of making them wait another hour.
        while not self._stop.is_set():
            try:
                run_scheduled_pass(process_fn=self.process_fn)
            except Exception:  # noqa: BLE001 — run_scheduled_pass already logs; never die
                logger.exception("penpal scheduler pass raised unexpectedly")
            # Wait the interval, but wake promptly on stop().
            self._stop.wait(self.interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)


_scheduler: ReplyScheduler | None = None
_scheduler_lock = threading.Lock()


def start_scheduler(interval: int | None = None, process_fn=None) -> ReplyScheduler:
    """Start (or return) the process-wide scheduler. Idempotent: a
    second call while it is running returns the running instance."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None and _scheduler.running:
            return _scheduler
        _scheduler = ReplyScheduler(interval=interval, process_fn=process_fn)
        _scheduler.start()
        logger.info("penpal reply scheduler started (interval=%ss)", _scheduler.interval)
        return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        scheduler, _scheduler = _scheduler, None
    if scheduler is not None:
        scheduler.stop()


def scheduler_status() -> dict:
    """Health/dashboard view: running state, interval, last pass."""
    summary = database.scheduler_summary()
    last = summary.get("last_run") or {}
    return {
        "running": _scheduler.running if _scheduler is not None else False,
        "interval_seconds": _scheduler.interval if _scheduler is not None else interval_seconds(),
        "runs": summary.get("runs", 0),
        "last_run_at": last.get("finished_at"),
        "last_run": last or None,
    }
