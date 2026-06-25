from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from contextlib import asynccontextmanager, suppress
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from model_analysis.api.schemas import AnalyzeRequest
from model_analysis.core.config import ASSET_DIR, ASSET_ROUTE, CLEANUP_INTERVAL_SECONDS, MAX_CONCURRENT_JOBS, PUBLIC_BASE_URL, TASK_RETENTION_SECONDS
from model_analysis.expert.skill import analyze_with_3d_expert_skill
from model_analysis.services.analysis_runner import run_model_analysis
from model_analysis.services.downloader import download_model
from model_analysis.services.quality import quality_status_from_analysis
from model_analysis.services.task_store import (
    cleanup_finished_tasks,
    cleanup_runtime_cache,
    create_task,
    get_task as get_stored_task,
    now,
    task_public_view,
    update_task,
)

logger = logging.getLogger(__name__)


async def _cleanup_loop() -> None:
    while True:
        try:
            await cleanup_runtime_cache()
        except Exception:
            logger.exception("runtime cache cleanup failed")
        await asyncio.sleep(max(CLEANUP_INTERVAL_SECONDS, 60))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await cleanup_runtime_cache()
    except Exception:
        logger.exception("startup cache cleanup failed")
    cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


app = FastAPI(title="Model Analysis API", version="1.1.0", lifespan=lifespan)
app.mount(ASSET_ROUTE, StaticFiles(directory=ASSET_DIR), name="assets")

_job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)


def _fallback_error(exc: Exception) -> dict:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            return {
                "code": detail.get("code") or "HTTP_ERROR",
                "message": detail.get("message") or "请求处理失败",
                "detail": detail.get("detail") or detail.get("message") or "未知错误",
            }
        return {"code": "HTTP_ERROR", "message": "请求处理失败", "detail": str(detail or "未知错误")}

    return {
        "code": getattr(exc, "code", "ANALYSIS_FAILED"),
        "message": "模型分析失败，请检查 URL 是否可下载、文件格式是否受支持，或确认分析依赖已正确安装。",
        "detail": str(exc) or "未知错误",
        "engine_errors": getattr(exc, "engine_errors", []),
    }


def _mesh_report(meshes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "mesh_count": len(meshes),
        "vertices": sum(int(mesh.get("vertices") or 0) for mesh in meshes),
        "faces": sum(int(mesh.get("faces") or 0) for mesh in meshes),
        "triangles": sum(int(mesh.get("triangles") or 0) for mesh in meshes),
        "meshes": [
            {
                "name": mesh.get("name"),
                "vertices": mesh.get("vertices"),
                "faces": mesh.get("faces"),
                "triangles": mesh.get("triangles"),
                "dimensions": mesh.get("dimensions"),
                "has_uv": mesh.get("has_uv"),
                "is_manifold": mesh.get("is_manifold"),
                "non_manifold_edge_count": mesh.get("non_manifold_edge_count"),
                "boundary_edge_count": mesh.get("boundary_edge_count"),
                "zero_area_faces": mesh.get("zero_area_faces"),
                "loose_edge_count": mesh.get("loose_edge_count"),
                "inward_normal_ratio": mesh.get("inward_normal_ratio"),
                "has_custom_normals": mesh.get("has_custom_normals"),
            }
            for mesh in meshes
        ],
    }


def _texture_channel_name(channel: str) -> str:
    return {
        "baseColorTexture": "Base Color",
        "metallicRoughnessTexture": "Metallic/Roughness",
        "normalTexture": "Normal",
        "occlusionTexture": "Occlusion",
        "emissiveTexture": "Emissive",
    }.get(channel, channel)


