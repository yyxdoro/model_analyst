from __future__ import annotations

from typing import Any


EXPERT_SKILL = {
    "name": "professional_3d_modeling_expert",
    "role": "专业3D建模与网格几何质检专家",
    "version": "1.1.0",
    "source": "docs/metrics.md + rig/material/pbr/part production standards",
    "capabilities": [
        "基础网格/白模质量判断",
        "绑骨模型判断",
        "贴图模型判断",
        "PBR材质模型判断",
        "分part/多mesh模型判断",
    ],
    "metric_groups": [
        {
            "name": "topology_validity",
            "title": "拓扑与网格合法性指标",
            "purpose": "判断模型是否为有效可用网格，是上线、仿真、渲染和后续布尔/切片处理的基础门槛。",
            "metrics": [
                {"name": "manifold_mesh", "label": "流形网格", "standard": "合格模型应无非流形边、无非流形顶点；每条边最多被2个三角面共享。", "severity": "critical", "analysis_fields": ["is_manifold", "non_manifold_edge_count"]},
                {"name": "degenerate_face", "label": "退化面", "standard": "合格模型退化面/零面积面数量应为0。", "severity": "critical", "analysis_fields": ["zero_area_faces", "meshlib_degenerate_face_count"]},
                {"name": "hole_boundary", "label": "孔洞与边界边", "standard": "实体封闭模型边界边应为0；开放面片允许边界边，但需要语义上构成完整外轮廓。", "severity": "major", "analysis_fields": ["boundary_edge_count", "loose_edge_count"]},
                {"name": "duplicate_elements", "label": "重复元素", "standard": "合格模型不应存在重复三角面或重复顶点。", "severity": "major", "analysis_fields": ["duplicate_triangle_count"]},
                {"name": "normal_consistency", "label": "法向一致性", "standard": "面法向和顶点法向应整体方向统一，不应出现大面积反转或明显朝向混乱。", "severity": "major", "analysis_fields": ["inward_normal_ratio", "normals.opposite_vertices", "normals.bad_alignment_vertices_dot_lt_0_5"]},
            ],
        },
        {
            "name": "mesh_quality",
            "title": "网格质量指标",
            "purpose": "评估三角面形态和分布均匀度，影响重拓扑、简化、仿真计算和渲染稳定性。",
            "metrics": [
                {"name": "face_vertex_count", "label": "面数与顶点数", "standard": "面数≤100,000为常规可控；100,000~2,000,000为偏重需优化；>2,000,000为高风险重模型。", "severity": "major", "analysis_fields": ["faces", "triangles", "vertices"]},
                {"name": "triangle_shape", "label": "三角面形态", "standard": "工业通用建议长宽比≤5优秀、≤10合格、>10劣质；内角建议保持在15°~150°。当前分析结果如未提供该项，应标记为未检测。", "severity": "moderate", "analysis_fields": ["aspect_ratio", "angle"]},
                {"name": "uv_quality", "label": "UV质量", "standard": "有材质贴图的模型应具备UV；UV零面积面越少越好，UV坐标范围应合理。", "severity": "moderate", "analysis_fields": ["has_uv", "uv.zero_uv_area_faces", "uv.uv_bounds"]},
                {"name": "mesh_components", "label": "连通组件", "standard": "单体模型通常应保持较少连通组件；组件数量异常增多说明存在碎片或未合并部件。", "severity": "moderate", "analysis_fields": ["component_count_python"]},
            ],
        },
        {
            "name": "rigging_animation",
            "title": "绑骨与动画指标",
            "purpose": "判断模型是否为绑骨模型，以及骨骼/动画数据是否具备可交付基础。",
            "metrics": [
                {"name": "armature_presence", "label": "骨架存在性", "standard": "绑骨模型应包含至少1套 Armature/Skeleton，骨骼数量应大于0。", "severity": "major", "analysis_fields": ["armatures", "armature_count", "bones"]},
                {"name": "animation_presence", "label": "动画轨道", "standard": "动画模型应包含 action/clip，且帧长大于0；静态绑骨模型可无动画但需明确交付类型。", "severity": "moderate", "analysis_fields": ["animations", "animation_count", "frames"]},
                {"name": "skin_weight", "label": "蒙皮权重", "standard": "变形角色模型应具备权重数据，权重应归一化且无孤立零权重点。当前 Blender 结果主要识别骨架和动画，native 结果可补充 weights。", "severity": "moderate", "analysis_fields": ["weights.has_skin_weights", "weights.non_normalized_weight_vertices", "weights.zero_weight_vertices"]},
            ],
        },
        {
            "name": "materials_textures_pbr",
            "title": "贴图与PBR材质指标",
            "purpose": "判断模型是否为贴图/PBR模型，以及贴图通道、清晰度、PBR参数和材质节点是否完整。",
            "metrics": [
                {"name": "texture_presence", "label": "贴图存在性", "standard": "贴图模型应至少包含 Base Color/Albedo 或等价颜色贴图，并能追踪到有效图像资源。", "severity": "major", "analysis_fields": ["materials.textures", "textures.channel", "image.exists", "image.packed"]},
                {"name": "pbr_channel_completeness", "label": "PBR通道完整性", "standard": "标准PBR建议包含 Base Color、Normal、Roughness，金属材质应包含 Metallic；可按业务选择 AO/Alpha/Displacement。", "severity": "major", "analysis_fields": ["Base Color", "Normal", "Roughness", "Metallic", "Alpha", "Displacement"]},
                {"name": "texture_resolution", "label": "贴图清晰度", "standard": "主贴图建议≥1K，展示资产建议2K，特写/高精资产可4K；低于1K需提示清晰度风险。", "severity": "moderate", "analysis_fields": ["image.resolution", "image.clarity"]},
                {"name": "unused_texture", "label": "未使用贴图", "standard": "材质节点中不应残留无用图片节点，避免包体冗余和误导审核。", "severity": "notice", "analysis_fields": ["materials.unused_images"]},
            ],
        },
        {
            "name": "part_structure",
            "title": "分part与结构组织指标",
            "purpose": "判断模型是否为多part/多mesh结构，并评估命名、组件数量和碎片风险。",
            "metrics": [
                {"name": "multi_mesh_parts", "label": "多mesh/多part", "standard": "分part模型允许多个 mesh，但应按语义拆分、命名清晰；非语义碎片会影响编辑、绑定和渲染管理。", "severity": "moderate", "analysis_fields": ["summary.mesh_count", "meshes.name", "component_count_python"]},
                {"name": "part_fragmentation", "label": "碎片化风险", "standard": "组件数量明显大于mesh数量时，通常说明存在碎片、断裂或未合并部件，需要人工确认。", "severity": "moderate", "analysis_fields": ["mesh_count", "component_count"]},
            ],
        },
        {
            "name": "geometry_similarity",
            "title": "几何相似度指标",
            "purpose": "有GT标准模型时，用于量化重建、扫描配准、网格修复、简化前后的几何误差。",
            "metrics": [
                {"name": "hausdorff_distance", "label": "双向Hausdorff距离", "standard": "衡量整体最大偏差；对离群点敏感。需单位统一并做刚体配准后才有判断意义。当前单模型URL分析无GT，默认不计算。", "severity": "reference", "analysis_fields": ["gt.hausdorff_distance"]},
                {"name": "mean_percentile_distance", "label": "平均距离与分位距离", "standard": "工程评测建议同时关注平均距离、95分位距离和最大距离。当前单模型URL分析无GT，默认不计算。", "severity": "reference", "analysis_fields": ["gt.mean_distance", "gt.percentile_95_distance"]},
                {"name": "normal_volume_surface_deviation", "label": "法向/体积/表面积偏差", "standard": "法向误差<5°通常可视为优秀；体积和表面积偏差需与GT对比。当前单模型URL分析无GT，默认不计算。", "severity": "reference", "analysis_fields": ["gt.normal_error", "gt.volume_deviation", "gt.surface_area_deviation"]},
            ],
        },
        {
            "name": "efficiency",
            "title": "网格轻量化与效率指标",
            "purpose": "用于评估模型体量、压缩简化收益和渲染/传输效率。",
            "metrics": [
                {"name": "mesh_density", "label": "网格密度", "standard": "单位空间内面/顶点数量应与模型细节匹配；局部过密会增加渲染和处理成本。", "severity": "moderate", "analysis_fields": ["dimensions", "faces", "vertices"]},
                {"name": "compression_ratio", "label": "压缩率", "standard": "压缩率=(原始面数-简化后面数)/原始面数×100%；当前单模型分析无简化前后对比，默认不计算。", "severity": "reference", "analysis_fields": ["comparison.compression_ratio"]},
            ],
        },
    ],
}


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> Any:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dimensions_volume(dimensions: dict[str, Any]) -> float | None:
    x = _to_float(dimensions.get("x"))
    y = _to_float(dimensions.get("y"))
    z = _to_float(dimensions.get("z"))
    if x is None or y is None or z is None:
        return None
    volume = x * y * z
    return volume if volume > 0 else None


