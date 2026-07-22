# 模型分析 API 标准接口文档

## 1. 接口概览

- 服务名称：`model-analysis-api`
- 当前版本：`1.1.0`
- 当前部署地址：`http://34.219.48.53:8000`
- 请求/响应格式：`application/json`
- 分析方式：异步任务。客户端提交模型 URL 后，轮询任务状态获取结果。
- 任务结果默认保留：24 小时，可通过 `TASK_RETENTION_SECONDS` 配置。
- 单文件下载大小默认上限：300MB，可通过 `MAX_DOWNLOAD_BYTES` 配置。
- URL 限制：公网 `http/https`（拒绝本机、内网和保留地址）；亦支持 `s3://bucket/key` 从服务端配置的私有 S3（或 S3 兼容存储）拉取，凭证由服务端 `.env` 配置、不经请求传递。

## 2. 标准调用流程

1. 调用 `POST /analyze` 提交远程模型 URL。
2. 服务返回 `task_id` 和 `poll_url`。
3. 客户端每 2-5 秒调用 `GET /tasks/{task_id}` 轮询。
4. 当 `status=succeeded` 时读取 `result`。
5. 当 `status=failed` 时读取 `error`。

## 3. 分析引擎说明

服务使用 hybrid 合并模式：

| 引擎 | 用途 |
| --- | --- |
| native meshlib/trimesh | 几何、拓扑、点面数、非流形、边界边、零面积面、自相交、连通组件等。 |
| Blender | 材质、贴图、PBR、UV、四边面、法线、骨架、动画、包围盒和贴图导出。 |

`summary.model.analysis_engine` 取值：

| 值 | 含义 |
| --- | --- |
| `hybrid` | native 与 Blender 均成功，结果已合并。 |
| `native` | native 成功，Blender 失败；无 Blender 增强字段或贴图导出。 |
| `blender_fallback` | native 失败，Blender 成功。 |

## 4. 支持格式

| 类型 | 格式 |
| --- | --- |
| 几何分析 | `.glb`, `.gltf`, `.fbx`, `.obj`, `.stl`, `.dae`, `.usd`, `.usdz` |
| Blender 增强分析 | `.glb`, `.gltf`, `.fbx`, `.obj`, `.dae` |

`.stl`, `.usd`, `.usdz` 通常只返回几何分析结果，不保证返回材质、贴图、PBR、骨架、动画字段。

## 5. 健康检查

### 请求

```http
GET /
```

### 响应

```json
{
  "status": "ok",
  "service": "model-analysis-api",
  "version": "1.1.0",
  "max_concurrent_jobs": 10
}
```

## 6. 提交分析任务

### 请求

```http
POST /analyze
Content-Type: application/json
```

### 请求体

```json
{
  "url": "https://example.com/model.glb"
}
```

从私有对象存储拉取时，`url` 传 `s3://bucket/key`（凭证由服务端 `.env` 配置，AWS/BOS 均支持，按桶名路由）：

```json
{
  "url": "s3://cn-openapi/tcli_f5dd6b72952d43b99fdbe8fac1d45c1b/20260721/2fb24398-b5e7-4a00-b556-d8757e7f852b"
}
```

### 请求字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `url` | string | 是 | 3D 模型文件地址。公网 `http/https`；或 `s3://bucket/key`（从服务端 `.env` 配置的私有桶拉取，按桶名自动选 AWS/BOS 凭证，AK/SK 不经请求传递）。key 无扩展名时按 `.glb` 处理。 |

### 成功响应

HTTP 状态码：`202 Accepted`

```json
{
  "task_id": "0c92e9c7-9bb3-496d-9e64-9af5d4587c4a",
  "status": "pending",
  "poll_url": "/tasks/0c92e9c7-9bb3-496d-9e64-9af5d4587c4a",
  "message": "任务已提交，请轮询 poll_url 查询状态和结果"
}
```

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 后台任务 ID。 |
| `status` | string | 初始状态，通常为 `pending`。 |
| `poll_url` | string | 任务查询路径。 |
| `message` | string | 当前任务提示。 |

