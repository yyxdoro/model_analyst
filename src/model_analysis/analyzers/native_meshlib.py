#!/usr/bin/env python3
"""Standalone full-fidelity model analysis with native readers and MeshLib."""

from __future__ import annotations

import json
import math
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Vec2 = Tuple[float, float]
Vec3 = Tuple[float, float, float]
Face = Tuple[int, ...]
Tri = Tuple[int, int, int]

SUPPORTED_EXTS = {".fbx", ".usd", ".usda", ".usdc", ".usdz", ".glb", ".gltf", ".stl", ".obj"}


@dataclass
class NativeMeshData:
    name: str
    vertices: List[Vec3]
    faces: List[Face]
    source: str
    normals: List[Vec3] = field(default_factory=list)
    uvs: List[Vec2] = field(default_factory=list)
    tangents: List[Tuple[float, float, float, float]] = field(default_factory=list)
    joints: List[Tuple[int, ...]] = field(default_factory=list)
    weights: List[Tuple[float, ...]] = field(default_factory=list)
    material: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def _optional_import(module_name: str):
    try:
        return __import__(module_name, fromlist=["*"]), None
    except Exception as exc:
        return None, str(exc)


def _as_vec2(value: Sequence[Any]) -> Vec2:
    return (float(value[0]), float(value[1]))


def _as_vec3(value: Sequence[Any]) -> Vec3:
    return (float(value[0]), float(value[1]), float(value[2]))


def _triangulate_face(face: Sequence[int]) -> List[Tri]:
    if len(face) < 3:
        return []
    if len(face) == 3:
        return [(int(face[0]), int(face[1]), int(face[2]))]
    root = int(face[0])
    return [(root, int(face[i]), int(face[i + 1])) for i in range(1, len(face) - 1)]


def _triangulate_faces(faces: Iterable[Sequence[int]]) -> List[Tri]:
    tris: List[Tri] = []
    for face in faces:
        tris.extend(_triangulate_face(face))
    return tris


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(float(x) * float(x) for x in v))


def _unit(v: Vec3) -> Vec3:
    n = _norm(v)
    return (0.0, 0.0, 0.0) if n <= 1e-12 else (v[0] / n, v[1] / n, v[2] / n)


def _triangle_area(a: Vec3, b: Vec3, c: Vec3) -> float:
    return 0.5 * _norm(_cross(_sub(b, a), _sub(c, a)))


def _uv_area(a: Vec2, b: Vec2, c: Vec2) -> float:
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) * 0.5


def _bounds(vertices: Sequence[Vec3]) -> Dict[str, Any]:
    if not vertices:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0], "dimensions": {"x": 0.0, "y": 0.0, "z": 0.0}}
    mins = [min(v[i] for v in vertices) for i in range(3)]
    maxs = [max(v[i] for v in vertices) for i in range(3)]
    dims = [maxs[i] - mins[i] for i in range(3)]
    return {"min": [round(x, 6) for x in mins], "max": [round(x, 6) for x in maxs], "dimensions": {"x": round(dims[0], 6), "y": round(dims[1], 6), "z": round(dims[2], 6)}}


def _edge_stats(triangles: Sequence[Tri]) -> Dict[str, Any]:
    edge_faces: Dict[Tuple[int, int], int] = {}
    for tri in triangles:
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = (a, b) if a <= b else (b, a)
            edge_faces[key] = edge_faces.get(key, 0) + 1
    boundary = sum(1 for count in edge_faces.values() if count == 1)
    loose = sum(1 for count in edge_faces.values() if count == 0)
    non_manifold = sum(1 for count in edge_faces.values() if count > 2)
    return {"edge_count": len(edge_faces), "boundary_edge_count": int(boundary), "loose_edge_count": int(loose), "non_manifold_edge_count": int(non_manifold), "is_manifold": non_manifold == 0 and boundary == 0}


def _duplicate_triangle_count(triangles: Sequence[Tri]) -> int:
    seen = set()
    duplicates = 0
    for tri in triangles:
        key = tuple(sorted(tri))
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    return duplicates


