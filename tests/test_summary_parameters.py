from __future__ import annotations

from model_analysis.api.app import _summary_parameters


def test_low_poly_uses_computed_faces_before_blender_meshes() -> None:
    analysis = {
        "summary": {"total_faces": 14283, "total_vertices": 16520},
        "meshes": [{"name": "native", "faces": 14283, "vertices": 16520}],
        "blender": {"meshes": [{"name": "blender", "faces": 40000, "vertices": 50000}]},
    }

    params = _summary_parameters(analysis, {"faces": 14283, "vertices": 16520})

    assert params["faces"] == 14283
    assert params["vertices"] == 16520
    assert params["low_poly"] is True


def test_low_poly_falls_back_to_summary_faces_before_blender_meshes() -> None:
    analysis = {
        "summary": {"total_faces": 14283, "total_vertices": 16520},
        "meshes": [{"name": "native", "faces": 14283, "vertices": 16520}],
        "blender": {"meshes": [{"name": "blender", "faces": 40000, "vertices": 50000}]},
    }

    params = _summary_parameters(analysis, {})

    assert params["faces"] == 14283
    assert params["vertices"] == 16520
    assert params["low_poly"] is True


def test_quad_mesh_true_when_quad_faces_are_majority() -> None:
    analysis = {
        "blender": {
            "meshes": [
                {"name": "mesh_a", "triangle_faces": 10, "quad_faces": 30, "quad_mesh": False},
                {"name": "mesh_b", "triangle_faces": 5, "quad_faces": 0, "quad_mesh": False},
            ]
        }
    }

    params = _summary_parameters(analysis, {"faces": 45, "vertices": 100})

    assert params["quad_mesh"] is True


def test_quad_mesh_false_when_triangle_faces_are_majority() -> None:
    analysis = {
        "blender": {
            "meshes": [
                {"name": "mesh_a", "triangle_faces": 30, "quad_faces": 10, "quad_mesh": False},
                {"name": "mesh_b", "triangle_faces": 5, "quad_faces": 5, "quad_mesh": True},
            ]
        }
    }

    params = _summary_parameters(analysis, {"faces": 50, "vertices": 100})

    assert params["quad_mesh"] is False
