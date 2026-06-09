from __future__ import annotations

import time
from typing import Any

from model_analysis.core.config import QUALITY_RULES


def _primary_analysis(analysis_data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(analysis_data, dict) and isinstance(analysis_data.get("files"), list) and analysis_data["files"]:
        first = analysis_data["files"][0]
        if isinstance(first, dict) and isinstance(first.get("analysis"), dict):
            return first["analysis"]
    return analysis_data or {}


def quality_status_from_analysis(analysis_data: dict[str, Any]) -> dict[str, Any]:
    data = _primary_analysis(analysis_data)
    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    meshes = data.get("meshes", []) if isinstance(data, dict) else []

    faces = int(summary.get("total_faces") or sum(int(m.get("faces") or 0) for m in meshes if isinstance(m, dict)))
    non_manifold = int(summary.get("non_manifold_edge_count") or sum(int(m.get("non_manifold_edge_count") or 0) for m in meshes if isinstance(m, dict)))
    zero_area = int(summary.get("zero_area_faces") or sum(int(m.get("zero_area_faces") or 0) for m in meshes if isinstance(m, dict)))

    reasons = []
    severity = "green"

    if faces > 2_000_000:
        reasons.append(f"面数超过 2,000,000（当前 {faces}）")
        severity = "red"
    elif faces > 100_000:
        reasons.append(f"面数超过 100,000（当前 {faces}）")
        severity = "yellow"

    if non_manifold > 0:
        reasons.append(f"非流形边 {non_manifold}")
        if non_manifold > 100:
            severity = "red"
        elif severity != "red":
            severity = "yellow"

    if zero_area > 0:
        reasons.append(f"零面积面 {zero_area}")
        severity = "red"

    return {
        "is_standard": severity == "green",
        "label": "标准" if severity == "green" else "不标准",
        "severity": severity,
        "rules": QUALITY_RULES,
        "metrics": {
            "faces": faces,
            "non_manifold_edge_count": non_manifold,
            "zero_area_faces": zero_area,
        },
        "reasons": reasons,
        "reason_text": "；".join(reasons) if reasons else "未命中异常规则",
    }