def _component_count(triangles: Sequence[Tri]) -> int:
    parent: Dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b, c in triangles:
        union(a, b)
        union(b, c)
    return len({find(v) for v in parent}) if parent else 0


def _pure_geometry_checks(vertices: Sequence[Vec3], faces: Sequence[Face]) -> Dict[str, Any]:
    triangles = _triangulate_faces(faces)
    triangle_faces = sum(1 for face in faces if len(face) == 3)
    quad_faces = sum(1 for face in faces if len(face) == 4)
    invalid_faces = 0
    degenerate_faces = 0
    for face in faces:
        if len(face) < 3 or len(set(face)) < 3:
            invalid_faces += 1
            degenerate_faces += 1
            continue
        face_tris = _triangulate_face(face)
        if not face_tris:
            invalid_faces += 1
            continue
        if all(_triangle_area(vertices[a], vertices[b], vertices[c]) <= 1e-12 for a, b, c in face_tris):
            degenerate_faces += 1
    stats = _edge_stats(triangles)
    stats.update({"source_face_count": len(faces), "triangles": len(triangles), "triangle_faces": int(triangle_faces), "quad_faces": int(quad_faces), "invalid_face_count": int(invalid_faces), "zero_area_faces": int(degenerate_faces), "duplicate_triangle_count": int(_duplicate_triangle_count(triangles)), "component_count_python": int(_component_count(triangles))})
    return stats


def _normal_checks(mesh: NativeMeshData) -> Dict[str, Any]:
    if not mesh.normals:
        return {"has_normals": False}
    triangles = _triangulate_faces(mesh.faces)
    zero = sum(1 for n in mesh.normals if _norm(n) < 1e-8)
    lengths = [_norm(n) for n in mesh.normals if _norm(n) >= 1e-8]
    accum: List[Vec3] = [(0.0, 0.0, 0.0) for _ in mesh.vertices]
    face_inconsistent = 0
    for tri in triangles:
        a, b, c = tri
        fn = _cross(_sub(mesh.vertices[b], mesh.vertices[a]), _sub(mesh.vertices[c], mesh.vertices[a]))
        fu = _unit(fn)
        if _norm(fu) < 1e-8:
            continue
        dots = [_dot(_unit(mesh.normals[v]), fu) for v in tri if v < len(mesh.normals) and _norm(mesh.normals[v]) >= 1e-8]
        if dots and sum(dots) / len(dots) < -0.5:
            face_inconsistent += 1
        for v in tri:
            if v < len(accum):
                old = accum[v]
                accum[v] = (old[0] + fn[0], old[1] + fn[1], old[2] + fn[2])
    alignments = []
    opposite = 0
    bad = 0
    for i, n in enumerate(mesh.normals[: len(mesh.vertices)]):
        nu = _unit(n)
        au = _unit(accum[i])
        if _norm(nu) < 1e-8 or _norm(au) < 1e-8:
            continue
        d = _dot(nu, au)
        alignments.append(d)
        if d < 0:
            opposite += 1
        if d < 0.5:
            bad += 1
    return {"has_normals": True, "normal_count": len(mesh.normals), "zero_normals": int(zero), "normal_length_min": round(min(lengths), 6) if lengths else 0.0, "normal_length_max": round(max(lengths), 6) if lengths else 0.0, "checked_vertices": len(alignments), "opposite_vertices": int(opposite), "bad_alignment_vertices_dot_lt_0_5": int(bad), "face_inconsistent_with_vertex_normals": int(face_inconsistent), "avg_normal_alignment_dot": round(sum(alignments) / len(alignments), 6) if alignments else None}


