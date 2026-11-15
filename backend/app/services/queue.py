from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from typing import Any

from app.db import Database
from app.services.refresh import AddressNotFound, RefreshService
from app.utils.time import utcnow_iso

logger = logging.getLogger(__name__)


class RefreshQueue:
    """Single-worker refresh queue with a hard spacing between address starts."""

    def __init__(
        self,
        db: Database,
        refresh_service: RefreshService,
        interval_seconds: float = 3.0,
    ):
        self.db = db
        self.refresh_service = refresh_service
        self.interval_seconds = max(0.0, interval_seconds)
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._last_started: float | None = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stopping = False
        now = utcnow_iso()
        # A running job cannot survive a process restart; queued jobs can.
        self.db.execute(
            """
            UPDATE refresh_jobs
            SET status = 'failed', finished_at = ?, error = 'Interrupted by server restart'
            WHERE status = 'running'
            """,
            (now,),
        )
        queued = self.db.fetchall(
            "SELECT id FROM refresh_jobs WHERE status = 'queued' ORDER BY id"
        )
        for row in queued:
            self._queue.put_nowait(row["id"])
        self._task = asyncio.create_task(self._worker(), name="assetx-refresh-worker")
        logger.info("refresh worker started; requeued %s job(s)", len(queued))

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("refresh worker stopped")

    async def enqueue(self, address_id: int, trigger: str = "manual") -> dict[str, Any]:
        existing = self.db.fetchone(
            """
            SELECT id, status, created_at FROM refresh_jobs
            WHERE address_id = ? AND status IN ('queued', 'running')
            ORDER BY id DESC LIMIT 1
            """,
            (address_id,),
        )
        if existing:
            return {
                "job_id": existing["id"],
                "status": existing["status"],
                "created_at": existing["created_at"],
                "deduplicated": True,
            }
        created_at = utcnow_iso()
        try:
            with self.db.transaction() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO refresh_jobs(address_id, status, trigger, created_at)
                    VALUES (?, 'queued', ?, ?)
                    """,
                    (address_id, trigger, created_at),
                )
                job_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            existing = self.db.fetchone(
                """
                SELECT id, status, created_at FROM refresh_jobs
                WHERE address_id = ? AND status IN ('queued', 'running')
                ORDER BY id DESC LIMIT 1
                """,
                (address_id,),
            )
            if not existing:
                raise
            return {
                "job_id": existing["id"],
                "status": existing["status"],
                "created_at": existing["created_at"],
                "deduplicated": True,
            }
        await self._queue.put(job_id)
        return {
            "job_id": job_id,
            "status": "queued",
            "created_at": created_at,
            "deduplicated": False,
        }

    async def enqueue_many(self, address_ids: list[int], trigger: str = "manual-all") -> list[dict[str, Any]]:
        results = []
        for address_id in address_ids:
            results.append(await self.enqueue(address_id, trigger))
        return results

    async def _wait_for_slot(self) -> None:
        if self._last_started is None or self.interval_seconds <= 0:
            return
        remaining = self.interval_seconds - (time.monotonic() - self._last_started)
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _worker(self) -> None:
        while not self._stopping:
            job_id = await self._queue.get()
            try:
                await self._wait_for_slot()
                self._last_started = time.monotonic()
                await self._process(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - worker must survive a bad job
                logger.exception("unexpected refresh worker error for job %s", job_id)
            finally:
                self._queue.task_done()

    async def _process(self, job_id: int) -> None:
        job = self.db.fetchone("SELECT * FROM refresh_jobs WHERE id = ?", (job_id,))
        if job is None or job["status"] != "queued":
            return
        started_at = utcnow_iso()
        started_monotonic = time.monotonic()
        self.db.execute(
            "UPDATE refresh_jobs SET status = 'running', started_at = ? WHERE id = ?",
            (started_at, job_id),
        )
        address_id = job["address_id"]
        if address_id is None:
            self._finish_failed(job_id, started_monotonic, "address no longer exists")
            return
        try:
            result = await self.refresh_service.refresh_address(address_id)
        except AddressNotFound:
            self._finish_failed(job_id, started_monotonic, "address was deleted")
            return
        except Exception as exc:  # noqa: BLE001
            message = str(exc).strip()[:1000] or exc.__class__.__name__
            self._finish_failed(job_id, started_monotonic, message)
            self.db.execute(
                "UPDATE addresses SET last_refresh_error = ?, updated_at = ? WHERE id = ?",
                (message, utcnow_iso(), address_id),
            )
            logger.warning("refresh job %s failed: %s", job_id, message)
            return
        self._finish_success(job_id, started_monotonic, result)

    def _finish_success(self, job_id: int, started_monotonic: float, result: dict[str, Any]) -> None:
        finished_at = utcnow_iso()
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        self.db.execute(
            """
            UPDATE refresh_jobs
            SET status = 'success', finished_at = ?, duration_ms = ?, provider = ?, warning = ?
            WHERE id = ?
            """,
            (finished_at, duration_ms, result.get("provider"), result.get("warning"), job_id),
        )

    def _finish_failed(self, job_id: int, started_monotonic: float, error: str) -> None:
        finished_at = utcnow_iso()
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        self.db.execute(
            """
            UPDATE refresh_jobs
            SET status = 'failed', finished_at = ?, duration_ms = ?, error = ?
            WHERE id = ?
            """,
            (finished_at, duration_ms, error, job_id),
        )

    def status(self) -> dict[str, Any]:
        rows = self.db.fetchall(
            "SELECT status, COUNT(*) AS count FROM refresh_jobs GROUP BY status"
        )
        counts = {row["status"]: row["count"] for row in rows}
        active = self.db.fetchall(
            """
            SELECT j.id, j.address_id, j.status, j.created_at, j.started_at,
                   a.chain, a.address
            FROM refresh_jobs j
            LEFT JOIN addresses a ON a.id = j.address_id
            WHERE j.status IN ('queued', 'running')
            ORDER BY j.id
            """
        )
        return {
            "worker_running": self.running,
            "queue_size": self._queue.qsize(),
            "interval_seconds": self.interval_seconds,
            "counts": {
                "queued": counts.get("queued", 0),
                "running": counts.get("running", 0),
                "success": counts.get("success", 0),
                "failed": counts.get("failed", 0),
            },
            "active": [dict(row) for row in active],
        }
