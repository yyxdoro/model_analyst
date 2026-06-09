# 模型分析 API 接口文档

## 服务说明

当前部署访问地址：`http://34.219.48.53:8000`

服务用于分析单个远程 3D 模型文件。客户端提交模型 `url` 后，服务异步下载文件并分析；客户端通过任务状态接口轮询获取结果。

分析成功后，服务会自动触发内置 `professional_3d_modeling_expert` 专家 skill。该 skill 基于 `docs/metrics.md` 中的专业指标体系，将模型分析结果转换为专业 3D 建模质检结论，并与固定标准、标准化报告、原始分析结果一起返回。

- 默认最大并发任务数：10
- 下载大小上限：300MB，可通过 `MAX_DOWNLOAD_BYTES` 调整
- 任务结果保留时间：24 小时，可通过 `TASK_RETENTION_SECONDS` 调整
- 材质贴图链接默认保留 24 小时，与任务结果同步过期
- 下载缓存文件会在任务成功或失败后删除
- URL 仅允许公网 `http/https`，会拒绝本机、内网、保留地址

## 分析引擎

标准接口使用 hybrid 合并模式：

1. **native meshlib/trimesh**：优先读取模型几何，负责点数、面数、三角面、边界边、非流形边、零面积面、自相交、连通组件等几何/拓扑指标。
2. **Blender**：对 `.glb`, `.gltf`, `.fbx`, `.obj`, `.dae` 补充材质、贴图、PBR、骨架、动画，并导出可访问的贴图 asset URL。
3. 两者都成功时 `analysis_engine` 为 `hybrid`。
4. native 成功、Blender 失败时任务仍可成功，`analysis_engine` 为 `native`，并在 `analysis_errors` 中记录 Blender 错误。
5. native 失败、Blender 成功时任务仍可成功，`analysis_engine` 为 `blender_fallback`，并记录 native 错误。
6. 两者都失败时任务状态为 `failed`，返回结构化错误码。

## 支持格式

- 几何分析：`.glb`, `.gltf`, `.fbx`, `.obj`, `.stl`, `.dae`, `.usd`, `.usdz`
- Blender 增强分析：`.glb`, `.gltf`, `.fbx`, `.obj`, `.dae`
- `.stl`, `.usd`, `.usdz` 通常只有 native 几何分析，不返回 Blender 导出的贴图链接

## 专家 Skill 说明

### Skill 名称

`professional_3d_modeling_expert`

### 触发时机

当后台任务完成模型下载并成功得到 `analysis` 后，服务自动调用专家 skill 生成专业分析。

### 覆盖能力

- **白模/基础网格模型**：拓扑、面数、退化面、法向、边界、自相交、连通组件。
- **绑骨模型**：骨架数量、骨骼数量、动画轨道、帧长、蒙皮权重异常。
- **贴图模型**：UV、贴图数量、贴图通道、贴图路径/打包状态、贴图清晰度、未使用贴图。
- **PBR模型**：Base Color、Normal、Roughness、Metallic 等核心 PBR 通道完整性。
- **分part/多mesh模型**：mesh 数量、part 命名、连通组件、碎片化风险。

几何相似度类指标需要 GT 标准模型和配准流程，当前单 URL 接口默认不计算。

## 1. 健康检查

### 请求

```http
GET /
```

### 响应示例

```json
{
  "status": "ok",
  "service": "model-analysis-api",
  "version": "1.1.0",
  "max_concurrent_jobs": 10
}
```

## 2. 提交分析任务

### 请求

```http
POST /analyze
Content-Type: application/json

{
  "url": "https://example.com/model.glb"
}
```

### curl 示例

```bash
curl -X POST http://34.219.48.53:8000/analyze \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/model.glb"}'
```

### 请求参数

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| `url` | string | 是 | 需要分析的远程 3D 模型文件 URL；只支持公网 `http/https`，不允许本机、内网或保留地址。 |

### 返回字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `task_id` | string | 后台分析任务 ID，后续用它查询任务状态。 |
| `status` | string | 初始任务状态，提交成功后通常为 `pending`。 |
| `poll_url` | string | 查询任务状态的相对路径，客户端轮询该地址直到 `succeeded` 或 `failed`。 |
| `message` | string | 当前任务提示信息。 |

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