def _material_report(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    report = []
    for material in materials:
        if not isinstance(material, dict):
            report.append({"name": str(material), "texture_count": 0, "textures": []})
            continue
        textures = []
        raw_textures = material.get("textures")
        if isinstance(raw_textures, dict):
            for channel, texture in raw_textures.items():
                texture = texture if isinstance(texture, dict) else {}
                textures.append(
                    {
                        "channel": _texture_channel_name(str(channel)),
                        "image_name": texture.get("image"),
                        "source_file": None,
                        "packed": None,
                        "resolution": None,
                        "clarity": None,
                        "colorspace": None,
                        "url": None,
                        "asset_file": None,
                        "asset_error": None,
                    }
                )
        elif isinstance(raw_textures, list):
            for texture in raw_textures:
                if not isinstance(texture, dict):
                    continue
                image = texture.get("image") or {}
                if not isinstance(image, dict):
                    image = {}
                textures.append(
                    {
                        "channel": texture.get("channel"),
                        "image_name": image.get("name"),
                        "source_file": image.get("source_file"),
                        "packed": image.get("packed"),
                        "resolution": image.get("resolution"),
                        "clarity": image.get("clarity"),
                        "colorspace": image.get("colorspace"),
                        "url": image.get("url"),
                        "asset_file": image.get("asset_file"),
                        "asset_error": image.get("asset_error"),
                    }
                )
        report.append(
            {
                "name": material.get("name"),
                "texture_count": len(textures),
                "textures": textures,
                "pbr_params": material.get("pbr_params") or material.get("pbr"),
                "alpha": material.get("alpha") or {"mode": material.get("alphaMode")},
                "displacement": material.get("displacement"),
                "unused_images": material.get("unused_images") or [],
                "raw": material if not textures else None,
            }
        )
    return report


def _report_texture_count(materials: list[dict[str, Any]]) -> int:
    count = 0
    for material in materials:
        if not isinstance(material, dict):
            continue
        textures = material.get("textures")
        if isinstance(textures, dict):
            count += len(textures)
        elif isinstance(textures, list):
            count += len(textures)
    return count


def _first_mesh_value(meshes: list[dict[str, Any]], key: str) -> Any:
    values = [mesh.get(key) for mesh in meshes if isinstance(mesh, dict) and mesh.get(key) is not None]
    if not values:
        return None
    return values[0] if len(values) == 1 else values


def _summary_source_meshes(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    blender = analysis.get("blender") if isinstance(analysis.get("blender"), dict) else {}
    blender_meshes = blender.get("meshes") if isinstance(blender.get("meshes"), list) else []
    if blender_meshes:
        return blender_meshes
    return analysis.get("meshes") if isinstance(analysis.get("meshes"), list) else []


def _mesh_number(mesh: dict[str, Any], key: str) -> int:
    try:
        return int(mesh.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _mesh_bool_any(meshes: list[dict[str, Any]], *keys: str) -> bool:
    return any(any(bool(mesh.get(key)) for key in keys) for mesh in meshes if isinstance(mesh, dict))


def _mesh_bool_all(meshes: list[dict[str, Any]], key: str) -> Optional[bool]:
    values = [bool(mesh.get(key)) for mesh in meshes if isinstance(mesh, dict) and mesh.get(key) is not None]
    if not values:
        return None
    return all(values)


def _bounds_value(meshes: list[dict[str, Any]], axis: str) -> Optional[float]:
    values = []
    for mesh in meshes:
        if not isinstance(mesh, dict):
            continue
        bounds = mesh.get("bounds") if isinstance(mesh.get("bounds"), dict) else None
        dimensions = mesh.get("dimensions") if isinstance(mesh.get("dimensions"), dict) else None
        value = (bounds or dimensions or {}).get(axis)
        if isinstance(value, (int, float)):
            values.append(float(value))
    if not values:
        return None
    return round(max(values), 4)


def _summary_parameters(analysis: dict[str, Any], computed: dict[str, Any]) -> dict[str, Any]:
    summary = analysis.get("summary") if isinstance(analysis.get("summary"), dict) else {}
    meshes = _summary_source_meshes(analysis)
    merged_meshes = analysis.get("meshes") if isinstance(analysis.get("meshes"), list) else []
    armatures = analysis.get("armatures") if isinstance(analysis.get("armatures"), list) else []
    animations = analysis.get("animations") if isinstance(analysis.get("animations"), list) else []
    faces = computed.get("faces")
    if faces is None:
        faces = summary.get("total_faces")
    if faces is None:
        faces = sum(_mesh_number(mesh, "faces") for mesh in merged_meshes or meshes)
    vertices = computed.get("vertices")
    if vertices is None:
        vertices = summary.get("total_vertices")
    if vertices is None:
        vertices = sum(_mesh_number(mesh, "vertices") for mesh in merged_meshes or meshes)
    armature_count = computed.get("armature_count") if computed.get("armature_count") is not None else len(armatures)
    animation_count = computed.get("animation_count") if computed.get("animation_count") is not None else len(animations)
    bone_count = computed.get("bone_count") if computed.get("bone_count") is not None else sum(_mesh_number(armature, "bones") for armature in armatures)
    textures = computed.get("has_texture_model")
    pbr = computed.get("has_pbr_model")
    return {
        "textures": bool(textures),
        "pbr": bool(pbr),
        "PBR_1": bool(computed.get("PBR_1")),
        "quad_mesh": _mesh_bool_all(meshes, "quad_mesh"),
        "low_poly": faces < 20000,
        "uv_export": _mesh_bool_any(meshes, "uv_export", "has_uv"),
        "armature": bool(armature_count),
        "armature_count": armature_count,
        "bone_count": bone_count,
        "animations": bool(animation_count),
        "animation_count": animation_count,
        "has_normals": _mesh_bool_any(meshes, "has_normals", "has_custom_normals"),
        "normals_valid": _mesh_bool_all(meshes, "normals_valid"),
        "vertices": vertices,
        "faces": faces,
        "bounds": {
            "x": _bounds_value(meshes, "x"),
            "y": _bounds_value(meshes, "y"),
            "z": _bounds_value(meshes, "z"),
        },
    }


def _build_summary(source_url: str, file_name: str, engine: str, analysis: dict[str, Any], standard: dict[str, Any], expert: dict[str, Any], finished_at: float) -> dict[str, Any]:
    summary = analysis.get("summary") if isinstance(analysis.get("summary"), dict) else {}
    meshes = analysis.get("meshes") if isinstance(analysis.get("meshes"), list) else []
    computed = expert.get("computed_metrics") or {}
    model_type_profile = expert.get("model_type_profile") or {}
    parameters = _summary_parameters(analysis, computed)
    return {
        "model": {
            "source_url": source_url,
            "file_name": file_name,
            "analysis_engine": engine,
            "asset_retention_seconds": TASK_RETENTION_SECONDS,
            "assets_expires_at": finished_at + TASK_RETENTION_SECONDS,
        },
        "parameters": parameters,
        "counts": {
            "mesh_count": computed.get("mesh_count") or summary.get("mesh_count"),
            "vertices": computed.get("vertices") or summary.get("total_vertices"),
            "faces": computed.get("faces") or summary.get("total_faces"),
            "triangles": computed.get("triangles") or summary.get("total_triangles"),
            "material_count": computed.get("material_count") or summary.get("material_count"),
            "texture_count": computed.get("texture_count"),
            "armature_count": computed.get("armature_count") or summary.get("armature_count"),
            "animation_count": computed.get("animation_count") or summary.get("animation_count"),
        },
        "quality": {
            "is_standard": standard.get("is_standard"),
            "label": standard.get("label"),
            "severity": standard.get("severity"),
            "reason_text": standard.get("reason_text"),
        },
        "professional": {
            "passed": expert.get("passed"),
            "level": expert.get("level"),
            "detected_types": model_type_profile.get("detected_types") or [],
        },
        "model_types": {
            "white_mesh_model": model_type_profile.get("white_mesh_model"),
            "rigged_model": model_type_profile.get("rigged_model"),
            "animated_model": model_type_profile.get("animated_model"),
            "textured_model": model_type_profile.get("textured_model"),
            "pbr_model": model_type_profile.get("pbr_model"),
            "multi_part_model": model_type_profile.get("multi_part_model"),
            "detected_types": model_type_profile.get("detected_types") or [],
        },
        "geometry_flags": {
            "has_uv": any(bool(mesh.get("has_uv")) for mesh in meshes if isinstance(mesh, dict)),
            "is_manifold": _first_mesh_value(meshes, "is_manifold"),
            "non_manifold_edge_count": computed.get("non_manifold_edge_count") or summary.get("non_manifold_edge_count"),
            "boundary_edge_count": computed.get("boundary_edge_count") or summary.get("boundary_edge_count"),
            "zero_area_faces": computed.get("zero_area_faces") or summary.get("zero_area_faces"),
            "degenerate_face_count": computed.get("degenerate_face_count"),
            "duplicate_triangle_count": computed.get("duplicate_triangle_count"),
            "self_intersection_count": computed.get("self_intersection_count") or summary.get("self_intersection_count"),
            "component_count": computed.get("component_count"),
            "bad_normal_alignment_vertices": computed.get("bad_normal_alignment_vertices"),
            "opposite_normal_vertices": computed.get("opposite_normal_vertices"),
            "uv_zero_area_faces": computed.get("uv_zero_area_faces"),
        },
        "material_flags": {
            "has_texture_model": computed.get("has_texture_model"),
            "has_pbr_model": computed.get("has_pbr_model"),
            "PBR_1": computed.get("PBR_1"),
            "pbr_channels": computed.get("pbr_channels"),
            "pbr_texture_suite": computed.get("pbr_texture_suite"),
            "pbr_param_channels": computed.get("pbr_param_channels") or [],
            "texture_channels": computed.get("texture_channels") or [],
            "texture_clarity_counts": computed.get("texture_clarity_counts") or {},
            "missing_image_count": computed.get("missing_image_count"),
            "unpacked_external_missing_count": computed.get("unpacked_external_missing_count"),
            "unused_image_count": computed.get("unused_image_count"),
            "alpha_material_count": computed.get("alpha_material_count"),
            "displacement_material_count": computed.get("displacement_material_count"),
        },
        "rig_animation_flags": {
            "has_rigged_model": computed.get("has_rigged_model"),
            "has_animation": computed.get("has_animation"),
            "armature_count": computed.get("armature_count") or summary.get("armature_count"),
            "bone_count": computed.get("bone_count"),
            "animation_count": computed.get("animation_count") or summary.get("animation_count"),
            "animation_frame_count": computed.get("animation_frame_count"),
            "weight_mesh_count": computed.get("weight_mesh_count"),
            "non_normalized_weight_vertices": computed.get("non_normalized_weight_vertices"),
            "zero_weight_vertices": computed.get("zero_weight_vertices"),
        },
    }


def _build_result(source_url: str, file_name: str, engine: str, analysis: dict[str, Any], standard: dict[str, Any], expert_result: dict[str, Any], finished_at: float) -> dict[str, Any]:
    expert = expert_result["expert_analysis"]
    meshes = analysis.get("meshes") or []
    materials = analysis.get("materials") or []
    geometry = _mesh_report(meshes)
    computed = expert.get("computed_metrics") or {}
    validation = {
        "geometry_matches_computed_metrics": geometry["vertices"] == computed.get("vertices") and geometry["faces"] == computed.get("faces") and geometry["triangles"] == computed.get("triangles"),
        "quality_metrics_match_geometry": standard.get("metrics", {}).get("faces") == geometry["faces"],
        "texture_count_matches_materials": _report_texture_count(materials) == computed.get("texture_count"),
        "analysis_engine": engine,
    }
    validation["passed"] = all(value is True for key, value in validation.items() if key != "analysis_engine")
    return {
        "summary": _build_summary(source_url, file_name, engine, analysis, standard, expert, finished_at),
        "quality": {
            "is_standard": standard.get("is_standard"),
            "label": standard.get("label"),
            "severity": standard.get("severity"),
            "rules": standard.get("rules") or [],
            "metrics": standard.get("metrics"),
            "reasons": standard.get("reasons") or [],
            "reason_text": standard.get("reason_text"),
        },
        "professional_analysis": {
            "passed": expert.get("passed"),
            "level": expert.get("level"),
            "conclusion": expert.get("conclusion"),
            "model_type_profile": expert.get("model_type_profile"),
            "structure_conclusion": expert.get("structure_conclusion"),
            "impact_analysis": expert.get("impact_analysis") or [],
            "issues": expert.get("issues") or [],
            "coverage_notes": expert.get("coverage_notes") or [],
        },
        "geometry": geometry,
        "materials": _material_report(materials),
        "validation": validation,
        "details": {
            "computed_metrics": computed,
            "texture_resolution_summary": expert.get("texture_resolution_summary") or [],
            "expert_skill": expert_result["skill"],
            "expert_standard": expert_result["expert_standard"],
            "raw_analysis": analysis,
        },
    }


async def _process_analysis_task(task_id: str, source_url: str, public_base_url: str) -> None:
    local_path = None
    await update_task(task_id, status="pending", message="任务已进入队列，等待分析资源")
    async with _job_semaphore:
        try:
            await update_task(task_id, status="running", started_at=now(), message="正在下载模型文件")
            local_path, file_name = await download_model(source_url)
            await update_task(task_id, message="模型下载完成，正在分析")
            task_asset_dir = ASSET_DIR / task_id
            engine, analysis_data = await run_model_analysis(local_path, task_asset_dir, task_id, public_base_url)
            finished_at = now()
            standard = quality_status_from_analysis(analysis_data)
            expert_result = analyze_with_3d_expert_skill(analysis_data, standard)
            result = _build_result(source_url, file_name, engine, analysis_data, standard, expert_result, finished_at)
            await update_task(
                task_id,
                status="succeeded",
                finished_at=finished_at,
                message="分析完成，下载缓存已删除",
                result=result,
            )
        except Exception as exc:
            await update_task(
                task_id,
                status="failed",
                finished_at=now(),
                message="分析失败，下载缓存已删除",
                error=_fallback_error(exc),
            )
        finally:
            if local_path:
                shutil.rmtree(local_path.parent / f"{local_path.stem}_files", ignore_errors=True)
                local_path.unlink(missing_ok=True)


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "model-analysis-api",
        "version": app.version,
        "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
    }


@app.post("/analyze", status_code=202)
async def submit_analysis(request: Request, payload: AnalyzeRequest):
    await cleanup_finished_tasks()
    source_url = str(payload.url)
    task_id = str(uuid.uuid4())
    public_base_url = PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    await create_task(task_id, source_url)
    asyncio.create_task(_process_analysis_task(task_id, source_url, public_base_url))
    return {
        "task_id": task_id,
        "status": "pending",
        "poll_url": f"/tasks/{task_id}",
        "message": "任务已提交，请轮询 poll_url 查询状态和结果",
    }


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    await cleanup_finished_tasks()
    task = await get_stored_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return task_public_view(task)
