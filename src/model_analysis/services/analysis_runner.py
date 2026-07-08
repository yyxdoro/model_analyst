from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from model_analysis.analyzers.native_meshlib import analyze_white_model
from model_analysis.core.config import ASSET_ROUTE, BLENDER_BIN, BLENDER_SCRIPT

MATERIAL_EXTS = {".glb", ".gltf", ".fbx", ".obj", ".dae"}


class AnalysisError(RuntimeError):
    def __init__(self, message: str, code: str = "ANALYSIS_FAILED", engine_errors: Optional[list[dict[str, str]]] = None):
        super().__init__(message)
        self.code = code
        self.engine_errors = engine_errors or []


async def run_meshlib_analysis(file_path: Path) -> dict:
    return await asyncio.to_thread(analyze_white_model, str(file_path))


async def run_blender_analysis(file_path: Path, asset_dir: Optional[Path] = None) -> dict:
    if not Path(BLENDER_BIN).exists():
        raise AnalysisError(f"Blender not found at {BLENDER_BIN}", code="BLENDER_NOT_FOUND")
    if not BLENDER_SCRIPT.exists():
        raise AnalysisError(f"Blender analysis script not found: {BLENDER_SCRIPT}", code="BLENDER_SCRIPT_NOT_FOUND")

    cmd = [BLENDER_BIN, "--background", "--python", str(BLENDER_SCRIPT), "--", str(file_path)]
    if asset_dir is not None:
        asset_dir.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--asset-dir", str(asset_dir)])
    process = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True)
    stdout = process.stdout or ""
    if "---RESULT_START---" not in stdout or "---RESULT_END---" not in stdout:
        raise AnalysisError(f"Blender analysis failed: {stdout or process.stderr}", code="BLENDER_ANALYSIS_FAILED")

    json_text = stdout.split("---RESULT_START---", 1)[1].split("---RESULT_END---", 1)[0].strip()
    return json.loads(json_text)


def _attach_asset_urls(value, task_id: str, public_base_url: str = "") -> None:
    if isinstance(value, dict):
        asset_file = value.get("asset_file")
        if isinstance(asset_file, str) and asset_file:
            path = f"{ASSET_ROUTE}/{task_id}/{asset_file}"
            value["url"] = f"{public_base_url}{path}" if public_base_url else path
        value.pop("asset_path", None)
        value.pop("abspath", None)
        for child in value.values():
            _attach_asset_urls(child, task_id, public_base_url)
    elif isinstance(value, list):
        for child in value:
            _attach_asset_urls(child, task_id, public_base_url)


def _engine_error(engine: str, exc: Exception, default_code: str) -> dict[str, str]:
    return {
        "engine": engine,
        "code": getattr(exc, "code", default_code),
        "message": str(exc),
    }


def _summary(native: Optional[dict[str, Any]], blender: Optional[dict[str, Any]], meshes: list[dict[str, Any]], materials: list[dict[str, Any]], armatures: list[dict[str, Any]], animations: list[dict[str, Any]]) -> dict[str, Any]:
    native_summary = native.get("summary") if isinstance(native, dict) else {}
    blender_summary = blender.get("summary") if isinstance(blender, dict) else {}
    return {
        "mesh_count": len(meshes),
        "material_count": len(materials),
        "armature_count": len(armatures),
        "animation_count": len(animations),
        "total_vertices": sum(int(mesh.get("vertices") or 0) for mesh in meshes),
        "total_faces": sum(int(mesh.get("faces") or 0) for mesh in meshes),
        "total_triangles": sum(int(mesh.get("triangles") or 0) for mesh in meshes),
        "total_triangle_faces": sum(int(mesh.get("triangle_faces") or 0) for mesh in meshes),
        "total_quad_faces": sum(int(mesh.get("quad_faces") or 0) for mesh in meshes),
        "zero_area_faces": sum(int(mesh.get("zero_area_faces") or 0) for mesh in meshes),
        "non_manifold_edge_count": sum(int(mesh.get("non_manifold_edge_count") or 0) for mesh in meshes),
        "boundary_edge_count": sum(int(mesh.get("boundary_edge_count") or 0) for mesh in meshes),
        "self_intersection_count": int((native_summary or {}).get("self_intersection_count") or (blender_summary or {}).get("self_intersection_count") or 0),
        "meshlib_available": (native_summary or {}).get("meshlib_available"),
        "no_format_conversion": bool((native_summary or {}).get("no_format_conversion")),
    }


def _merge_analysis(native: Optional[dict[str, Any]], blender: Optional[dict[str, Any]], engine: str, errors: list[dict[str, str]]) -> dict[str, Any]:
    meshes = (native or {}).get("meshes") or (blender or {}).get("meshes") or []
    materials = (blender or {}).get("materials") or (native or {}).get("materials") or []
    armatures = (blender or {}).get("armatures") or (native or {}).get("armatures") or []
    animations = (blender or {}).get("animations") or (native or {}).get("animations") or []
    return {
        "analyzer": "hybrid_native_blender" if engine == "hybrid" else (native or blender or {}).get("analyzer"),
        "engines": {
            "primary": engine,
            "geometry": (native or {}).get("analyzer") if native else None,
            "materials": "blender" if blender else None,
        },
        "analysis_errors": errors,
        "native": native,
        "blender": blender,
        "native_reader": (native or {}).get("native_reader"),
        "meshlib": (native or {}).get("meshlib"),
        "dependencies": (native or {}).get("dependencies"),
        "summary": _summary(native, blender, meshes, materials, armatures, animations),
        "meshes": meshes,
        "materials": materials,
        "armatures": armatures,
        "animations": animations,
    }


async def run_model_analysis(file_path: Path, asset_dir: Optional[Path] = None, task_id: Optional[str] = None, public_base_url: str = "") -> tuple[str, dict]:
    native = None
    blender = None
    errors: list[dict[str, str]] = []

    try:
        native = await run_meshlib_analysis(file_path)
    except Exception as native_exc:
        errors.append(_engine_error("native", native_exc, "NATIVE_ANALYSIS_FAILED"))

    if file_path.suffix.lower() in MATERIAL_EXTS:
        try:
            blender = await run_blender_analysis(file_path, asset_dir)
        except Exception as blender_exc:
            errors.append(_engine_error("blender", blender_exc, "BLENDER_ANALYSIS_FAILED"))

    if native and blender:
        engine = "hybrid"
    elif native:
        engine = "native"
    elif blender:
        engine = "blender_fallback"
    else:
        raise AnalysisError("Native and Blender analysis both failed", engine_errors=errors)

    analysis = _merge_analysis(native, blender, engine, errors)
    if task_id:
        _attach_asset_urls(analysis, task_id, public_base_url)
    return engine, analysis