def _uv_checks(mesh: NativeMeshData) -> Dict[str, Any]:
    if not mesh.uvs:
        return {"has_uv": False, "uv_count": 0}
    triangles = _triangulate_faces(mesh.faces)
    zero_uv_faces = 0
    stretch_values = []
    for a, b, c in triangles:
        if max(a, b, c) >= len(mesh.uvs):
            continue
        area3d = _triangle_area(mesh.vertices[a], mesh.vertices[b], mesh.vertices[c])
        area_uv = _uv_area(mesh.uvs[a], mesh.uvs[b], mesh.uvs[c])
        if area_uv <= 1e-12:
            zero_uv_faces += 1
        elif area3d > 1e-12:
            stretch_values.append(area3d / area_uv)
    us = [uv[0] for uv in mesh.uvs]
    vs = [uv[1] for uv in mesh.uvs]
    return {"has_uv": True, "uv_count": len(mesh.uvs), "uv_bounds": {"min": [round(min(us), 6), round(min(vs), 6)], "max": [round(max(us), 6), round(max(vs), 6)]}, "zero_uv_area_faces": int(zero_uv_faces), "uv_stretch_ratio_min": round(min(stretch_values), 6) if stretch_values else None, "uv_stretch_ratio_max": round(max(stretch_values), 6) if stretch_values else None}


def _weight_checks(mesh: NativeMeshData) -> Dict[str, Any]:
    if not mesh.weights and not mesh.joints:
        return {"has_skin_weights": False}
    orphan = 0
    non_normalized = 0
    for weights in mesh.weights:
        total = sum(float(w) for w in weights)
        if total <= 1e-8:
            orphan += 1
        if abs(total - 1.0) > 1e-3:
            non_normalized += 1
    return {"has_skin_weights": bool(mesh.weights), "joint_count_records": len(mesh.joints), "weight_count_records": len(mesh.weights), "zero_weight_vertices": int(orphan), "non_normalized_weight_vertices": int(non_normalized)}


def _read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _gltf_component_format(component_type: int) -> str:
    mapping = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
    if component_type not in mapping:
        raise RuntimeError(f"不支持的 componentType: {component_type}")
    return mapping[component_type]