## 3. 查询任务状态

### 请求

```http
GET /tasks/{task_id}
```

### 查询参数

| 参数 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| `task_id` | string | 是 | 提交任务时返回的任务 ID。任务过期或不存在时返回 404。 |

### 通用返回字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `task_id` | string | 任务 ID。 |
| `status` | string | 当前任务状态：`pending`、`running`、`succeeded` 或 `failed`。 |
| `source_url` | string | 提交分析时传入的原始模型 URL。 |
| `created_at` | number | 任务创建时间，Unix 时间戳，单位秒。 |
| `updated_at` | number | 任务最近更新时间，Unix 时间戳，单位秒。 |
| `started_at` | number/null | 实际开始处理时间；排队中可能为空。 |
| `finished_at` | number/null | 任务完成时间；未完成时为空。 |
| `message` | string | 当前任务处理状态说明。 |
| `result` | object | 分析成功后的完整结果，仅 `succeeded` 时返回。 |
| `error` | object | 分析失败后的错误信息，仅 `failed` 时返回。 |

### 状态说明

| status | 含义 |
| --- | --- |
| `pending` | 任务已提交或正在排队 |
| `running` | 正在下载或分析 |
| `succeeded` | 分析成功，结果已返回 |
| `failed` | 分析失败，返回结构化错误信息 |

### pending / running 响应示例

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

### succeeded 结果读取顺序

建议调用方按以下顺序读取成功结果：

1. `result.summary`：当前模型已有参数概览，适合列表页、卡片和快速判断。
2. `result.quality` + `result.professional_analysis`：基础判定和专业结论。
3. `result.geometry` + `result.materials`：几何、材质、贴图展示详情。
4. `result.details`：补充指标、专家标准和原始分析数据，适合调试或深度集成。

### succeeded 核心结果字段说明

| 字段路径 | 类型 | 含义 |
| --- | --- | --- |
| `result.summary` | object | 当前模型已有参数概览，放在成功结果最上方。 |
| `result.quality` | object | 基础标准化判定，适合快速判断是否命中硬性规则。 |
| `result.professional_analysis` | object | 专家质检结论、问题列表、影响分析和覆盖说明。 |
| `result.geometry` | object | 标准化几何信息。 |
| `result.materials` | array | 标准化材质和贴图信息。 |
| `result.validation` | object | 报告内部一致性校验结果。 |
| `result.details` | object | 放在结果底部的补充详情，包含专家指标、标准和原始分析数据。 |

### `result.summary` 字段说明

