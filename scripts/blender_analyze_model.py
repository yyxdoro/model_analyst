import bpy
import bmesh
import json
import sys
import os
import random
import re
import shutil
from pathlib import Path
from typing import Optional

def clean_scene():
    """清空场景中所有默认对象和残留数据"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for data in [bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.armatures, bpy.data.actions]:
        for item in data:
            data.remove(item)

def import_model(filepath):
    """根据文件后缀名自动选择导入器"""
    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext in ['.glb', '.gltf']:
            bpy.ops.import_scene.gltf(filepath=filepath)
        elif ext == '.fbx':
            bpy.ops.import_scene.fbx(filepath=filepath)
        elif ext == '.obj':
            bpy.ops.import_scene.obj(filepath=filepath)
        elif ext == '.dae':
            bpy.ops.wm.collada_import(filepath=filepath)
        else:
            return False, f"不支持的格式: {ext}"
        return True, "Success"
    except Exception as e:
        return False, str(e)

def find_image_node(node):
    """递归查找连接到该节点的图像纹理节点"""
    if node is None:
        return None
    if node.type == 'TEX_IMAGE':
        return node
    # 遍历所有输入插槽，寻找来源链接
    for input in node.inputs:
        if input.is_linked:
            for link in input.links:
                found = find_image_node(link.from_node)
                if found:
                    return found
    return None

def _clarity_from_size(size):
    try:
        m = max(size[0], size[1])
    except Exception:
        return "Unknown"
    if m >= 4096:
        return "4K"
    if m >= 2048:
        return "2K"
    if m >= 1024:
        return "1K"
    return "Low"


def _safe_asset_name(value):
    name = re.sub(r"[^0-9A-Za-z._-]+", "_", value or "texture").strip("._")
    return name or "texture"


def _image_extension(img, abspath):
    ext = Path(abspath).suffix.lower() if abspath else ""
    if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".tga", ".webp"}:
        return ext
    file_format = str(getattr(img, "file_format", "") or "").upper()
    mapping = {"JPEG": ".jpg", "PNG": ".png", "TIFF": ".tif", "TARGA": ".tga", "BMP": ".bmp", "WEBP": ".webp"}
    return mapping.get(file_format, ".png")


def _unique_asset_path(asset_dir, stem, ext):
    asset_dir.mkdir(parents=True, exist_ok=True)
    candidate = asset_dir / f"{stem}{ext}"
    index = 2
    while candidate.exists():
        candidate = asset_dir / f"{stem}_{index}{ext}"
        index += 1
    return candidate


def _export_image_asset(img, asset_dir, context, abspath, exists):
    if not img or not asset_dir:
        return {}
    ext = _image_extension(img, abspath)
    image_name = Path(str(getattr(img, "name", "image"))).stem
    stem = _safe_asset_name(f"{context or 'texture'}_{image_name}")
    target = _unique_asset_path(Path(asset_dir), stem, ext)
    try:
        if exists and abspath:
            shutil.copy2(abspath, target)
        else:
            original_filepath = getattr(img, "filepath_raw", None)
            try:
                img.filepath_raw = str(target)
                try:
                    img.save()
                except TypeError:
                    img.save_render(str(target))
            finally:
                if original_filepath is not None:
                    img.filepath_raw = original_filepath
        return {"asset_file": target.name, "asset_path": str(target)}
    except Exception as exc:
        return {"asset_error": str(exc)}


def _image_resource_info(img, asset_dir=None, context=None):
    if not img:
        return None
    abspath = None
    exists = False
    try:
        abspath = bpy.path.abspath(img.filepath) if img.filepath else None
    except Exception:
        abspath = None
    if abspath:
        exists = os.path.exists(abspath)
    packed = bool(getattr(img, "packed_file", None))
    source = getattr(img, "source", None)
    colorspace = None
    try:
        colorspace = img.colorspace_settings.name
    except Exception:
        colorspace = None
    info = {
        "name": img.name,
        "source": str(source) if source is not None else None,
        "source_file": Path(img.filepath).name if img.filepath else "",
        "exists": exists,
        "packed": packed,
        "resolution": [int(img.size[0]), int(img.size[1])] if hasattr(img, "size") else [0, 0],
        "clarity": _clarity_from_size(img.size) if hasattr(img, "size") else "Unknown",
        "colorspace": colorspace,
    }
    info.update(_export_image_asset(img, asset_dir, context, abspath, exists))
    return info

def _sample_image_component(img, component: Optional[str], samples: int = 2000):
    if not img or not hasattr(img, "pixels"):
        return None
    try:
        px = img.pixels
        total = int(len(px) / 4)
        if total <= 0:
            return None
        n = min(samples, total)
        if n <= 0:
            return None
        comp = (component or "R").upper()
        comp_idx = {"R": 0, "G": 1, "B": 2, "A": 3}.get(comp, 0)
        if total > n:
            idxs = random.sample(range(total), n)
        else:
            idxs = range(total)
        s = 0.0
        mn = 1e9
        mx = -1e9
        c = 0
        for i in idxs:
            v = float(px[i * 4 + comp_idx])
            s += v
            if v < mn:
                mn = v
            if v > mx:
                mx = v
            c += 1
        if c == 0:
            return None
        return {"component": comp, "min": round(mn, 4), "max": round(mx, 4), "mean": round(s / c, 4)}
    except Exception:
        return None

def _collect_upstream_images(node, from_socket_name, depth, visited, asset_dir=None, context=None):
    if not node or depth <= 0:
        return []
    key = (node.as_pointer(), from_socket_name)
    if key in visited:
        return []
    visited.add(key)

    if node.type == "TEX_IMAGE":
        return [{
            "image": _image_resource_info(node.image, asset_dir, context),
            "node_chain": [f"{node.type}:{node.name}"],
            "via": [],
        }]

    results = []

    if node.type in ("SEPRGB", "SEPARATE_COLOR"):
        comp = None
        if from_socket_name in ("R", "Red"):
            comp = "R"
        elif from_socket_name in ("G", "Green"):
            comp = "G"
        elif from_socket_name in ("B", "Blue"):
            comp = "B"
        elif from_socket_name in ("A", "Alpha"):
            comp = "A"
        for inp in node.inputs:
            if inp.is_linked:
                for link in inp.links:
                    upstream = _collect_upstream_images(link.from_node, link.from_socket.name, depth - 1, visited, asset_dir, context)
                    for u in upstream:
                        u["node_chain"].append(f"{node.type}:{node.name}")
                        if comp:
                            u["via"].append({"node": node.type, "component": comp})
                        results.append(u)
        return results

    if node.type == "NORMAL_MAP":
        for inp in node.inputs:
            if inp.is_linked:
                for link in inp.links:
                    upstream = _collect_upstream_images(link.from_node, link.from_socket.name, depth - 1, visited, asset_dir, context)
                    for u in upstream:
                        u["node_chain"].append(f"{node.type}:{node.name}")
                        u["via"].append({"node": node.type})
                        results.append(u)
        return results

    if node.type == "DISPLACEMENT":
        meta = {}
        try:
            meta = {
                "scale": float(node.inputs.get("Scale").default_value) if node.inputs.get("Scale") else None,
                "midlevel": float(node.inputs.get("Midlevel").default_value) if node.inputs.get("Midlevel") else None,
            }
        except Exception:
            meta = {}
        for inp in node.inputs:
            if inp.is_linked:
                for link in inp.links:
                    upstream = _collect_upstream_images(link.from_node, link.from_socket.name, depth - 1, visited, asset_dir, context)
                    for u in upstream:
                        u["node_chain"].append(f"{node.type}:{node.name}")
                        u["via"].append({"node": node.type, **meta})
                        results.append(u)
        return results

    for inp in getattr(node, "inputs", []):
        if inp.is_linked:
            for link in inp.links:
                upstream = _collect_upstream_images(link.from_node, link.from_socket.name, depth - 1, visited, asset_dir, context)
                for u in upstream:
                    u["node_chain"].append(f"{node.type}:{node.name}")
                    results.append(u)

    return results

def analyze_mesh(obj):
    """分析网格：面数、顶点、拓扑及尺寸信息"""
    mesh = obj.data
    
    # 获取尺寸信息 (X, Y, Z)
    size = obj.dimensions
    
    # 使用 bmesh 进行更准确的检测
    bm = bmesh.new()
    bm.from_mesh(mesh)
    
    # 检测非流形边缘
    non_manifold_edges = [e for e in bm.edges if not e.is_manifold]
    is_manifold = len(non_manifold_edges) == 0

    boundary_edge_count = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    loose_edge_count = sum(1 for e in bm.edges if len(e.link_faces) == 0)

    inward_ratio = None
    try:
        poly_count = len(mesh.polygons)
        if poly_count > 0:
            sample_n = min(5000, poly_count)
            idxs = random.sample(range(poly_count), sample_n) if poly_count > sample_n else range(poly_count)
            obj_center = obj.matrix_world.translation
            mat3 = obj.matrix_world.to_3x3()
            inward = 0
            total = 0
            for i in idxs:
                p = mesh.polygons[i]
                c = obj.matrix_world @ p.center
                n = (mat3 @ p.normal).normalized()
                v = c - obj_center
                if v.length > 1e-8:
                    if n.dot(v) < 0:
                        inward += 1
                    total += 1
            inward_ratio = round(inward / total, 4) if total else None
    except Exception:
        inward_ratio = None
    
    stats = {
        "name": obj.name,
        "vertices": len(mesh.vertices),
        "faces": len(mesh.polygons),
        "triangles": sum(len(p.vertices) - 2 for p in mesh.polygons),
        "dimensions": {
            "x": round(size.x, 4),
            "y": round(size.y, 4),
            "z": round(size.z, 4)
        },
        "has_uv": len(mesh.uv_layers) > 0,
        "zero_area_faces": sum(1 for p in mesh.polygons if p.area < 0.000001),
        "is_manifold": is_manifold,
        "non_manifold_edge_count": len(non_manifold_edges),
        "boundary_edge_count": int(boundary_edge_count),
        "loose_edge_count": int(loose_edge_count),
        "inward_normal_ratio": inward_ratio,
        "has_custom_normals": bool(getattr(mesh, "has_custom_normals", False)),
    }
    
    bm.free()
    return stats

def analyze_materials(asset_dir=None):
    """深度解析材质：追踪节点树查找所有贴图"""
    mats_info = []
    for mat in bpy.data.materials:
        if not mat.use_nodes: continue
        info = {
            "name": mat.name,
            "textures": [],
            "pbr_params": {},
            "alpha": {"used": False, "sources": []},
            "displacement": {"used": False, "sources": []},
            "unused_images": [],
            "blend_method": getattr(mat, "blend_method", None),
            "shadow_method": getattr(mat, "shadow_method", None),
        }
        
        # 查找 Principled BSDF 节点
        bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        image_by_name = {}
        for n in mat.node_tree.nodes:
            if getattr(n, "type", None) == "TEX_IMAGE" and getattr(n, "image", None):
                image_by_name[n.image.name] = n.image
        used_images = set()
        if bsdf:
            for input in bsdf.inputs:
                # 无论是否直接相连，递归查找图像节点
                if input.is_linked:
                    # 获取该输入点的所有链接
                    for link in input.links:
                        sources = _collect_upstream_images(link.from_node, link.from_socket.name, 24, set(), asset_dir, f"{mat.name}_{input.name}")
                        for s in sources:
                            img = s.get("image")
                            if not img:
                                continue
                            used_images.add(img["name"])
                            comp = None
                            for v in s.get("via", []):
                                if v.get("component") in ("R", "G", "B", "A"):
                                    comp = v.get("component")
                                    break
                            value_stats = None
                            if input.name in ("Metallic", "Roughness", "Alpha"):
                                value_stats = _sample_image_component(image_by_name.get(img["name"]), comp or "R")
                            info["textures"].append({
                                "channel": input.name,
                                "image": img,
                                "node_chain": list(reversed(s.get("node_chain", []))),
                                "via": s.get("via", []),
                                "value_stats": value_stats,
                            })
                            if input.name == "Alpha":
                                info["alpha"]["used"] = True
                                info["alpha"]["sources"].append({
                                    "image": img,
                                    "node_chain": list(reversed(s.get("node_chain", []))),
                                    "via": s.get("via", []),
                                })
                elif isinstance(input.default_value, (float, int)):
                    info["pbr_params"][input.name] = round(input.default_value, 3)

        for tex in info["textures"]:
            if tex.get("channel") == "Alpha":
                info["alpha"]["used"] = True

        output_node = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if output_node:
            disp_in = output_node.inputs.get("Displacement") if hasattr(output_node, "inputs") else None
            if disp_in and disp_in.is_linked:
                info["displacement"]["used"] = True
                for link in disp_in.links:
                    sources = _collect_upstream_images(link.from_node, link.from_socket.name, 24, set(), asset_dir, f"{mat.name}_Displacement")
                    for s in sources:
                        img = s.get("image")
                        if not img:
                            continue
                        used_images.add(img["name"])
                        info["displacement"]["sources"].append({
                            "image": img,
                            "node_chain": list(reversed(s.get("node_chain", []))),
                            "via": s.get("via", []),
                        })

        all_image_nodes = [n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and getattr(n, "image", None)]
        for n in all_image_nodes:
            img = n.image
            if img and img.name not in used_images:
                info["unused_images"].append(_image_resource_info(img, asset_dir, f"{mat.name}_Unused"))

        seen = set()
        dedup = []
        for t in info["textures"]:
            key = (t.get("channel"), (t.get("image") or {}).get("name"), json.dumps(t.get("via", []), ensure_ascii=False))
            if key in seen:
                continue
            seen.add(key)
            dedup.append(t)
        info["textures"] = dedup

        mats_info.append(info)
    return mats_info

def _parse_args():
    try:
        args = sys.argv[sys.argv.index("--") + 1:]
    except ValueError:
        args = []
    if not args:
        return None, None
    input_path = args[0]
    asset_dir = None
    if "--asset-dir" in args:
        idx = args.index("--asset-dir")
        if idx + 1 < len(args):
            asset_dir = args[idx + 1]
    return input_path, asset_dir


def main():
    input_path, asset_dir = _parse_args()
    if not input_path:
        print("Error: Missing input file path")
        return

    clean_scene()
    success, msg = import_model(input_path)
    if not success:
        print(f"---ERROR---{msg}")
        return

    # 汇总报告
    report = {
        "summary": {
            "mesh_count": len(bpy.data.meshes),
            "material_count": len(bpy.data.materials),
            "armature_count": len(bpy.data.armatures),
            "animation_count": len(bpy.data.actions)
        },
        "meshes": [analyze_mesh(obj) for obj in bpy.data.objects if obj.type == 'MESH'],
        "materials": analyze_materials(asset_dir),
        "armatures": [{"name": a.name, "bones": len(a.bones)} for a in bpy.data.armatures],
        "animations": [{"name": act.name, "frames": int(act.frame_range[1] - act.frame_range[0])} for act in bpy.data.actions]
    }

    # 标记 JSON 输出范围，方便 FastAPI 截取
    print("---RESULT_START---")
    print(json.dumps(report, indent=4))
    print("---RESULT_END---")

if __name__ == "__main__":
    main()