## 7. 查询任务状态

### 请求

```http
GET /tasks/{task_id}
```

### 路径参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `task_id` | string | 是 | 提交任务时返回的任务 ID。 |

### 任务状态

| status | 含义 | 是否终态 |
| --- | --- | --- |
| `pending` | 任务已提交或正在排队。 | 否 |
| `running` | 正在下载或分析。 | 否 |
| `succeeded` | 分析成功，返回 `result`。 | 是 |
| `failed` | 分析失败，返回 `error`。 | 是 |

### 通用响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 任务 ID。 |
| `status` | string | 当前任务状态。 |
| `source_url` | string | 用户提交的原始模型 URL。 |
| `created_at` | number | 任务创建时间，Unix 时间戳，单位秒。 |
| `updated_at` | number | 最近更新时间，Unix 时间戳，单位秒。 |
| `started_at` | number/null | 实际开始处理时间。 |
| `finished_at` | number/null | 任务完成时间。 |
| `message` | string | 当前状态说明。 |
| `result` | object | 成功结果，仅 `status=succeeded` 时存在。 |
| `error` | object | 失败信息，仅 `status=failed` 时存在。 |

### pending/running 响应示例

```json
{
  "task_id": "0c92e9c7-9bb3-496d-9e64-9af5d4587c4a",
  "status": "running",
  "source_url": "https://example.com/model.glb",
  "created_at": 1791199500.12,
  "updated_at": 1791199501.45,
  "started_at": 1791199501.01,
  "message": "模型下载完成，正在分析"
}
```

## 8. 成功结果结构

`status=succeeded` 时返回：

```json
{
  "task_id": "0c92e9c7-9bb3-496d-9e64-9af5d4587c4a",
  "status": "succeeded",
  "source_url": "https://example.com/model.glb",
  "created_at": 1791199500.12,
  "updated_at": 1791199510.34,
  "started_at": 1791199501.01,
  "finished_at": 1791199510.34,
  "message": "分析完成，下载缓存已删除",
  "result": {
    "summary": {},
    "quality": {},
    "professional_analysis": {},
    "geometry": {},
    "materials": [],
    "validation": {},
    "details": {}
  }
}
```

建议读取顺序：

1. `result.summary`：标准化概览，适合列表页、卡片和快速展示。
2. `result.quality`：基础质量判定。
3. `result.professional_analysis`：专家结论、问题和建议。
4. `result.geometry` / `result.materials`：几何、材质和贴图详情。
5. `result.details`：调试、原始分析和专家标准。

## 9. `result.summary` 标准字段

`summary` 是面向业务展示的标准化字段集合，核心是 `summary.parameters`。

### 9.1 `summary.model`

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `summary.model.source_url` | string | 用户提交的原始模型 URL。 |
| `summary.model.file_name` | string | 下载或解析出的文件名。 |
| `summary.model.analysis_engine` | string | 分析引擎：`hybrid`、`native`、`blender_fallback`。 |
| `summary.model.asset_retention_seconds` | number | 结果和贴图保留秒数。 |
| `summary.model.assets_expires_at` | number | 结果和贴图过期时间，Unix 秒。 |

### 9.2 `summary.parameters`

该对象按“模型 xxx=true/N”的使用方式展开，字段口径与 Blender 字段对齐。