| 字段路径 | 类型 | 含义 |
| --- | --- | --- |
| `summary.model.source_url` | string | 原始模型 URL。 |
| `summary.model.file_name` | string | 下载或解析出的模型文件名。 |
| `summary.model.analysis_engine` | string | 本次使用的分析引擎：`hybrid`、`native` 或 `blender_fallback`。 |
| `summary.model.asset_retention_seconds` | number | 材质贴图和任务结果保留秒数。 |
| `summary.model.assets_expires_at` | number | 材质贴图过期时间，Unix 时间戳，单位秒。 |
| `summary.counts.mesh_count` | number/null | mesh 数量。 |
| `summary.counts.vertices` | number/null | 总顶点数。 |
| `summary.counts.faces` | number/null | 总面数。当前红线为 `faces > 2,000,000`。 |
| `summary.counts.triangles` | number/null | 总三角面数。 |
| `summary.counts.material_count` | number/null | 材质数量。 |
| `summary.counts.texture_count` | number/null | 贴图通道数量。 |
| `summary.counts.armature_count` | number/null | 骨架数量。 |
| `summary.counts.animation_count` | number/null | 动画数量。 |
| `summary.quality.is_standard` | boolean | 是否通过基础标准规则。 |
| `summary.quality.label` | string | 中文判定标签，例如 `标准` / `不标准`。 |
| `summary.quality.severity` | string | 基础严重级别：`green`、`yellow`、`red`。 |
| `summary.quality.reason_text` | string | 命中规则原因的中文合并文本。 |
| `summary.professional.passed` | boolean | 是否通过专家专业检查。 |
| `summary.professional.level` | string | 专家最高问题等级：`pass`、`notice`、`warning`、`fail`。 |
| `summary.professional.detected_types` | array | 识别出的中文模型类型列表。 |
| `summary.model_types.white_mesh_model` | boolean/null | 是否为白模/基础网格模型。 |
| `summary.model_types.rigged_model` | boolean/null | 是否为绑骨模型。 |
| `summary.model_types.animated_model` | boolean/null | 是否为动画模型。 |
| `summary.model_types.textured_model` | boolean/null | 是否为贴图模型。 |
| `summary.model_types.pbr_model` | boolean/null | 是否为 PBR 材质模型。 |
| `summary.model_types.multi_part_model` | boolean/null | 是否为分 part / 多 mesh 模型。 |
| `summary.model_types.detected_types` | array | 识别出的中文模型类型列表。 |
| `summary.geometry_flags.has_uv` | boolean | 是否检测到 UV。 |
| `summary.geometry_flags.is_manifold` | boolean/array/null | mesh 是否为流形；单 mesh 返回布尔值，多 mesh 返回数组。 |
| `summary.geometry_flags.non_manifold_edge_count` | number/null | 非流形边数量。 |
| `summary.geometry_flags.boundary_edge_count` | number/null | 边界/开口边数量。 |
| `summary.geometry_flags.zero_area_faces` | number/null | 零面积面数量。 |
| `summary.geometry_flags.self_intersection_count` | number/null | 自相交数量。 |
| `summary.geometry_flags.component_count` | number/null | 连通组件数量。 |
| `summary.material_flags.has_texture_model` | boolean/null | 是否识别为贴图模型。 |
| `summary.material_flags.has_pbr_model` | boolean/null | 是否识别为 PBR 材质模型。 |
| `summary.material_flags.pbr_channels` | object/null | PBR 通道存在性，例如 `base_color`、`normal`、`roughness`、`metallic`。 |
| `summary.material_flags.texture_channels` | array | 检测到的贴图通道列表。 |
| `summary.material_flags.missing_image_count` | number/null | 缺失贴图数量。 |
| `summary.material_flags.unused_image_count` | number/null | 未使用贴图数量。 |

### `result.quality` 字段说明

| 字段路径 | 类型 | 含义 |
| --- | --- | --- |
| `quality.is_standard` | boolean | 是否通过基础标准规则。 |
| `quality.label` | string | 中文判定标签。 |
| `quality.severity` | string | 基础严重级别。 |
| `quality.rules` | array | 当前启用的基础规则列表。 |
| `quality.metrics.faces` | number | 模型总面数。 |
| `quality.metrics.non_manifold_edge_count` | number | 非流形边数量。 |
| `quality.metrics.zero_area_faces` | number | 零面积面数量。 |
| `quality.reasons` | array | 命中的基础规则原因列表。 |
| `quality.reason_text` | string | `reasons` 的中文合并文本。 |

### `result.professional_analysis` 字段说明

| 字段路径 | 类型 | 含义 |
| --- | --- | --- |
| `professional_analysis.passed` | boolean | 是否通过专家专业检查。 |
| `professional_analysis.level` | string | 专家最高问题等级。 |
| `professional_analysis.conclusion` | string | 面向人阅读的完整专业结论。 |
| `professional_analysis.model_type_profile` | object | 模型类型识别结果。 |
| `professional_analysis.model_type_profile.detected_types` | array | 识别出的中文模型类型列表。 |
| `professional_analysis.structure_conclusion` | string | 针对结构、面数、边界、组件、贴图等的简短结论。 |
| `professional_analysis.impact_analysis` | array | 按影响面归类的分析，例如拓扑结构、渲染传输、材质贴图。 |
| `professional_analysis.issues` | array | 检测到的问题列表，每项包含指标名、等级、证据和修复建议。 |
| `professional_analysis.coverage_notes` | array | 当前分析覆盖范围说明。 |

### `result.geometry` 字段说明