def _load_glb_native(file_path: str) -> Tuple[List[NativeMeshData], Dict[str, Any]]:
    with open(file_path, "rb") as f:
        data = f.read()
    if data[:4] != b"glTF":
        raise RuntimeError("不是有效的 GLB 文件")
    version = _read_u32(data, 4)
    if version != 2:
        raise RuntimeError(f"不支持的 GLB 版本: {version}")
    offset = 12
    json_chunk = None
    bin_chunk = None
    while offset + 8 <= len(data):
        chunk_len = _read_u32(data, offset)
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + chunk_len]
        if chunk_type == b"JSON":
            json_chunk = chunk_data.rstrip(b" \t\r\n\x00").decode("utf-8")
        elif chunk_type == b"BIN\x00":
            bin_chunk = chunk_data
        offset += 8 + _align4(chunk_len)
    if not json_chunk:
        raise RuntimeError("GLB 中缺少 JSON chunk")
    doc = json.loads(json_chunk)
    if (doc.get("buffers") or []) and bin_chunk is None:
        raise RuntimeError("GLB 中缺少 BIN chunk")

    buffer_views = doc.get("bufferViews", []) or []
    accessors = doc.get("accessors", []) or []
    materials = doc.get("materials", []) or []
    images = doc.get("images", []) or []
    textures = doc.get("textures", []) or []

    def accessor_data(index: int):
        acc = accessors[index]
        view = buffer_views[acc["bufferView"]]
        if view.get("buffer", 0) != 0:
            raise RuntimeError("当前实现只支持单 buffer GLB")
        start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        count = int(acc["count"])
        item_size = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}.get(acc["type"])
        if not item_size:
            raise RuntimeError(f"不支持的 accessor 类型: {acc['type']}")
        fmt = "<" + _gltf_component_format(int(acc["componentType"])) * item_size
        stride = int(view.get("byteStride", 0)) or struct.calcsize(fmt)
        out = []
        for i in range(count):
            values = struct.unpack(fmt, bin_chunk[start + i * stride : start + i * stride + struct.calcsize(fmt)])
            out.append(values[0] if item_size == 1 else values)
        return out

    def material_info(index: Optional[int]) -> Optional[Dict[str, Any]]:
        if index is None or index < 0 or index >= len(materials):
            return None
        mat = materials[index]
        pbr = mat.get("pbrMetallicRoughness", {}) or {}
        tex_refs = {}
        for key, value in pbr.items():
            if key.endswith("Texture") and isinstance(value, dict):
                tex_refs[key] = value.get("index")
        for key in ("normalTexture", "occlusionTexture", "emissiveTexture"):
            if isinstance(mat.get(key), dict):
                tex_refs[key] = mat[key].get("index")
        resolved = {}
        for channel, tex_index in tex_refs.items():
            if isinstance(tex_index, int) and 0 <= tex_index < len(textures):
                source = textures[tex_index].get("source")
                img = images[source] if isinstance(source, int) and 0 <= source < len(images) else {}
                resolved[channel] = {"texture_index": tex_index, "image": img.get("name") or img.get("uri") or f"image_{source}"}
        return {"name": mat.get("name") or f"material_{index}", "pbr": {"baseColorFactor": pbr.get("baseColorFactor"), "metallicFactor": pbr.get("metallicFactor"), "roughnessFactor": pbr.get("roughnessFactor")}, "textures": resolved, "alphaMode": mat.get("alphaMode"), "doubleSided": mat.get("doubleSided", False)}

    meshes: List[NativeMeshData] = []
    for mesh_index, mesh_def in enumerate(doc.get("meshes", []) or []):
        for prim_index, prim in enumerate(mesh_def.get("primitives", []) or []):
            attrs = prim.get("attributes", {}) or {}
            if "POSITION" not in attrs:
                continue
            vertices = [_as_vec3(v) for v in accessor_data(int(attrs["POSITION"]))]
            if "indices" in prim:
                indices = [int(i) for i in accessor_data(int(prim["indices"]))]
                faces = [tuple(indices[i : i + 3]) for i in range(0, len(indices) - 2, 3)]
            else:
                faces = [(i, i + 1, i + 2) for i in range(0, len(vertices) - 2, 3)]
            meshes.append(NativeMeshData(name=mesh_def.get("name") or f"mesh_{mesh_index}_{prim_index}", vertices=vertices, faces=faces, normals=[_as_vec3(v) for v in accessor_data(int(attrs["NORMAL"]))] if "NORMAL" in attrs else [], uvs=[_as_vec2(v) for v in accessor_data(int(attrs["TEXCOORD_0"]))] if "TEXCOORD_0" in attrs else [], tangents=[tuple(float(x) for x in v[:4]) for v in accessor_data(int(attrs["TANGENT"]))] if "TANGENT" in attrs else [], joints=[tuple(int(x) for x in v) if isinstance(v, tuple) else (int(v),) for v in accessor_data(int(attrs["JOINTS_0"]))] if "JOINTS_0" in attrs else [], weights=[tuple(float(x) for x in v) if isinstance(v, tuple) else (float(v),) for v in accessor_data(int(attrs["WEIGHTS_0"]))] if "WEIGHTS_0" in attrs else [], material=material_info(prim.get("material")), source="glb-native", metadata={"mesh_index": mesh_index, "primitive_index": prim_index, "mode": prim.get("mode", 4)}))
    return meshes, {"reader": "glb-native", "version": version, "mesh_count": len(doc.get("meshes", []) or []), "material_count": len(materials), "image_count": len(images)}


def _load_trimesh_native(file_path: str) -> Tuple[List[NativeMeshData], Dict[str, Any]]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".glb":
        return _load_glb_native(file_path)
    trimesh, err = _optional_import("trimesh")
    if trimesh is None:
        raise RuntimeError(f"trimesh 未安装，无法原生读取 GLB/STL/OBJ: {err}")
    kwargs = {"process": False, "maintain_order": True}
    try:
        loaded = trimesh.load(file_path, force=None, skip_materials=True, **kwargs)
    except TypeError:
        loaded = trimesh.load(file_path, force=None, **kwargs)
    meshes: List[NativeMeshData] = []
    geometries = loaded.geometry.items() if hasattr(loaded, "geometry") else [(os.path.basename(file_path), loaded)]
    for name, geom in geometries:
        meshes.append(NativeMeshData(name=str(name), vertices=[_as_vec3(v) for v in getattr(geom, "vertices", [])], faces=[tuple(int(i) for i in face) for face in getattr(geom, "faces", [])], normals=[_as_vec3(v) for v in getattr(geom, "vertex_normals", [])] if getattr(geom, "vertex_normals", None) is not None else [], source="trimesh-native", metadata={"original_type": type(geom).__name__}))
    return meshes, {"reader": "trimesh", "process": False, "maintain_order": True}


