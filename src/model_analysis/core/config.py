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
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


def _csv_env(name: str, default: str) -> list[str]:
    return [b.strip() for b in os.getenv(name, default).split(",") if b.strip()]


# 对象存储下载凭证（收到 s3://bucket/key 或裸 object key 时用）。凭证留服务端，不经请求体传递。
# 两套后端：AWS S3 与 百度 BOS。按 URI 里的桶名归属选用对应凭证（桶在 BOS_BUCKETS 里 → 用 BOS）。
# —— AWS S3 ——
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")
S3_SESSION_TOKEN = os.getenv("S3_SESSION_TOKEN", "")  # 可选，临时凭证
S3_REGION = os.getenv("S3_REGION", "us-west-2")
S3_BUCKETS = _csv_env("S3_BUCKETS", "tripo-data,vast-plugin-data")  # AWS 侧桶（逗号分隔）
# —— 百度 BOS（S3 兼容，需独立 endpoint + 凭证）——
BOS_ACCESS_KEY = os.getenv("BOS_ACCESS_KEY", "")
BOS_SECRET_KEY = os.getenv("BOS_SECRET_KEY", "")
BOS_ENDPOINT = os.getenv("BOS_ENDPOINT", "")
BOS_BUCKETS = _csv_env("BOS_BUCKETS", "cn-openapi,cn-openapi-test,tripo-studio-cn-data-prod,tripo-studio-cn-data-test")

BLENDER_BIN = os.getenv("BLENDER_BIN", "/Applications/Blender.app/Contents/MacOS/Blender")
BLENDER_SCRIPT = PROJECT_ROOT / "scripts" / "blender_analyze_model.py"
ALLOWED_EXTS = {".glb", ".gltf", ".fbx", ".obj", ".stl", ".dae", ".usd", ".usdz"}
QUALITY_RULES = [
    {"name": "faces_red", "condition": "faces > 2000000", "severity": "red"},
    {"name": "faces_yellow", "condition": "faces > 100000", "severity": "yellow"},
    {"name": "non_manifold", "condition": "non_manifold_edge_count > 0", "severity": "yellow/red"},
    {"name": "zero_area", "condition": "zero_area_faces > 0", "severity": "red"},
]

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
ASSET_DIR.mkdir(parents=True, exist_ok=True)