| 字段路径 | 类型 | 含义 |
| --- | --- | --- |
| `geometry.mesh_count` | number | mesh 数量。 |
| `geometry.vertices` | number | 总顶点数。 |
| `geometry.faces` | number | 总面数。 |
| `geometry.triangles` | number | 总三角面数。 |
| `geometry.meshes[]` | array | 每个 mesh 的基础几何信息。 |
| `geometry.meshes[].name` | string/null | mesh 名称。 |
| `geometry.meshes[].dimensions` | object/null | mesh 包围盒尺寸。 |
| `geometry.meshes[].has_uv` | boolean/null | 是否检测到 UV。 |
| `geometry.meshes[].is_manifold` | boolean/null | 是否为流形网格。 |
| `geometry.meshes[].non_manifold_edge_count` | number/null | 该 mesh 的非流形边数量。 |
| `geometry.meshes[].boundary_edge_count` | number/null | 该 mesh 的边界/开口边数量。 |
| `geometry.meshes[].zero_area_faces` | number/null | 该 mesh 的零面积面数量。 |
| `geometry.meshes[].loose_edge_count` | number/null | 游离边数量。 |
| `geometry.meshes[].inward_normal_ratio` | number/null | 内翻法向比例；未检测时为空。 |
| `geometry.meshes[].has_custom_normals` | boolean/null | 是否包含自定义法向。 |

### `result.materials` 字段说明

| 字段路径 | 类型 | 含义 |
| --- | --- | --- |
| `materials[]` | array | 材质列表。 |
| `materials[].name` | string/null | 材质名称。 |
| `materials[].texture_count` | number | 当前材质识别到的贴图通道数量。 |
| `materials[].textures[]` | array | 当前材质的贴图通道列表。 |
| `materials[].textures[].channel` | string/null | 贴图通道，例如 `Base Color`、`Normal`、`Roughness`、`Metallic`。 |
| `materials[].textures[].image_name` | string/null | 图片资源在模型中的名称。 |
| `materials[].textures[].source_file` | string/null | 外部贴图源文件路径；打包贴图通常为空。 |
| `materials[].textures[].packed` | boolean/null | 贴图是否打包在模型文件内。 |
| `materials[].textures[].resolution` | array/null | 贴图分辨率 `[width, height]`。 |
| `materials[].textures[].clarity` | string/null | 分辨率等级，例如 `2K`。 |
| `materials[].textures[].colorspace` | string/null | 色彩空间，例如 `sRGB` 或 `Non-Color`。 |
| `materials[].textures[].url` | string/null | 导出的贴图访问 URL。配置 `PUBLIC_BASE_URL` 后为完整可访问链接。 |
| `materials[].textures[].asset_file` | string/null | 服务端临时导出的贴图文件名。 |
| `materials[].textures[].asset_error` | string/null | 贴图导出错误；为空表示导出正常。 |
| `materials[].pbr_params` | object/null | 材质 PBR 参数。 |
| `materials[].alpha` | object/null | 透明相关信息。 |
| `materials[].displacement` | object/null | 置换相关信息。 |
| `materials[].unused_images` | array | 未使用图片节点列表。 |

### `result.validation` 字段说明

| 字段路径 | 类型 | 含义 |
| --- | --- | --- |
| `validation.geometry_matches_computed_metrics` | boolean | `geometry` 是否与专家汇总指标一致。 |
| `validation.quality_metrics_match_geometry` | boolean | 基础质量指标是否与几何统计一致。 |
| `validation.texture_count_matches_materials` | boolean | 贴图数量是否与材质列表统计一致。 |
| `validation.analysis_engine` | string | 本次使用的分析引擎。 |
| `validation.passed` | boolean | 上述校验是否全部通过。 |

### `result.details` 字段说明

| 字段路径 | 类型 | 含义 |
| --- | --- | --- |
| `details.computed_metrics` | object | 专家分析汇总指标，包含面数、顶点数、边界边、自相交、材质贴图、骨架动画等。 |
| `details.texture_resolution_summary` | array | 贴图分辨率摘要，包含材质名、通道、图片名、分辨率和可访问 URL。 |
| `details.expert_skill` | object | 专家规则/能力描述，用于说明专业分析依据。 |
| `details.expert_standard` | object | 专家标准说明，包括准入基线、通过条件和指标组。 |
| `details.raw_analysis` | object | hybrid 合并后的原始分析数据。 |
| `details.raw_analysis.engines` | object | native/Blender 实际使用情况。 |
| `details.raw_analysis.analysis_errors` | array | 某个分析引擎失败但任务仍成功时的错误列表。 |
| `details.raw_analysis.summary` | object | 原始汇总指标。 |
| `details.raw_analysis.meshes` | array | 原始 mesh 指标列表。 |
| `details.raw_analysis.materials` | array | 原始材质/贴图分析列表。 |
| `details.raw_analysis.armatures` | array | 骨架数据列表。 |
| `details.raw_analysis.animations` | array | 动画数据列表。 |