| 用例写法 | 字段路径 | 类型 | 说明 |
| --- | --- | --- | --- |
| `模型 textures=true` | `summary.parameters.textures` | boolean | 是否包含贴图。 |
| `模型 pbr=true` | `summary.parameters.pbr` | boolean | 是否具备核心 PBR 贴图套装；要求贴图通道包含 Base Color、Normal、Roughness。 |
| `模型 PBR_1=true` | `summary.parameters.PBR_1` | boolean | 旧版宽松 PBR 判定；检测到 Base Color/Normal/Roughness/Metallic 任一贴图通道或 PBR 参数即为 true。 |
| `模型 quad_mesh=true` | `summary.parameters.quad_mesh` | boolean/null | 是否四边面占多数；原始四边面数大于原始三角面数时为 true，四边面少于或等于三角面时为 false，无法判断时为 null。 |
| `模型 low_poly=true` | `summary.parameters.low_poly` | boolean | 是否低模；规则为 `faces < 10000`。 |
| `模型 uv_export=true` | `summary.parameters.uv_export` | boolean | 是否有 UV 坐标。 |
| `模型 armature=true` | `summary.parameters.armature` | boolean | 是否带骨架。 |
| `模型 armature_count=N` | `summary.parameters.armature_count` | number | 骨架数量。 |
| `模型 bone_count=N` | `summary.parameters.bone_count` | number | 骨骼总数。 |
| `模型 animations=true` | `summary.parameters.animations` | boolean | 是否带动画。 |
| `模型 animation_count=N` | `summary.parameters.animation_count` | number | 动画数量。 |
| `模型 normals=true` | `summary.parameters.has_normals` | boolean | 是否存在法线数据。 |
| `模型 normals_valid=true` | `summary.parameters.normals_valid` | boolean/null | 法线是否有效；无零向量法线时为 true，无法判断时为 null。 |
| `模型 vertices=N` | `summary.parameters.vertices` | number | 顶点总数。 |
| `模型 faces=N` | `summary.parameters.faces` | number | 面数总数。 |
| `模型 bounds_x=N` | `summary.parameters.bounds.x` | number/null | 包围盒 X 轴尺寸。 |
| `模型 bounds_y=N` | `summary.parameters.bounds.y` | number/null | 包围盒 Y 轴尺寸。 |
| `模型 bounds_z=N` | `summary.parameters.bounds.z` | number/null | 包围盒 Z 轴尺寸。 |

### 9.3 `summary.parameters` 示例

```json
{
  "textures": true,
  "pbr": true,
  "quad_mesh": false,
  "low_poly": false,
  "uv_export": true,
  "armature": false,
  "armature_count": 0,
  "bone_count": 0,
  "animations": false,
  "animation_count": 0,
  "has_normals": true,
  "normals_valid": true,
  "vertices": 750256,
  "faces": 2445656,
  "bounds": {
    "x": 4.8123,
    "y": 3.2041,
    "z": 2.9917
  }
}
```

### 9.4 `summary.counts`

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `summary.counts.mesh_count` | number/null | mesh 数量。 |
| `summary.counts.vertices` | number/null | 顶点总数。 |
| `summary.counts.faces` | number/null | 面数总数。红线为 `faces > 2,000,000`。 |
| `summary.counts.triangles` | number/null | 三角面总数。 |
| `summary.counts.triangle_faces` | number/null | 原始三角面数量。 |
| `summary.counts.quad_faces` | number/null | 原始四边面数量。 |
| `summary.counts.material_count` | number/null | 材质数量。 |
| `summary.counts.texture_count` | number/null | 贴图通道数量，不等同于唯一图片数量。 |
| `summary.counts.armature_count` | number/null | 骨架数量。 |
| `summary.counts.animation_count` | number/null | 动画数量。 |

### 9.5 `summary.quality`

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `summary.quality.is_standard` | boolean | 基础规则是否通过。 |
| `summary.quality.label` | string | 中文标签：`标准` / `不标准`。 |
| `summary.quality.severity` | string | 严重级别：`green` / `yellow` / `red`。 |
| `summary.quality.reason_text` | string | 命中规则说明。 |

基础面数规则：

| 条件 | 级别 | 说明 |
| --- | --- | --- |
| `faces <= 100000` | `green` | 常规可控。 |
| `100000 < faces <= 2000000` | `yellow` | 模型偏重，建议优化。 |
| `faces > 2000000` | `red` | 高风险重模型，判定不标准。 |

