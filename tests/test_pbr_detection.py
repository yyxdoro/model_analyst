from __future__ import annotations

from model_analysis.expert.skill import analyze_with_3d_expert_skill


def _analyze_material(material: dict) -> dict:
    result = analyze_with_3d_expert_skill(
        {
            "summary": {"total_faces": 1, "total_triangles": 1, "total_vertices": 3},
            "meshes": [{"name": "mesh", "faces": 1, "triangles": 1, "vertices": 3, "has_uv": True}],
            "materials": [material],
        },
        {"is_standard": True},
    )
    return result["expert_analysis"]


def test_base_color_texture_with_pbr_params_is_only_legacy_pbr() -> None:
    expert = _analyze_material(
        {
            "name": "mat",
            "textures": [{"channel": "Base Color", "image": {"name": "color", "resolution": [2048, 2048]}}],
            "pbr_params": {"Metallic": 0.0, "Roughness": 0.9},
        }
    )

    metrics = expert["computed_metrics"]
    assert metrics["has_pbr_model"] is False
    assert metrics["PBR_1"] is True
    assert metrics["pbr_texture_suite"]["missing_channels"] == ["normal", "roughness"]
    assert any(issue["metric"] == "pbr_channel_completeness" for issue in expert["issues"])


def test_core_pbr_texture_suite_sets_pbr_model() -> None:
    expert = _analyze_material(
        {
            "name": "mat",
            "textures": [
                {"channel": "Base Color", "image": {"name": "color", "resolution": [2048, 2048]}},
                {"channel": "Normal", "image": {"name": "normal", "resolution": [2048, 2048]}},
                {"channel": "Roughness", "image": {"name": "roughness", "resolution": [2048, 2048]}},
            ],
            "pbr_params": {},
        }
    )

    metrics = expert["computed_metrics"]
    assert metrics["has_pbr_model"] is True
    assert metrics["PBR_1"] is True
    assert metrics["pbr_texture_suite"]["missing_channels"] == []
    assert expert["model_type_profile"]["pbr_model"] is True