### succeeded 响应结构

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
      },
      "model_types": {
        "white_mesh_model": false,
        "rigged_model": false,
        "animated_model": false,
        "textured_model": true,
        "pbr_model": true,
        "multi_part_model": false,
        "detected_types": ["贴图模型", "PBR材质模型"]
      },
      "geometry_flags": {
        "has_uv": true,
        "is_manifold": false,
        "non_manifold_edge_count": 0,
        "boundary_edge_count": 45594,
        "zero_area_faces": 0,
        "self_intersection_count": 135,
        "component_count": 128
      },
      "material_flags": {
        "has_texture_model": true,
        "has_pbr_model": true,
        "pbr_channels": {
          "base_color": true,
          "normal": true,
          "roughness": true,
          "metallic": true
        },
        "texture_channels": ["base_color", "metallic", "normal", "roughness"],
        "missing_image_count": 0,
        "unused_image_count": 0
      },
      "rig_animation_flags": {
        "has_rigged_model": false,
        "has_animation": false,
        "armature_count": 0,
        "bone_count": 0,
        "animation_count": 0,
        "animation_frame_count": 0,
        "weight_mesh_count": 0,
        "non_normalized_weight_vertices": 0,
        "zero_weight_vertices": 0
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
      "model_type_profile": {
        "textured_model": true,
        "pbr_model": true,
        "detected_types": ["贴图模型", "PBR材质模型"]
      },
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
    "materials": [
      {
        "name": "Body",
        "texture_count": 4,
        "textures": [
          {
            "channel": "Base Color",
            "image_name": "BaseColor",
            "resolution": [2048, 2048],
            "clarity": "2K",
            "url": "http://34.219.48.53:8000/assets/0c92e9c7-9bb3-496d-9e64-9af5d4587c4a/Body_Base_Color_BaseColor.png",
            "asset_file": "Body_Base_Color_BaseColor.png"
          }
        ]
      }
    ],
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
      "raw_analysis": {
        "analyzer": "hybrid_native_blender",
        "engines": {
          "primary": "hybrid",
          "geometry": "native_meshlib_full_fidelity",
          "materials": "blender"
        },
        "analysis_errors": [],
        "summary": {},
        "meshes": [],
        "materials": [],
        "armatures": [],
        "animations": []
      }
    }
  }
}
```

### 贴图链接说明

- 标准化贴图链接位于 `result.materials[].textures[].url`
- 原始 Blender 贴图链接位于 `result.details.raw_analysis.materials[].textures[].image.url`
- 链接为完整可访问 URL，例如 `http://34.219.48.53:8000/assets/{task_id}/{asset_file}`
- 贴图链接与任务结果默认保留 24 小时
- 如果 Blender 失败但 native 成功，任务仍可成功，但只返回贴图引用名，不返回导出的 `/assets/...` 图片链接
- API 不返回贴图的本地绝对路径

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

### failed 字段说明

| 字段路径 | 类型 | 含义 |
| --- | --- | --- |
| `error.code` | string | 机器可读错误码，见下方错误码表。 |
| `error.message` | string | 面向用户展示的中文错误信息。 |
| `error.detail` | string | 更具体的错误细节，便于排查。 |
| `error.engine_errors` | array | native/Blender 分析阶段的子错误列表；仅分析引擎失败时可能出现。 |
| `error.engine_errors[].engine` | string | 出错的分析引擎，例如 `native` 或 `blender`。 |
| `error.engine_errors[].code` | string | 子错误码。 |
| `error.engine_errors[].message` | string | 子错误信息。 |

当 native 和 Blender 都失败时：