def _load_usd_native(file_path: str) -> Tuple[List[NativeMeshData], Dict[str, Any]]:
    try:
        from pxr import Usd, UsdGeom  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"OpenUSD(pxr) 未安装，无法原生读取 USD/USDZ/USDC: {exc}") from exc
    stage = Usd.Stage.Open(file_path)
    if stage is None:
        raise RuntimeError("OpenUSD 无法打开文件")
    meshes: List[NativeMeshData] = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        usd_mesh = UsdGeom.Mesh(prim)
        points = usd_mesh.GetPointsAttr().Get() or []
        counts = list(usd_mesh.GetFaceVertexCountsAttr().Get() or [])
        indices = list(usd_mesh.GetFaceVertexIndicesAttr().Get() or [])
        faces: List[Face] = []
        cursor = 0
        for count in counts:
            count = int(count)
            faces.append(tuple(int(i) for i in indices[cursor : cursor + count]))
            cursor += count
        normals_attr = usd_mesh.GetNormalsAttr().Get() or []
        normals = [_as_vec3(n) for n in normals_attr] if len(normals_attr) == len(points) else []
        meshes.append(NativeMeshData(name=prim.GetPath().pathString, vertices=[_as_vec3(p) for p in points], faces=faces, normals=normals, source="openusd-native", metadata={"orientation": str(usd_mesh.GetOrientationAttr().Get()), "subdivision_scheme": str(usd_mesh.GetSubdivisionSchemeAttr().Get())}))
    return meshes, {"reader": "OpenUSD", "stage_root": str(stage.GetPseudoRoot().GetPath())}


def _load_fbx_native(file_path: str) -> Tuple[List[NativeMeshData], Dict[str, Any]]:
    try:
        import fbx  # type: ignore
        import FbxCommon  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"FBX SDK Python 未安装，无法原生读取 FBX: {exc}") from exc
    manager, scene = FbxCommon.InitializeSdkObjects()
    ok = FbxCommon.LoadScene(manager, scene, file_path)
    if not ok:
        raise RuntimeError("FBX SDK 无法打开文件")
    meshes: List[NativeMeshData] = []

    def visit(node):
        attr = node.GetNodeAttribute() if node else None
        if attr and attr.GetAttributeType() == fbx.FbxNodeAttribute.eMesh:
            fbx_mesh = node.GetMesh()
            control_points = fbx_mesh.GetControlPoints()
            faces: List[Face] = []
            for poly_idx in range(fbx_mesh.GetPolygonCount()):
                faces.append(tuple(int(fbx_mesh.GetPolygonVertex(poly_idx, j)) for j in range(fbx_mesh.GetPolygonSize(poly_idx))))
            meshes.append(NativeMeshData(name=node.GetName() or f"fbx_mesh_{len(meshes)}", vertices=[_as_vec3(control_points[i]) for i in range(fbx_mesh.GetControlPointsCount())], faces=faces, source="fbx-sdk-native", metadata={"polygon_count": fbx_mesh.GetPolygonCount()}))
        for i in range(node.GetChildCount() if node else 0):
            visit(node.GetChild(i))

    visit(scene.GetRootNode())
    manager.Destroy()
    return meshes, {"reader": "FBX SDK"}


def load_native_meshes(file_path: str) -> Tuple[List[NativeMeshData], Dict[str, Any]]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_EXTS:
        raise RuntimeError(f"不支持的格式: {ext}")
    if ext == ".fbx":
        return _load_fbx_native(file_path)
    if ext in {".usd", ".usda", ".usdc", ".usdz"}:
        return _load_usd_native(file_path)
    return _load_trimesh_native(file_path)