def _collect_meshes(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    meshes = analysis.get("meshes")
    if isinstance(meshes, list):
        return [m for m in meshes if isinstance(m, dict)]
    return []


def _collect_materials(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    materials = analysis.get("materials")
    if isinstance(materials, list):
        return [m for m in materials if isinstance(m, dict)]
    return []


def _channel_key(channel: Any) -> str:
    key = str(channel or "").replace("Texture", "").lower().replace(" ", "_").replace("-", "_")
    return {
        "basecolor": "base_color",
        "metallicroughness": "metallic_roughness",
        "normal": "normal",
        "occlusion": "occlusion",
        "emissive": "emissive",
    }.get(key, key)


def _material_metrics(materials: list[dict[str, Any]]) -> dict[str, Any]:
    texture_count = 0
    channels = set()
    clarity_counts: dict[str, int] = {}
    texture_resolutions = []
    missing_images = 0
    unpacked_external_missing = 0
    unused_images = 0
    alpha_materials = 0
    displacement_materials = 0
    pbr_param_names = set()

    for material in materials:
        raw_textures = material.get("textures")
        if isinstance(raw_textures, dict):
            textures = [{"channel": _texture_channel_name, "image": {"name": (texture or {}).get("image") if isinstance(texture, dict) else None}} for _texture_channel_name, texture in raw_textures.items()]
        else:
            textures = raw_textures if isinstance(raw_textures, list) else []
        texture_count += len(textures)
        unused_images += len(material.get("unused_images") or [])
        if (material.get("alpha") or {}).get("used") or material.get("alphaMode"):
            alpha_materials += 1
        if isinstance(material.get("displacement"), dict) and material.get("displacement", {}).get("used"):
            displacement_materials += 1
        pbr_param_names.update(_channel_key(k) for k in (material.get("pbr_params") or material.get("pbr") or {}).keys())

        for texture in textures:
            channel = _channel_key(texture.get("channel"))
            if channel:
                channels.add(channel)
            image = texture.get("image") if isinstance(texture.get("image"), dict) else {}
            clarity = image.get("clarity") or "Unknown"
            clarity_counts[clarity] = clarity_counts.get(clarity, 0) + 1
            resolution = image.get("resolution") if isinstance(image.get("resolution"), list) else [0, 0]
            width = _to_int(resolution[0]) if len(resolution) > 0 else 0
            height = _to_int(resolution[1]) if len(resolution) > 1 else 0
            texture_resolutions.append({
                "material": material.get("name"),
                "channel": texture.get("channel"),
                "image": image.get("name"),
                "resolution": [width, height],
                "clarity": clarity,
                "url": image.get("url"),
                "asset_file": image.get("asset_file"),
                "asset_error": image.get("asset_error"),
            })
            missing_source = bool(image.get("source_file")) and not image.get("exists") and not image.get("packed") and not image.get("asset_file")
            missing_pixels = width <= 0 or height <= 0 or bool(image.get("asset_error"))
            if image and (missing_source or missing_pixels):
                missing_images += 1
                if missing_source:
                    unpacked_external_missing += 1

    has_base_color = any(c in channels for c in {"base_color", "basecolor", "base_colour", "color", "diffuse"})
    has_normal = any("normal" in c for c in channels)
    has_roughness_texture = any("roughness" in c for c in channels)
    has_metallic_texture = any("metallic" in c or "metalness" in c for c in channels)
    legacy_has_roughness = has_roughness_texture or "roughness" in pbr_param_names
    legacy_has_metallic = has_metallic_texture or "metallic" in pbr_param_names
    legacy_has_pbr = has_base_color or has_normal or legacy_has_roughness or legacy_has_metallic or bool(pbr_param_names)
    pbr_suite_missing = [name for name, exists in (
        ("base_color", has_base_color),
        ("normal", has_normal),
        ("roughness", has_roughness_texture),
    ) if not exists]
    has_pbr = not pbr_suite_missing

    texture_resolutions.sort(key=lambda item: (-(item["resolution"][0] * item["resolution"][1]), str(item.get("channel") or ""), str(item.get("image") or "")))

    return {
        "material_count": len(materials),
        "texture_count": texture_count,
        "texture_channels": sorted(channels),
        "texture_clarity_counts": clarity_counts,
        "texture_resolution_summary": texture_resolutions,
        "missing_image_count": missing_images,
        "unpacked_external_missing_count": unpacked_external_missing,
        "unused_image_count": unused_images,
        "alpha_material_count": alpha_materials,
        "displacement_material_count": displacement_materials,
        "has_texture_model": texture_count > 0,
        "has_pbr_model": has_pbr,
        "PBR_1": legacy_has_pbr,
        "pbr_channels": {
            "base_color": has_base_color,
            "normal": has_normal,
            "roughness": has_roughness_texture,
            "metallic": has_metallic_texture,
        },
        "pbr_texture_suite": {
            "complete": has_pbr,
            "required_channels": ["base_color", "normal", "roughness"],
            "optional_channels": ["metallic"],
            "missing_channels": pbr_suite_missing,
        },
        "pbr_param_channels": sorted(pbr_param_names),
    }


def _rig_metrics(analysis: dict[str, Any], meshes: list[dict[str, Any]]) -> dict[str, Any]:
    armatures = analysis.get("armatures") if isinstance(analysis.get("armatures"), list) else []
    animations = analysis.get("animations") if isinstance(analysis.get("animations"), list) else []
    bone_count = sum(_to_int(a.get("bones")) for a in armatures if isinstance(a, dict))
    animation_frame_count = sum(_to_int(a.get("frames")) for a in animations if isinstance(a, dict))
    weight_meshes = sum(1 for m in meshes if bool((m.get("weights") or {}).get("has_skin_weights")))
    non_normalized_weights = sum(_to_int((m.get("weights") or {}).get("non_normalized_weight_vertices")) for m in meshes)
    zero_weight_vertices = sum(_to_int((m.get("weights") or {}).get("zero_weight_vertices")) for m in meshes)
    return {
        "armature_count": len(armatures),
        "bone_count": bone_count,
        "animation_count": len(animations),
        "animation_frame_count": animation_frame_count,
        "weight_mesh_count": weight_meshes,
        "non_normalized_weight_vertices": non_normalized_weights,
        "zero_weight_vertices": zero_weight_vertices,
        "has_rigged_model": len(armatures) > 0 or bone_count > 0 or weight_meshes > 0,
        "has_animation": len(animations) > 0,
    }


def _summary_metrics(analysis: dict[str, Any], meshes: list[dict[str, Any]]) -> dict[str, Any]:
    summary = analysis.get("summary") if isinstance(analysis.get("summary"), dict) else {}
    faces = _to_int(summary.get("total_faces") or sum(_to_int(m.get("faces")) for m in meshes))
    triangles = _to_int(summary.get("total_triangles") or sum(_to_int(m.get("triangles")) for m in meshes))
    vertices = _to_int(summary.get("total_vertices") or sum(_to_int(m.get("vertices")) for m in meshes))
    non_manifold = _to_int(summary.get("non_manifold_edge_count") or sum(_to_int(m.get("non_manifold_edge_count")) for m in meshes))
    boundary = _to_int(summary.get("boundary_edge_count") or sum(_to_int(m.get("boundary_edge_count")) for m in meshes))
    zero_area = _to_int(summary.get("zero_area_faces") or sum(_to_int(m.get("zero_area_faces")) for m in meshes))
    duplicate_triangles = sum(_to_int(m.get("duplicate_triangle_count")) for m in meshes)
    components = sum(_to_int(m.get("component_count_python")) for m in meshes)
    loose_edges = sum(_to_int(m.get("loose_edge_count")) for m in meshes)
    self_intersections = _to_int(summary.get("self_intersection_count") or sum(_to_int((m.get("meshlib") or {}).get("self_intersection_count")) for m in meshes))
    degenerate_faces = sum(_to_int((m.get("meshlib") or {}).get("meshlib_degenerate_face_count")) for m in meshes)
    bad_normals = sum(_to_int((m.get("normals") or {}).get("bad_alignment_vertices_dot_lt_0_5")) for m in meshes)
    opposite_normals = sum(_to_int((m.get("normals") or {}).get("opposite_vertices")) for m in meshes)
    uv_zero_faces = sum(_to_int((m.get("uv") or {}).get("zero_uv_area_faces")) for m in meshes)
    has_uv_meshes = sum(1 for m in meshes if bool(m.get("has_uv")))
    mesh_names = [str(m.get("name") or "") for m in meshes]

    volumes = [_dimensions_volume(m.get("dimensions") or {}) for m in meshes]
    total_aabb_volume = sum(v for v in volumes if v is not None)
    density_faces_per_unit = round(faces / total_aabb_volume, 4) if total_aabb_volume > 0 else None

    metrics = {
        "mesh_count": len(meshes),
        "mesh_names": mesh_names,
        "faces": faces,
        "triangles": triangles,
        "vertices": vertices,
        "non_manifold_edge_count": non_manifold,
        "boundary_edge_count": boundary,
        "loose_edge_count": loose_edges,
        "zero_area_faces": zero_area,
        "degenerate_face_count": degenerate_faces,
        "duplicate_triangle_count": duplicate_triangles,
        "component_count": components,
        "self_intersection_count": self_intersections,
        "bad_normal_alignment_vertices": bad_normals,
        "opposite_normal_vertices": opposite_normals,
        "uv_zero_area_faces": uv_zero_faces,
        "uv_mesh_count": has_uv_meshes,
        "density_faces_per_aabb_unit": density_faces_per_unit,
        "has_multi_part_model": len(meshes) > 1,
    }
    metrics.update(_material_metrics(_collect_materials(analysis)))
    metrics.update(_rig_metrics(analysis, meshes))
    return metrics


def _level_rank(level: str) -> int:
    return {"pass": 0, "notice": 1, "warning": 2, "fail": 3}.get(level, 0)


def _issue(metric: str, level: str, title: str, evidence: dict[str, Any], recommendation: str) -> dict[str, Any]:
    return {"metric": metric, "level": level, "title": title, "evidence": evidence, "recommendation": recommendation}


def _evaluate(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    if metrics["non_manifold_edge_count"] > 0:
        issues.append(_issue("manifold_mesh", "fail" if metrics["non_manifold_edge_count"] > 100 else "warning", "存在非流形边，模型拓扑不满足严格准入标准", {"non_manifold_edge_count": metrics["non_manifold_edge_count"]}, "建议定位非流形边并执行拓扑修复，确保每条边最多被两个面共享。"))

    zero_or_degenerate = metrics["zero_area_faces"] + metrics["degenerate_face_count"]
    if zero_or_degenerate > 0:
        issues.append(_issue("degenerate_face", "fail", "存在零面积面或退化面，可能导致法向、体积和布尔计算异常", {"zero_area_faces": metrics["zero_area_faces"], "degenerate_face_count": metrics["degenerate_face_count"]}, "建议删除或重建退化三角面，合并重合点并重新三角化局部区域。"))

    if metrics["boundary_edge_count"] > 0:
        issues.append(_issue("hole_boundary", "warning", "存在边界边，若目标是封闭实体则说明模型有孔洞或开放边界", {"boundary_edge_count": metrics["boundary_edge_count"], "loose_edge_count": metrics["loose_edge_count"]}, "若模型应为实体，请补洞并闭合边界；若本身是开放面片，请确认边界轮廓连续且符合设计语义。"))

    if metrics["duplicate_triangle_count"] > 0:
        issues.append(_issue("duplicate_elements", "warning", "存在重复三角面，增加无效面数并可能造成渲染闪烁", {"duplicate_triangle_count": metrics["duplicate_triangle_count"]}, "建议去除重复面和重合元素，减少冗余拓扑。"))

    normal_problem_count = metrics["bad_normal_alignment_vertices"] + metrics["opposite_normal_vertices"]
    if normal_problem_count > 0:
        issues.append(_issue("normal_consistency", "warning", "法向一致性存在风险，可能出现光照发黑或表面显示异常", {"bad_normal_alignment_vertices": metrics["bad_normal_alignment_vertices"], "opposite_normal_vertices": metrics["opposite_normal_vertices"]}, "建议统一法向朝向并重新计算顶点/面法向，必要时检查局部反面。"))

    if metrics["faces"] > 2_000_000:
        issues.append(_issue("face_vertex_count", "fail", "面数超过 200 万，属于高风险重模型", {"faces": metrics["faces"], "vertices": metrics["vertices"]}, "建议进行重拓扑或分级LOD，优先保留轮廓和高曲率区域细节。"))
    elif metrics["faces"] > 100_000:
        issues.append(_issue("face_vertex_count", "warning", "面数超过十万，渲染和传输成本偏高", {"faces": metrics["faces"], "vertices": metrics["vertices"]}, "建议评估目标平台预算，必要时做减面、合批或LOD。"))

    if metrics["has_texture_model"] and metrics["uv_mesh_count"] == 0:
        issues.append(_issue("uv_quality", "warning", "贴图模型未检测到UV，纹理映射不可控", {"texture_count": metrics["texture_count"], "uv_mesh_count": metrics["uv_mesh_count"]}, "建议为所有使用贴图的网格展开UV，并检查UV重叠、拉伸和零面积UV面。"))
    elif metrics["mesh_count"] > 0 and metrics["uv_mesh_count"] == 0:
        issues.append(_issue("uv_quality", "notice", "未检测到UV，若模型需要贴图材质会影响纹理映射", {"mesh_count": metrics["mesh_count"], "uv_mesh_count": metrics["uv_mesh_count"]}, "若该模型需要PBR或贴图表现，请展开UV并检查UV重叠、拉伸和零面积UV面。"))
    elif metrics["uv_zero_area_faces"] > 0:
        issues.append(_issue("uv_quality", "warning", "存在零面积UV面，可能导致贴图采样异常", {"uv_zero_area_faces": metrics["uv_zero_area_faces"]}, "建议清理异常UV岛并重新展开受影响区域。"))

    if metrics["has_texture_model"] and metrics["missing_image_count"] > 0:
        issues.append(_issue("texture_presence", "warning", "存在外链贴图缺失，材质可能无法完整还原", {"missing_image_count": metrics["missing_image_count"]}, "建议打包贴图或修复贴图路径，确保交付文件可独立加载。"))

    if metrics["has_texture_model"]:
        clarity_counts = metrics.get("texture_clarity_counts") or {}
        if _to_int(clarity_counts.get("Low")) > 0:
            issues.append(_issue("texture_resolution", "notice", "存在低清晰度贴图，近景展示可能发糊", {"texture_clarity_counts": clarity_counts}, "建议主视觉贴图至少1K，展示资产优先2K，特写资产按需4K。"))
        if metrics["unused_image_count"] > 0:
            issues.append(_issue("unused_texture", "notice", "存在未使用贴图节点，可能造成包体冗余", {"unused_image_count": metrics["unused_image_count"]}, "建议清理未连接或未被材质使用的图片节点。"))

    if metrics["PBR_1"]:
        pbr = metrics["pbr_channels"]
        missing = [name for name in ("base_color", "normal", "roughness") if not pbr.get(name)]
        if missing:
            issues.append(_issue("pbr_channel_completeness", "notice", "PBR核心通道不完整，材质物理一致性需要确认", {"missing_channels": missing, "pbr_channels": pbr}, "标准PBR建议至少具备 Base Color、Normal、Roughness；金属材质补充 Metallic。"))

    if metrics["has_rigged_model"]:
        if metrics["bone_count"] <= 0:
            issues.append(_issue("armature_presence", "warning", "检测到绑骨迹象但骨骼数量为0", {"armature_count": metrics["armature_count"], "bone_count": metrics["bone_count"]}, "建议检查骨架导出是否完整，确认骨骼层级和命名。"))
        if metrics["non_normalized_weight_vertices"] > 0 or metrics["zero_weight_vertices"] > 0:
            issues.append(_issue("skin_weight", "warning", "蒙皮权重存在异常，可能导致动画变形破面", {"non_normalized_weight_vertices": metrics["non_normalized_weight_vertices"], "zero_weight_vertices": metrics["zero_weight_vertices"]}, "建议归一化权重并修复零权重点，确认每个变形顶点有有效骨骼影响。"))
        if not metrics["has_animation"]:
            issues.append(_issue("animation_presence", "notice", "模型包含骨架但未检测到动画轨道", {"armature_count": metrics["armature_count"], "animation_count": metrics["animation_count"]}, "若交付目标是静态绑定模型可接受；若是动画模型，需要补充动作剪辑并确认帧长。"))

    if metrics["has_multi_part_model"]:
        issues.append(_issue("multi_mesh_parts", "notice", "检测到多mesh/多part结构", {"mesh_count": metrics["mesh_count"], "mesh_names": metrics["mesh_names"][:20]}, "请确认拆分是否符合语义；建议保持部件命名清晰，避免无意义碎片。"))
    if metrics["component_count"] > metrics["mesh_count"] and metrics["component_count"] > 1:
        issues.append(_issue("part_fragmentation", "notice", "连通组件数量偏多，可能存在碎片或未合并部件", {"mesh_count": metrics["mesh_count"], "component_count": metrics["component_count"]}, "建议检查是否有游离碎片；若是单体模型，应合并或删除无意义组件。"))

    if metrics["self_intersection_count"] > 0:
        issues.append(_issue("self_intersection", "fail", "检测到自相交，可能影响3D打印、布尔和物理仿真", {"self_intersection_count": metrics["self_intersection_count"]}, "建议使用自相交检测定位交叉三角面，并重建局部拓扑。"))

    return issues


def _model_type_profile(metrics: dict[str, Any]) -> dict[str, Any]:
    detected = []
    profile = {
        "white_mesh_model": metrics["mesh_count"] > 0 and not metrics["has_texture_model"] and not metrics["has_rigged_model"],
        "rigged_model": metrics["has_rigged_model"],
        "animated_model": metrics["has_animation"],
        "textured_model": metrics["has_texture_model"],
        "pbr_model": metrics["has_pbr_model"],
        "multi_part_model": metrics["has_multi_part_model"],
    }
    labels = {
        "white_mesh_model": "白模/基础网格模型",
        "rigged_model": "绑骨模型",
        "animated_model": "动画模型",
        "textured_model": "贴图模型",
        "pbr_model": "PBR材质模型",
        "multi_part_model": "分part/多mesh模型",
    }
    for key, enabled in profile.items():
        if enabled:
            detected.append(labels[key])
    profile["detected_types"] = detected or ["未识别到有效模型类型"]
    return profile


def _coverage_notes(metrics: dict[str, Any]) -> list[str]:
    notes = ["当前为单模型URL分析，几何相似度类指标需要GT标准模型和刚体配准后才能计算。"]
    if metrics["density_faces_per_aabb_unit"] is None:
        notes.append("模型尺寸或包围盒体积不足，未计算单位包围盒网格密度。")
    if not metrics["has_texture_model"]:
        notes.append("未检测到贴图节点，因此贴图清晰度和PBR贴图完整性按无贴图模型处理。")
    if not metrics["has_rigged_model"]:
        notes.append("未检测到骨架或蒙皮权重，因此绑骨/动画指标按非绑骨模型处理。")
    notes.append("长宽比、三角内角、二面角等网格质量细项当前分析结果未直接提供，已在专业标准中列为后续扩展检测项。")
    return notes


def _texture_resolution_text(metrics: dict[str, Any]) -> str:
    textures = metrics.get("texture_resolution_summary") or []
    if not textures:
        return "未检测到材质贴图图片引用。"
    valid = [t for t in textures if (t.get("resolution") or [0, 0])[0] > 0 and (t.get("resolution") or [0, 0])[1] > 0]
    invalid = len(textures) - len(valid)
    if not valid:
        return f"检测到 {len(textures)} 个贴图通道，但图片数据未成功加载或分辨率为 0，材质交付不完整。"
    top = valid[:6]
    detail = "；".join(f"{t.get('channel') or 'Unknown'} {t['resolution'][0]}×{t['resolution'][1]}" for t in top)
    suffix = f"；另有 {invalid} 个贴图未成功加载" if invalid else ""
    return f"检测到 {len(textures)} 个贴图通道，最高分辨率 {valid[0]['resolution'][0]}×{valid[0]['resolution'][1]}；{detail}{suffix}。"


def _structure_conclusion(metrics: dict[str, Any]) -> str:
    parts = []
    faces = metrics["faces"]
    if faces <= 100_000:
        parts.append(f"面数 {faces:,}，体量较轻，适合实时预览、Web/移动端展示和常规编辑。")
    elif faces <= 2_000_000:
        parts.append(f"面数 {faces:,}，属于中高复杂度模型，实时渲染和传输成本需要评估。")
    else:
        parts.append(f"面数 {faces:,}，属于高风险重模型，建议先做减面或LOD。")

    if metrics["non_manifold_edge_count"] > 0:
        parts.append(f"存在 {metrics['non_manifold_edge_count']:,} 条非流形边，会影响布尔、细分、碰撞体生成和3D打印切片。")
    if metrics["boundary_edge_count"] > 0:
        parts.append(f"存在 {metrics['boundary_edge_count']:,} 条开口边，模型不是严格封闭实体；若用于打印、仿真或体积计算，需要先补洞闭合。")
    if metrics["zero_area_faces"] + metrics["degenerate_face_count"] > 0:
        parts.append(f"存在 {metrics['zero_area_faces'] + metrics['degenerate_face_count']:,} 个零面积/退化面，可能造成法线异常、渲染闪烁或局部计算失败。")
    if metrics["component_count"] > max(metrics["mesh_count"], 1):
        parts.append(f"连通组件 {metrics['component_count']:,} 个，高于 mesh 数 {metrics['mesh_count']:,}，可能有碎片化或未合并部件。")
    if metrics["has_texture_model"] and metrics["uv_mesh_count"] == 0:
        parts.append("检测到贴图但未检测到UV，贴图映射不可控，PBR材质无法稳定还原。")
    parts.append(_texture_resolution_text(metrics))
    return " ".join(parts)


def _impact_analysis(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    impacts = []
    topology_level = "pass"
    topology_notes = []
    if metrics["non_manifold_edge_count"] > 0:
        topology_level = "fail" if metrics["non_manifold_edge_count"] > 100 else "warning"
        topology_notes.append("非流形边会导致布尔、细分、切片和碰撞体生成不稳定")
    if metrics["boundary_edge_count"] > 0:
        if topology_level == "pass":
            topology_level = "warning"
        topology_notes.append("开口边说明模型不是封闭体，影响打印、体积、物理仿真和实体检测")
    if metrics["zero_area_faces"] + metrics["degenerate_face_count"] > 0:
        topology_level = "fail"
        topology_notes.append("退化面会造成法向、阴影、三角化和网格修复异常")
    impacts.append({
        "area": "topology_structure",
        "title": "拓扑结构影响",
        "level": topology_level,
        "impact": "；".join(topology_notes) if topology_notes else "未发现非流形、退化面等关键拓扑阻断项，结构可进入常规渲染/预览流程。",
        "evidence": {"non_manifold_edge_count": metrics["non_manifold_edge_count"], "boundary_edge_count": metrics["boundary_edge_count"], "zero_or_degenerate_faces": metrics["zero_area_faces"] + metrics["degenerate_face_count"]},
    })

    render_level = "pass" if metrics["faces"] <= 100_000 else "warning" if metrics["faces"] <= 2_000_000 else "fail"
    impacts.append({
        "area": "render_performance",
        "title": "渲染与传输影响",
        "level": render_level,
        "impact": "面数较轻，适合实时预览和在线展示。" if render_level == "pass" else "面数偏高，会增加加载、传输、渲染和移动端功耗成本。",
        "evidence": {"faces": metrics["faces"], "vertices": metrics["vertices"], "density_faces_per_aabb_unit": metrics["density_faces_per_aabb_unit"]},
    })

    material_level = "pass"
    if metrics["has_texture_model"] and metrics["missing_image_count"] > 0:
        material_level = "warning"
    elif not metrics["has_texture_model"]:
        material_level = "notice"
    impacts.append({
        "area": "material_texture_delivery",
        "title": "材质贴图影响",
        "level": material_level,
        "impact": _texture_resolution_text(metrics),
        "evidence": {"material_count": metrics["material_count"], "texture_count": metrics["texture_count"], "texture_channels": metrics["texture_channels"], "missing_image_count": metrics["missing_image_count"]},
    })

    if metrics["has_rigged_model"]:
        rig_level = "notice" if not metrics["has_animation"] else "pass"
        impacts.append({
            "area": "rig_animation",
            "title": "绑定与动画影响",
            "level": rig_level,
            "impact": "检测到骨架但未检测到动画轨道；可作为静态绑定模型交付，若目标是动画资产需补充动作剪辑。" if not metrics["has_animation"] else "检测到骨架和动画数据，可继续检查权重归一化与动作范围。",
            "evidence": {"armature_count": metrics["armature_count"], "bone_count": metrics["bone_count"], "animation_count": metrics["animation_count"]},
        })
    return impacts


def analyze_with_3d_expert_skill(analysis_data: dict[str, Any], standard: dict[str, Any]) -> dict[str, Any]:
    analysis = analysis_data or {}
    meshes = _collect_meshes(analysis)
    metrics = _summary_metrics(analysis, meshes)
    issues = _evaluate(metrics)
    worst_level = max((issue["level"] for issue in issues), key=_level_rank, default="pass")
    passed = not any(issue["level"] in {"fail", "warning"} for issue in issues)
    model_type_profile = _model_type_profile(metrics)

    impact_analysis = _impact_analysis(metrics)
    structure_conclusion = _structure_conclusion(metrics)

    if passed:
        conclusion = f"模型通过当前可计算的专业3D网格准入检查；识别类型：{'、'.join(model_type_profile['detected_types'])}。{structure_conclusion}"
    else:
        top_titles = "；".join(issue["title"] for issue in sorted(issues, key=lambda i: _level_rank(i["level"]), reverse=True)[:3])
        conclusion = f"模型未完全满足专业3D质量标准；识别类型：{'、'.join(model_type_profile['detected_types'])}；主要问题为：{top_titles}。{structure_conclusion}"

    return {
        "skill": EXPERT_SKILL,
        "expert_standard": {
            "baseline": "以拓扑合法性为准入门槛，以贴图/PBR/绑骨/分part结构判断资产交付完整度，以网格质量和效率指标判断可优化程度；几何相似度指标需GT模型参与。",
            "pass_condition": "无非流形边、无退化/零面积面、无严重自相交；贴图/PBR模型应具备有效UV和核心通道；绑骨模型应具备有效骨架/权重；分part模型应按语义拆分且无碎片化风险。",
            "metric_groups": EXPERT_SKILL["metric_groups"],
        },
        "expert_analysis": {
            "passed": passed and bool(standard.get("is_standard", True)),
            "level": worst_level,
            "conclusion": conclusion,
            "model_type_profile": model_type_profile,
            "computed_metrics": metrics,
            "texture_resolution_summary": metrics.get("texture_resolution_summary") or [],
            "structure_conclusion": structure_conclusion,
            "impact_analysis": impact_analysis,
            "issues": issues,
            "coverage_notes": _coverage_notes(metrics),
        },
    }