```json
{
  "error": {
    "code": "ANALYSIS_FAILED",
    "message": "模型分析失败，请检查 URL 是否可下载、文件格式是否受支持，或确认分析依赖已正确安装。",
    "detail": "Native and Blender analysis both failed",
    "engine_errors": [
      {
        "engine": "native",
        "code": "NATIVE_ANALYSIS_FAILED",
        "message": "..."
      },
      {
        "engine": "blender",
        "code": "BLENDER_ANALYSIS_FAILED",
        "message": "..."
      }
    ]
  }
}
```

## 4. 错误码

| code | 含义 |
| --- | --- |
| `INVALID_URL` | URL scheme 或 hostname 非法 |
| `URL_DNS_FAILED` | 域名无法解析 |
| `URL_NOT_PUBLIC` | URL 指向本机、内网、保留地址等不允许下载的地址 |
| `UNSUPPORTED_FORMAT` | 文件扩展名不在支持范围内 |
| `DOWNLOAD_HTTP_ERROR` | 远程下载返回非 200 HTTP 状态 |
| `DOWNLOAD_FAILED` | 网络请求或下载过程失败 |
| `DOWNLOAD_TOO_LARGE` | 文件超过 `MAX_DOWNLOAD_BYTES` |
| `NATIVE_ANALYSIS_FAILED` | native meshlib/trimesh 分析失败 |
| `BLENDER_NOT_FOUND` | 找不到 Blender 可执行文件 |
| `BLENDER_SCRIPT_NOT_FOUND` | 找不到 Blender 分析脚本 |
| `BLENDER_ANALYSIS_FAILED` | Blender 运行失败或未输出合法 JSON 结果 |
| `ANALYSIS_FAILED` | native 与 Blender 都失败或分析阶段兜底错误 |
| `HTTP_ERROR` | FastAPI HTTPException 兜底错误 |

## 5. 轮询建议

客户端提交任务后，每 2-5 秒请求一次 `poll_url`：

```bash
TASK_ID="0c92e9c7-9bb3-496d-9e64-9af5d4587c4a"
curl "http://127.0.0.1:8000/tasks/${TASK_ID}"
```

当 `status` 为 `succeeded` 或 `failed` 时停止轮询。

## 6. 启动服务

```bash
.venv39/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

或：

```bash
python main.py
```

## 7. Python 依赖

基础依赖写在 `requirements.txt` 和 `pyproject.toml`：

```text
fastapi
uvicorn[standard]
httpx
pydantic
python-dotenv
trimesh
numpy
meshlib
```

安装示例：

```bash
python -m pip install -r requirements.txt
```

## 8. 外部/可选环境

| 组件 | 用途 | 配置 |
| --- | --- | --- |
| Blender | 材质、贴图、PBR、骨架、动画增强分析和贴图导出 | `BLENDER_BIN`，默认 `/Applications/Blender.app/Contents/MacOS/Blender` |
| MeshLib | 高质量几何检查、自相交等 native 指标 | Python 包 `meshlib` |
| trimesh | OBJ/STL/GLB 等 native 读取辅助 | Python 包 `trimesh` |
| OpenUSD / pxr | USD/USDZ native 读取 | 平台相关，可按部署环境单独安装 |
| Autodesk FBX SDK Python | FBX native 读取 | 平台相关，可按部署环境单独安装；未安装时会回退 Blender |

## 9. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOWNLOAD_DIR` | `downloads` | 临时下载目录 |
| `ASSET_DIR` | `downloads/assets` | 材质贴图临时静态资源目录 |
| `MAX_DOWNLOAD_BYTES` | `314572800` | 单文件最大下载字节数 |
| `MAX_CONCURRENT_JOBS` | `10` | 最大并发分析任务数 |
| `TASK_RETENTION_SECONDS` | `86400` | 成功/失败任务结果保留时间 |
| `PUBLIC_BASE_URL` | 空 | 对外可访问服务地址；配置后材质贴图返回完整 URL，例如 `http://34.219.48.53:8000/assets/...` |
| `BLENDER_BIN` | `/Applications/Blender.app/Contents/MacOS/Blender` | Blender 可执行文件路径 |
| `PORT` | `8000` | `python main.py` 启动端口 |