class MeshLibAnalyzer:
    def __init__(self) -> None:
        self.mr = None
        self.import_error = None
        self.module_name = None
        for module_name in ("meshlib.mrmeshpy", "mrmeshpy"):
            module, err = _optional_import(module_name)
            if module is not None:
                self.mr = module
                self.module_name = module_name
                break
            self.import_error = err

    @property
    def available(self) -> bool:
        return self.mr is not None

    def status(self) -> Dict[str, Any]:
        return {"available": self.available, "module": self.module_name, "import_error": self.import_error}

    def analyze(self, mesh_data: NativeMeshData) -> Dict[str, Any]:
        if not self.available:
            return {"available": False, "error": self.import_error}
        triangles = _triangulate_faces(mesh_data.faces)
        if not triangles:
            return {"available": True, "error": "没有可送入 MeshLib 的三角面"}
        try:
            mesh = self._build_mesh(mesh_data.vertices, triangles)
        except Exception as exc:
            return {"available": True, "error": f"MeshLib 内存建模失败: {exc}"}
        result: Dict[str, Any] = {"available": True, "module": self.module_name}
        result.update(self._call_optional_checks(mesh))
        return result

    def _build_mesh(self, vertices: Sequence[Vec3], triangles: Sequence[Tri]):
        mr = self.mr
        points = mr.VertCoords()
        points.resize(len(vertices))
        for i, (x, y, z) in enumerate(vertices):
            points[mr.VertId(i)] = mr.Vector3f(float(x), float(y), float(z))
        triangulation = mr.Triangulation()
        for a, b, c in triangles:
            triangulation.push_back(mr.ThreeVertIds([mr.VertId(a), mr.VertId(b), mr.VertId(c)]))
        topology = mr.MeshBuilder.fromTriangles(triangulation) if hasattr(mr, "MeshBuilder") else mr.MeshTopology()
        mesh = mr.Mesh()
        mesh.points = points
        mesh.topology = topology
        return mesh

    def _count_bitset(self, value: Any) -> Optional[int]:
        for name in ("count", "size"):
            method = getattr(value, name, None)
            if callable(method):
                try:
                    return int(method())
                except Exception:
                    pass
        try:
            return int(len(value))
        except Exception:
            return None

    def _call_optional_checks(self, mesh) -> Dict[str, Any]:
        mr = self.mr
        checks: Dict[str, Any] = {}
        for output_key, func_name in {"hole_count": "findHoleRepresentiveEdges", "component_count": "getAllComponents", "self_intersection_count": "findSelfCollidingTriangles"}.items():
            func = getattr(mr, func_name, None)
            if callable(func):
                try:
                    checks[output_key] = self._count_bitset(func(mesh))
                except Exception as exc:
                    checks[f"{output_key}_error"] = str(exc)
        degenerate_func = getattr(mr, "findDegenerateFaces", None)
        if callable(degenerate_func):
            try:
                settings_cls = getattr(mr, "FindDegenerateFacesSettings", None)
                value = degenerate_func(mesh, settings_cls()) if settings_cls else degenerate_func(mesh)
                checks["meshlib_degenerate_face_count"] = self._count_bitset(value)
            except Exception as exc:
                checks["meshlib_degenerate_face_error"] = str(exc)
        volume_func = getattr(mr, "volume", None)
        if callable(volume_func):
            try:
                checks["signed_volume"] = float(volume_func(mesh.topology, mesh.points))
            except Exception as exc:
                checks["signed_volume_error"] = str(exc)
        return checks


def _material_report(meshes: Sequence[NativeMeshData]) -> List[Dict[str, Any]]:
    seen = {}
    for mesh in meshes:
        if mesh.material:
            seen[json.dumps(mesh.material, sort_keys=True, ensure_ascii=False)] = mesh.material
    return list(seen.values())


