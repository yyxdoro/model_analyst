from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    path = Path(value) if value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


DOWNLOAD_DIR = _path_from_env("DOWNLOAD_DIR", PROJECT_ROOT / "downloads")
ASSET_DIR = _path_from_env("ASSET_DIR", DOWNLOAD_DIR / "assets")
MAX_DOWNLOAD_BYTES = int(os.getenv("MAX_DOWNLOAD_BYTES", str(300 * 1024 * 1024)))
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "10"))
TASK_RETENTION_SECONDS = int(os.getenv("TASK_RETENTION_SECONDS", str(24 * 3600)))
ASSET_ROUTE = "/assets"
BLENDER_BIN = os.getenv("BLENDER_BIN", "/Applications/Blender.app/Contents/MacOS/Blender")
BLENDER_SCRIPT = PROJECT_ROOT / "scripts" / "blender_analyze_model.py"
ALLOWED_EXTS = {".glb", ".gltf", ".fbx", ".obj", ".stl", ".dae", ".usd", ".usdz"}
QUALITY_RULES = [
    {"name": "faces_red", "condition": "faces > 1000000", "severity": "red"},
    {"name": "faces_yellow", "condition": "faces > 100000", "severity": "yellow"},
    {"name": "non_manifold", "condition": "non_manifold_edge_count > 0", "severity": "yellow/red"},
    {"name": "zero_area", "condition": "zero_area_faces > 0", "severity": "red"},
]

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
ASSET_DIR.mkdir(parents=True, exist_ok=True)
