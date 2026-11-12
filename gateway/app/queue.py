from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


JobFn = Callable[[], Awaitable[Any]]


@dataclass
class QueueJob:
    id: str
    account_id: str
    enqueued_at: float = field(default_factory=time.time)
    position: int = 0


class InferenceQueue:
    """Single-GPU fair queue. Soft-reserve: gpu_count > 1 can spawn more workers later."""

    def __init__(self, maxsize: int = 32, workers: int = 1) -> None:
        self._sem = asyncio.Semaphore(max(1, workers))
        self._pending: list[QueueJob] = []
        self._lock = asyncio.Lock()
        self._maxsize = maxsize
        self.workers = max(1, workers)

    async def status(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "queue_depth": len(self._pending),
                "workers": self.workers,
                "maxsize": self._maxsize,
            }

    async def position_for(self, job_id: str) -> int | None:
        async with self._lock:
            for i, job in enumerate(self._pending):
                if job.id == job_id:
                    return i + 1
            return None

    async def run(self, account_id: str, fn: JobFn) -> Any:
        async with self._lock:
            if len(self._pending) >= self._maxsize:
                raise RuntimeError("Warteschlange voll — bitte später erneut versuchen")
            job = QueueJob(id=str(uuid.uuid4()), account_id=account_id)
            self._pending.append(job)
            job.position = len(self._pending)

        try:
            async with self._sem:
                async with self._lock:
                    self._pending = [j for j in self._pending if j.id != job.id]
                return await fn()
        finally:
            async with self._lock:
                self._pending = [j for j in self._pending if j.id != job.id]