### 9.6 其他 summary 字段

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `summary.professional.passed` | boolean | 专家检查是否通过。 |
| `summary.professional.level` | string | 专家最高问题等级：`pass`、`notice`、`warning`、`fail`。 |
| `summary.professional.detected_types` | string[] | 识别出的模型类型。 |
| `summary.model_types` | object | 白模、贴图、PBR、绑骨、动画、多 part 等模型类型布尔标记。 |
| `summary.geometry_flags` | object | 拓扑、边界、非流形、自相交、UV 等几何标记。 |
| `summary.material_flags` | object | 贴图、PBR 贴图套装、PBR_1 旧口径、缺失贴图、未使用贴图等材质标记。 |
| `summary.rig_animation_flags` | object | 骨架、骨骼、动画、权重等绑定动画标记。 |

## 10. `result.quality`

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `quality.is_standard` | boolean | 基础标准是否通过。 |
| `quality.label` | string | 中文判定标签。 |
| `quality.severity` | string | `green`、`yellow`、`red`。 |
| `quality.rules` | object[] | 当前启用规则。 |
| `quality.metrics.faces` | number | 质量判定使用的总面数。 |
| `quality.metrics.non_manifold_edge_count` | number | 非流形边数量。 |
| `quality.metrics.zero_area_faces` | number | 零面积面数量。 |
| `quality.reasons` | string[] | 命中的原因列表。 |
| `quality.reason_text` | string | 原因合并文本。 |

## 11. `result.professional_analysis`

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `professional_analysis.passed` | boolean | 专家专业检查是否通过。 |
| `professional_analysis.level` | string | 最高问题等级。 |
| `professional_analysis.conclusion` | string | 面向用户的完整结论。 |
| `professional_analysis.model_type_profile` | object | 模型类型识别详情。 |
| `professional_analysis.structure_conclusion` | string | 结构、面数、边界、组件、贴图等简短结论。 |
| `professional_analysis.impact_analysis` | object[] | 按影响面归类的分析。 |
| `professional_analysis.issues` | object[] | 问题列表，包含指标、等级、证据和修复建议。 |
| `professional_analysis.coverage_notes` | string[] | 分析覆盖范围说明。 |

## 12. `result.geometry`

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `geometry.mesh_count` | number | mesh 数量。 |
| `geometry.vertices` | number | 顶点总数。 |
| `geometry.faces` | number | 面数总数。 |
| `geometry.triangles` | number | 三角面总数。 |
| `geometry.meshes` | object[] | 每个 mesh 的几何信息。 |
| `geometry.meshes[].name` | string/null | mesh 名称。 |
| `geometry.meshes[].vertices` | number/null | 当前 mesh 顶点数。 |
| `geometry.meshes[].faces` | number/null | 当前 mesh 面数。 |
| `geometry.meshes[].triangles` | number/null | 当前 mesh 三角面数。 |
| `geometry.meshes[].triangle_faces` | number/null | 当前 mesh 原始三角面数量。 |
| `geometry.meshes[].quad_faces` | number/null | 当前 mesh 原始四边面数量。 |
| `geometry.meshes[].dimensions` | object/null | 包围盒尺寸。 |
| `geometry.meshes[].has_uv` | boolean/null | 是否有 UV。 |
| `geometry.meshes[].is_manifold` | boolean/null | 是否为流形网格。 |
| `geometry.meshes[].non_manifold_edge_count` | number/null | 非流形边数量。 |
| `geometry.meshes[].boundary_edge_count` | number/null | 边界/开口边数量。 |
| `geometry.meshes[].zero_area_faces` | number/null | 零面积面数量。 |
| `geometry.meshes[].loose_edge_count` | number/null | 游离边数量。 |
| `geometry.meshes[].inward_normal_ratio` | number/null | 内翻法向比例。 |
| `geometry.meshes[].has_custom_normals` | boolean/null | 是否有自定义法线。 |

