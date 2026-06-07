from __future__ import annotations

import asyncio
import shutil
import time
from typing import Any

from model_analysis.core.config import ASSET_DIR, TASK_RETENTION_SECONDS

_tasks_lock = asyncio.Lock()
_tasks: dict[str, dict[str, Any]] = {}


def now() -> float:
    return time.time()


def task_public_view(task: dict[str, Any]) -> dict[str, Any]:
    view = {
        "task_id": task["task_id"],
        "status": task["status"],
        "source_url": task["source_url"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }
    for key in ("started_at", "finished_at", "message", "error", "result"):
        if key in task:
            view[key] = task[key]
    return view


async def cleanup_finished_tasks() -> None:
    cutoff = now() - TASK_RETENTION_SECONDS
    async with _tasks_lock:
        expired = [
            task_id
            for task_id, task in _tasks.items()
            if task.get("status") in {"succeeded", "failed"} and float(task.get("finished_at") or 0) < cutoff
        ]
        for task_id in expired:
            _tasks.pop(task_id, None)
            shutil.rmtree(ASSET_DIR / task_id, ignore_errors=True)


async def create_task(task_id: str, source_url: str) -> dict[str, Any]:
    created_at = now()
    task = {
        "task_id": task_id,
        "status": "pending",
        "source_url": source_url,
        "created_at": created_at,
        "updated_at": created_at,
        "message": "任务已提交",
    }
    async with _tasks_lock:
        _tasks[task_id] = task
    return task


async def update_task(task_id: str, **updates: Any) -> None:
    updates["updated_at"] = now()
    async with _tasks_lock:
        if task_id in _tasks:
            _tasks[task_id].update(updates)


async def get_task(task_id: str) -> dict[str, Any] | None:
    async with _tasks_lock:
        return _tasks.get(task_id)
