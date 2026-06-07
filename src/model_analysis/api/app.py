from __future__ import annotations

import asyncio
import shutil
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from model_analysis.api.schemas import AnalyzeRequest
from model_analysis.core.config import ASSET_DIR, ASSET_ROUTE, MAX_CONCURRENT_JOBS, TASK_RETENTION_SECONDS
from model_analysis.expert.skill import analyze_with_3d_expert_skill
from model_analysis.services.analysis_runner import run_model_analysis
from model_analysis.services.downloader import download_model
from model_analysis.services.quality import quality_status_from_analysis
from model_analysis.services.task_store import (
    cleanup_finished_tasks,
    create_task,
    get_task as get_stored_task,
    now,
    task_public_view,
    update_task,
)

app = FastAPI(title="Model Analysis API", version="1.1.0")
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


def _build_report(source_url: str, file_name: str, engine: str, analysis: dict[str, Any], standard: dict[str, Any], expert: dict[str, Any]) -> dict[str, Any]:
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
        "model": {
            "source_url": source_url,
            "file_name": file_name,
            "analysis_engine": engine,
        },
        "geometry": geometry,
        "materials": _material_report(materials),
        "quality": {
            "is_standard": standard.get("is_standard"),
            "label": standard.get("label"),
            "severity": standard.get("severity"),
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
        "validation": validation,
    }


async def _process_analysis_task(task_id: str, source_url: str) -> None:
    local_path = None
    await update_task(task_id, status="pending", message="任务已进入队列，等待分析资源")
    async with _job_semaphore:
        try:
            await update_task(task_id, status="running", started_at=now(), message="正在下载模型文件")
            local_path, file_name = await download_model(source_url)
            await update_task(task_id, message="模型下载完成，正在分析")
            task_asset_dir = ASSET_DIR / task_id
            engine, analysis_data = await run_model_analysis(local_path, task_asset_dir, task_id)
            finished_at = now()
            standard = quality_status_from_analysis(analysis_data)
            expert_result = analyze_with_3d_expert_skill(analysis_data, standard)
            expert_analysis = expert_result["expert_analysis"]
            report = _build_report(source_url, file_name, engine, analysis_data, standard, expert_analysis)
            result = {
                "standard": standard,
                "expert_skill": expert_result["skill"],
                "expert_standard": expert_result["expert_standard"],
                "expert_analysis": expert_analysis,
                "report": report,
                "result": {
                    "source_url": source_url,
                    "file_name": file_name,
                    "analysis_engine": engine,
                    "asset_retention_seconds": TASK_RETENTION_SECONDS,
                    "assets_expires_at": finished_at + TASK_RETENTION_SECONDS,
                    "analysis": analysis_data,
                },
            }
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
async def submit_analysis(request: AnalyzeRequest):
    await cleanup_finished_tasks()
    source_url = str(request.url)
    task_id = str(uuid.uuid4())
    await create_task(task_id, source_url)
    asyncio.create_task(_process_analysis_task(task_id, source_url))
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