## 13. `result.materials`

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `materials` | object[] | 材质列表。 |
| `materials[].name` | string/null | 材质名称。 |
| `materials[].texture_count` | number | 当前材质贴图通道数量。 |
| `materials[].textures` | object[] | 贴图通道列表。 |
| `materials[].textures[].channel` | string/null | 贴图通道，例如 `Base Color`、`Normal`、`Roughness`、`Metallic`。 |
| `materials[].textures[].image_name` | string/null | 图片资源名称。 |
| `materials[].textures[].source_file` | string/null | 外部贴图文件名。 |
| `materials[].textures[].packed` | boolean/null | 是否打包在模型内。 |
| `materials[].textures[].resolution` | number[]/null | 贴图分辨率 `[width, height]`。 |
| `materials[].textures[].clarity` | string/null | 清晰度等级，例如 `Low`、`1K`、`2K`、`4K`。 |
| `materials[].textures[].colorspace` | string/null | 色彩空间。 |
| `materials[].textures[].url` | string/null | 导出的贴图访问 URL。 |
| `materials[].textures[].asset_file` | string/null | 服务端临时贴图文件名。 |
| `materials[].textures[].asset_error` | string/null | 贴图导出错误。 |
| `materials[].pbr_params` | object/null | PBR 参数。 |
| `materials[].alpha` | object/null | 透明信息。 |
| `materials[].displacement` | object/null | 置换信息。 |
| `materials[].unused_images` | object[] | 未使用图片节点。 |

## 14. `result.validation`

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `validation.geometry_matches_computed_metrics` | boolean | `geometry` 与专家汇总点面数是否一致。 |
| `validation.quality_metrics_match_geometry` | boolean | 质量判定面数是否与 `geometry.faces` 一致。 |
| `validation.texture_count_matches_materials` | boolean | 贴图数量是否与材质列表求和一致。 |
| `validation.analysis_engine` | string | 分析引擎。 |
| `validation.passed` | boolean | 上述一致性校验是否全部通过。 |

## 15. `result.details`

`details` 用于调试和深度集成，普通展示优先使用 `summary`、`quality`、`professional_analysis`。

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `details.computed_metrics` | object | 专家分析汇总指标。 |
| `details.texture_resolution_summary` | object[] | 贴图分辨率摘要。 |
| `details.expert_skill` | object | 专家规则描述。 |
| `details.expert_standard` | object | 专家标准说明。 |
| `details.raw_analysis` | object | hybrid 合并后的原始分析数据。 |
| `details.raw_analysis.engines` | object | native/Blender 使用情况。 |
| `details.raw_analysis.analysis_errors` | object[] | 某个引擎失败但任务仍成功时的错误列表。 |
| `details.raw_analysis.meshes` | object[] | 原始 mesh 指标。 |
| `details.raw_analysis.materials` | object[] | 原始材质贴图指标。 |
| `details.raw_analysis.armatures` | object[] | 原始骨架数据。 |
| `details.raw_analysis.animations` | object[] | 原始动画数据。 |

## 16. succeeded 响应示例

