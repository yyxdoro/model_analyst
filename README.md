# 模型分析 API

用于远程 3D 模型文件的异步分析服务，支持 hybrid 分析：native MeshLib/trimesh 负责几何拓扑，Blender 负责材质/贴图/PBR/骨架/动画增强分析。

## 目录结构

```text
main.py                         # 兼容入口，仍支持 uvicorn main:app
src/model_analysis/api/         # FastAPI app 和请求 schema
src/model_analysis/core/        # 配置、路径、环境变量
src/model_analysis/services/    # 下载、任务、分析调度、质量状态
src/model_analysis/analyzers/   # native MeshLib/trimesh 分析器
src/model_analysis/expert/      # 专家规则和专业结论
scripts/                        # Blender 后台分析脚本
docs/                           # API 文档和指标说明
deploy/                         # systemd / nginx 部署样例
samples/models/                 # 本地样例模型
downloads/                      # 运行时下载和贴图临时资源，已忽略
```

## 本地启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/
```

当前服务器访问地址：

```text
http://34.219.48.53:8000
```

远程健康检查：

```bash
curl http://34.219.48.53:8000/
```

## 本地样例冒烟测试

```bash
python tests/smoke_local_models.py
```

测试会读取 `samples/models/` 下的 FBX 和 GLB，输出分析引擎、摘要、贴图分辨率和影响面分析。

## 服务器 git 部署

以下以 Amazon Linux / EC2 `ec2-user` 为例。

### 1. 安装系统依赖

Amazon Linux 2023：

```bash
sudo dnf update -y
sudo dnf install -y python3 python3-pip python3-devel git curl wget unzip nginx
```

Amazon Linux 2：

```bash
sudo yum update -y
sudo yum install -y python3 python3-pip python3-devel git curl wget unzip nginx
```

### 2. 克隆项目

```bash
sudo mkdir -p /opt
sudo chown -R ec2-user:ec2-user /opt
cd /opt
git clone https://github.com/yyxdoro/model_analyst.git model-analysis-api
cd /opt/model-analysis-api
```

### 3. 安装 Python 依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. 安装 Blender

Amazon Linux 默认仓库可能没有合适版本，推荐安装官方 Linux 包，并将 `BLENDER_BIN` 指向实际路径。

示例：

```bash
cd /opt
sudo wget https://download.blender.org/release/Blender4.3/blender-4.3.2-linux-x64.tar.xz
sudo tar -xf blender-4.3.2-linux-x64.tar.xz
sudo ln -sf /opt/blender-4.3.2-linux-x64/blender /usr/local/bin/blender
/usr/local/bin/blender --version
```

### 5. 配置环境变量

```bash
cd /opt/model-analysis-api
cp .env.example .env
nano .env
```

至少确认：

```env
PORT=8000
BLENDER_BIN=/usr/local/bin/blender
DOWNLOAD_DIR=downloads
ASSET_DIR=downloads/assets
TASK_RETENTION_SECONDS=86400
PUBLIC_BASE_URL=http://34.219.48.53:8000
```

不要把真实 `.env` 提交到 git。

### 6. 启动测试

```bash
source .venv/bin/activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

另开终端测试：

```bash
curl http://127.0.0.1:8000/
```

### 7. systemd 常驻运行

```bash
sudo cp deploy/model-analysis-api.service.example /etc/systemd/system/model-analysis-api.service
sudo systemctl daemon-reload
sudo systemctl enable model-analysis-api
sudo systemctl start model-analysis-api
sudo systemctl status model-analysis-api
```

日志：

```bash
journalctl -u model-analysis-api -f
```

### 8. Nginx 反向代理

```bash
sudo cp deploy/nginx.model-analysis-api.conf.example /etc/nginx/conf.d/model-analysis-api.conf
sudo nano /etc/nginx/conf.d/model-analysis-api.conf
sudo nginx -t
sudo systemctl restart nginx
```

把配置里的 `your-domain.com` 改成你的域名或服务器公网 IP。

## 接口文档

- 服务地址：`http://34.219.48.53:8000`
- Swagger UI：`http://34.219.48.53:8000/docs`
- API：`docs/API.md`
- 专业指标：`docs/metrics.md`

## 重要返回字段

- 原始模型链接：`result.report.model.source_url`
- 分析引擎：`result.report.model.analysis_engine`
- 点面数：`result.report.geometry`
- 材质图：`result.report.materials[].textures[].url`
- 专业结论：`result.report.professional_analysis`
- 错误码：失败任务的 `error.code`
