from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import Any

from model_analysis.core.config import ALLOWED_EXTS, ASSET_DIR, DOWNLOAD_DIR, STALE_DOWNLOAD_SECONDS, TASK_RETENTION_SECONDS

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
    expired: list[str] = []
    async with _tasks_lock:
        expired = [
            task_id
            for task_id, task in _tasks.items()
            if task.get("status") in {"succeeded", "failed"} and float(task.get("finished_at") or 0) < cutoff
        ]
        for task_id in expired:
            _tasks.pop(task_id, None)

    for task_id in expired:
        shutil.rmtree(ASSET_DIR / task_id, ignore_errors=True)


async def cleanup_runtime_cache() -> None:
    await cleanup_finished_tasks()
    async with _tasks_lock:
        active_task_ids = set(_tasks)
    await asyncio.to_thread(_cleanup_stale_storage_sync, active_task_ids)


def _is_expired(path: Path, cutoff: float) -> bool:
    try:
        return path.stat().st_mtime < cutoff
    except FileNotFoundError:
        return False


def _is_asset_dir(path: Path) -> bool:
    try:
        return path.resolve() == ASSET_DIR.resolve()
    except FileNotFoundError:
        return path == ASSET_DIR


def _cleanup_stale_storage_sync(active_task_ids: set[str]) -> None:
    asset_cutoff = now() - TASK_RETENTION_SECONDS
    download_cutoff = now() - STALE_DOWNLOAD_SECONDS

    if ASSET_DIR.exists():
        for path in ASSET_DIR.iterdir():
            if path.name in active_task_ids or not _is_expired(path, asset_cutoff):
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

    if not DOWNLOAD_DIR.exists():
        return

    for path in DOWNLOAD_DIR.iterdir():
        if _is_asset_dir(path) or not _is_expired(path, download_cutoff):
            continue
        if path.is_file() and path.suffix.lower() in ALLOWED_EXTS:
            path.unlink(missing_ok=True)
        elif path.is_dir() and path.name.endswith("_files"):
            shutil.rmtree(path, ignore_errors=True)


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
