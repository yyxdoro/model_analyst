# 模型分析 API 接口文档

## 服务说明

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
curl -X POST http://127.0.0.1:8000/analyze \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/model.glb"}'
```

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
    "standard": {
      "is_standard": false,
      "label": "不标准",
      "severity": "red",
      "metrics": {
        "faces": 1445656,
        "non_manifold_edge_count": 0,
        "zero_area_faces": 0
      },
      "reasons": ["面数超过 1,000,000（当前 1445656）"],
      "reason_text": "面数超过 1,000,000（当前 1445656）"
    },
    "expert_analysis": {
      "passed": false,
      "level": "fail",
      "conclusion": "模型未完全满足专业3D质量标准...",
      "model_type_profile": {
        "textured_model": true,
        "pbr_model": true,
        "detected_types": ["贴图模型", "PBR材质模型"]
      },
      "issues": [],
      "coverage_notes": []
    },
    "report": {
      "model": {
        "source_url": "https://example.com/model.glb",
        "file_name": "model.glb",
        "analysis_engine": "hybrid"
      },
      "geometry": {
        "mesh_count": 1,
        "vertices": 750256,
        "faces": 1445656,
        "triangles": 1445656,
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
              "url": "/assets/0c92e9c7-9bb3-496d-9e64-9af5d4587c4a/Body_Base_Color_BaseColor.png",
              "asset_file": "Body_Base_Color_BaseColor.png"
            }
          ]
        }
      ],
      "quality": {
        "label": "不标准",
        "severity": "red",
        "metrics": {
          "faces": 1445656,
          "non_manifold_edge_count": 0,
          "zero_area_faces": 0
        },
        "reasons": ["面数超过 1,000,000（当前 1445656）"]
      },
      "professional_analysis": {
        "conclusion": "模型未完全满足专业3D质量标准...",
        "impact_analysis": [],
        "issues": [],
        "coverage_notes": []
      },
      "validation": {
        "geometry_matches_computed_metrics": true,
        "quality_metrics_match_geometry": true,
        "texture_count_matches_materials": true,
        "analysis_engine": "hybrid",
        "passed": true
      }
    },
    "result": {
      "source_url": "https://example.com/model.glb",
      "file_name": "model.glb",
      "analysis_engine": "hybrid",
      "asset_retention_seconds": 86400,
      "assets_expires_at": 1791285910.34,
      "analysis": {
        "analyzer": "hybrid_native_blender",
        "engines": {
          "primary": "hybrid",
          "geometry": "native_meshlib_full_fidelity",
          "materials": "blender"
        },
        "analysis_errors": [],
        "native": {},
        "blender": {},
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

- 标准化贴图链接位于 `result.report.materials[].textures[].url`
- 原始 Blender 贴图链接位于 `result.result.analysis.materials[].textures[].image.url`
- 链接为服务内临时静态资源地址，例如 `/assets/{task_id}/{asset_file}`
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
| `BLENDER_BIN` | `/Applications/Blender.app/Contents/MacOS/Blender` | Blender 可执行文件路径 |
| `PORT` | `8000` | `python main.py` 启动端口 |