def analyze_white_model(file_path: str) -> Dict[str, Any]:
    file_path = os.path.abspath(file_path)
    meshes, reader_info = load_native_meshes(file_path)
    meshlib = MeshLibAnalyzer()
    analyzed_meshes: List[Dict[str, Any]] = []
    for mesh in meshes:
        bounds = _bounds(mesh.vertices)
        pure_checks = _pure_geometry_checks(mesh.vertices, mesh.faces)
        normal_checks = _normal_checks(mesh)
        uv_checks = _uv_checks(mesh)
        weight_checks = _weight_checks(mesh)
        meshlib_checks = meshlib.analyze(mesh)
        analyzed_meshes.append({"name": mesh.name, "source_reader": mesh.source, "vertices": len(mesh.vertices), "faces": len(mesh.faces), "triangles": pure_checks["triangles"], "triangle_faces": pure_checks["triangle_faces"], "quad_faces": pure_checks["quad_faces"], "quad_mesh": pure_checks["quad_faces"] > pure_checks["triangle_faces"], "dimensions": bounds["dimensions"], "aabb": {"min": bounds["min"], "max": bounds["max"]}, "has_uv": uv_checks["has_uv"], "has_custom_normals": normal_checks["has_normals"], "has_tangents": bool(mesh.tangents), "mikk_tspace": {"has_tangents": bool(mesh.tangents), "tangent_count": len(mesh.tangents)}, "zero_area_faces": pure_checks["zero_area_faces"], "invalid_face_count": pure_checks["invalid_face_count"], "is_manifold": pure_checks["is_manifold"], "non_manifold_edge_count": pure_checks["non_manifold_edge_count"], "boundary_edge_count": pure_checks["boundary_edge_count"], "loose_edge_count": pure_checks["loose_edge_count"], "edge_count": pure_checks["edge_count"], "duplicate_triangle_count": pure_checks["duplicate_triangle_count"], "component_count_python": pure_checks["component_count_python"], "normals": normal_checks, "uv": uv_checks, "weights": weight_checks, "material": mesh.material, "metadata": mesh.metadata, "meshlib": meshlib_checks})
    summary = {"mesh_count": len(analyzed_meshes), "material_count": len(_material_report(meshes)), "armature_count": 0, "animation_count": 0, "total_vertices": sum(m["vertices"] for m in analyzed_meshes), "total_faces": sum(m["faces"] for m in analyzed_meshes), "total_triangles": sum(m["triangles"] for m in analyzed_meshes), "total_triangle_faces": sum(m["triangle_faces"] for m in analyzed_meshes), "total_quad_faces": sum(m["quad_faces"] for m in analyzed_meshes), "zero_area_faces": sum(m["zero_area_faces"] for m in analyzed_meshes), "non_manifold_edge_count": sum(m["non_manifold_edge_count"] for m in analyzed_meshes), "boundary_edge_count": sum(m["boundary_edge_count"] for m in analyzed_meshes), "self_intersection_count": sum((m.get("meshlib", {}).get("self_intersection_count") or 0) for m in analyzed_meshes), "meshlib_available": meshlib.available, "no_format_conversion": True}
    return {"analyzer": "native_meshlib_full_fidelity", "no_format_conversion": True, "file": {"path": file_path, "name": os.path.basename(file_path), "ext": os.path.splitext(file_path)[1].lower()}, "native_reader": reader_info, "meshlib": meshlib.status(), "summary": summary, "meshes": analyzed_meshes, "materials": _material_report(meshes), "armatures": [], "animations": [], "dependencies": dependency_status()}


def dependency_status() -> Dict[str, Any]:
    status = {}
    for label, module in {"meshlib": "meshlib.mrmeshpy", "trimesh": "trimesh", "openusd": "pxr", "fbx_sdk": "fbx"}.items():
        imported, err = _optional_import(module)
        status[label] = {"available": imported is not None, "module": module, "error": err}
    return status


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print("Error: Missing input file path", file=sys.stderr)
        return 2
    try:
        report = analyze_white_model(args[0])
    except Exception as exc:
        print(f"---ERROR---{exc}")
        return 1
    print("---RESULT_START---")
    print(json.dumps(report, indent=4, ensure_ascii=False))
    print("---RESULT_END---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