```json
{
  "task_id": "0c92e9c7-9bb3-496d-9e64-9af5d4587c4a",
  "status": "succeeded",
  "source_url": "https://example.com/model.glb",
  "created_at": 1791199500.12,
  "updated_at": 1791199510.34,
  "started_at": 1791199501.01,
  "finished_at": 1791199510.34,
  "message": "分析完成，下载缓存已删除",
  "result": {
    "summary": {
      "model": {
        "source_url": "https://example.com/model.glb",
        "file_name": "model.glb",
        "analysis_engine": "hybrid",
        "asset_retention_seconds": 86400,
        "assets_expires_at": 1791285910.34
      },
      "parameters": {
        "textures": true,
        "pbr": true,
        "quad_mesh": false,
        "low_poly": false,
        "uv_export": true,
        "armature": false,
        "armature_count": 0,
        "bone_count": 0,
        "animations": false,
        "animation_count": 0,
        "has_normals": true,
        "normals_valid": true,
        "vertices": 750256,
        "faces": 2445656,
        "bounds": {
          "x": 4.8123,
          "y": 3.2041,
          "z": 2.9917
        }
      },
      "counts": {
        "mesh_count": 1,
        "vertices": 750256,
        "faces": 2445656,
        "triangles": 2445656,
        "material_count": 1,
        "texture_count": 4,
        "armature_count": 0,
        "animation_count": 0
      },
      "quality": {
        "is_standard": false,
        "label": "不标准",
        "severity": "red",
        "reason_text": "面数超过 2,000,000（当前 2445656）"
      },
      "professional": {
        "passed": false,
        "level": "fail",
        "detected_types": ["贴图模型", "PBR材质模型"]
      }
    },
    "quality": {
      "is_standard": false,
      "label": "不标准",
      "severity": "red",
      "metrics": {
        "faces": 2445656,
        "non_manifold_edge_count": 0,
        "zero_area_faces": 0
      },
      "reasons": ["面数超过 2,000,000（当前 2445656）"],
      "reason_text": "面数超过 2,000,000（当前 2445656）"
    },
    "professional_analysis": {
      "passed": false,
      "level": "fail",
      "conclusion": "模型未完全满足专业3D质量标准...",
      "structure_conclusion": "面数 2,445,656，属于高风险重模型...",
      "impact_analysis": [],
      "issues": [],
      "coverage_notes": []
    },
    "geometry": {
      "mesh_count": 1,
      "vertices": 750256,
      "faces": 2445656,
      "triangles": 2445656,
      "meshes": []
    },
    "materials": [],
    "validation": {
      "geometry_matches_computed_metrics": true,
      "quality_metrics_match_geometry": true,
      "texture_count_matches_materials": true,
      "analysis_engine": "hybrid",
      "passed": true
    },
    "details": {
      "computed_metrics": {},
      "texture_resolution_summary": [],
      "expert_skill": {},
      "expert_standard": {},
      "raw_analysis": {}
    }
  }
}
```

## 17. 贴图 URL 说明

- 标准化贴图链接位于 `result.materials[].textures[].url`。
- 原始 Blender 贴图信息位于 `result.details.raw_analysis.materials[].textures[].image`。
- 配置 `PUBLIC_BASE_URL` 后，贴图 URL 为完整外部可访问地址。
- 贴图 URL 与任务结果默认保留 24 小时。
- API 不返回本地绝对路径。

## 18. 失败响应

### failed 响应示例

```json
{
  "task_id": "0c92e9c7-9bb3-496d-9e64-9af5d4587c4a",
  "status": "failed",
  "source_url": "https://example.com/model.glb",
  "created_at": 1791199500.12,
  "updated_at": 1791199502.34,
  "started_at": 1791199501.01,
  "finished_at": 1791199502.34,
  "message": "分析失败，下载缓存已删除",
  "error": {
    "code": "DOWNLOAD_HTTP_ERROR",
    "message": "URL 下载失败: HTTP 404",
    "detail": "URL 下载失败: HTTP 404"
  }
}
```

### error 字段

| 字段路径 | 类型 | 说明 |
| --- | --- | --- |
| `error.code` | string | 机器可读错误码。 |
| `error.message` | string | 面向用户展示的中文错误信息。 |
| `error.detail` | string | 排查用错误细节。 |
| `error.engine_errors` | object[] | native/Blender 子错误列表；仅分析引擎失败时可能存在。 |
| `error.engine_errors[].engine` | string | 出错引擎：`native` 或 `blender`。 |
| `error.engine_errors[].code` | string | 子错误码。 |
| `error.engine_errors[].message` | string | 子错误信息。 |

## 19. 错误码

| code | 说明 |
| --- | --- |
| `INVALID_URL` | URL scheme 或 hostname 非法。 |
| `URL_DNS_FAILED` | 域名无法解析。 |
| `URL_NOT_PUBLIC` | URL 指向本机、内网或保留地址。 |
| `UNSUPPORTED_FORMAT` | 文件扩展名不在支持范围内。 |
| `DOWNLOAD_HTTP_ERROR` | 远程下载返回非 200 HTTP 状态。 |
| `DOWNLOAD_FAILED` | 网络请求或下载过程失败。 |
| `DOWNLOAD_TOO_LARGE` | 文件超过大小限制。 |
| `S3_NOT_CONFIGURED` | 请求用 `s3://`/裸 key，但服务端未配置对应后端（AWS 或 BOS）的凭证。 |
| `S3_INVALID_URI` | `s3://` URI 格式非法（缺 bucket 或 key）。 |
| `S3_DOWNLOAD_FAILED` | S3/BOS 对象下载失败（如 NoSuchKey、AccessDenied、区域/端点错误）。 |
| `S3_KEY_NOT_FOUND` | 裸 object key 在所有候选桶里都没找到。 |
| `NATIVE_ANALYSIS_FAILED` | native 分析失败。 |
| `BLENDER_NOT_FOUND` | 找不到 Blender 可执行文件。 |
| `BLENDER_SCRIPT_NOT_FOUND` | 找不到 Blender 分析脚本。 |
| `BLENDER_ANALYSIS_FAILED` | Blender 运行失败或未输出合法 JSON。 |
| `ANALYSIS_FAILED` | native 与 Blender 都失败，或分析阶段兜底错误。 |
| `HTTP_ERROR` | FastAPI HTTPException 兜底错误。 |

## 20. 轮询建议

```bash
TASK_ID="0c92e9c7-9bb3-496d-9e64-9af5d4587c4a"
curl "http://34.219.48.53:8000/tasks/${TASK_ID}"
```

建议每 2-5 秒轮询一次，遇到 `succeeded` 或 `failed` 后停止。

## 21. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOWNLOAD_DIR` | `downloads` | 临时下载目录。 |
| `ASSET_DIR` | `downloads/assets` | 贴图静态资源目录。 |
| `MAX_DOWNLOAD_BYTES` | `314572800` | 单文件最大下载字节数。 |
| `MAX_CONCURRENT_JOBS` | `10` | 最大并发分析任务数。 |
| `TASK_RETENTION_SECONDS` | `86400` | 任务结果保留秒数。 |
| `PUBLIC_BASE_URL` | 空 | 对外可访问服务地址；配置后贴图返回完整 URL。 |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | 空 | AWS S3 读凭证；下载 `S3_BUCKETS` 里的桶时使用。 |
| `S3_REGION` | `us-west-2` | AWS S3 区域。 |
| `S3_BUCKETS` | `tripo-data,vast-plugin-data` | AWS 侧候选桶（逗号分隔）；桶名归属由此判定。 |
| `S3_SESSION_TOKEN` | 空 | 可选，AWS 临时凭证 session token。 |
| `BOS_ACCESS_KEY` / `BOS_SECRET_KEY` | 空 | 百度 BOS 读凭证；下载 `BOS_BUCKETS` 里的桶时使用。 |
| `BOS_ENDPOINT` | 空 | BOS 端点（如 `https://s3.bj.bcebos.com`）。 |
| `BOS_BUCKETS` | `cn-openapi,cn-openapi-test,tripo-studio-cn-data-prod,tripo-studio-cn-data-test` | BOS 侧候选桶（逗号分隔）。 |
| `BLENDER_BIN` | `/Applications/Blender.app/Contents/MacOS/Blender` | Blender 可执行文件路径。 |
| `PORT` | `8000` | `python main.py` 启动端口。 |
