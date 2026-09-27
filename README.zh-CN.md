# Atelier TryOn

**基于独立 GPU Worker 的图片与视频虚拟试衣平台。**

[English](README.md) · [视频部署指南](VIDEO.md) · [验证记录](VALIDATION.md) · [支持项目](SUPPORT.md)

Atelier TryOn 是一个可自托管的虚拟试衣工程项目，支持上传人物照片或短视频，从本地衣橱选择服装，并通过异步任务生成换装结果。

> 本仓库是工程与研究原型，不是已经开放给公众使用的在线服务，适合私有部署、研究和产品原型验证。

## 特性

- 使用 [CatVTON](https://github.com/Zheng-Chong/CatVTON) 进行图片换装。
- 使用 [CatV2TON](https://github.com/Zheng-Chong/CatV2TON) 进行时序视频换装，不是逐帧图片拼接。
- 每张物理 GPU 一个独立推理 Worker，不使用八卡 TP。
- FastAPI + Redis 队列 + Scheduler + 常驻模型进程。
- 快速切换衣服时采用 `latest request wins`，旧结果不会覆盖最新选择。
- Worker 心跳、租约、崩溃恢复、token/boot 栅栏、超时、重试和 TTL 清理。
- 本地衣橱自动扫描，不依赖业务数据库。
- Next.js / React / TypeScript 前端，同时支持图片和视频模式。

## 架构

```text
浏览器
   │
   ├── 图片上传 + 选择服装
   └── 视频上传 + 选择服装
               │
               ▼
          FastAPI API
               │
               ▼
            Redis 队列
          ┌────┴────┐
          ▼         ▼
       图片队列   视频队列
          │         │
       GPU 0–6   GPU 7（示例）
     CatVTON×7  CatV2TON×1
```

视频 Worker 与图片 Worker 隔离，长视频任务不会阻塞低延迟图片队列。扩展视频并发时，必须显式把更多物理 GPU 分配给视频 Worker。

## 快速启动

### 环境要求

- Ubuntu 22.04 或兼容 Linux
- NVIDIA Driver、Docker Engine、Docker Compose v2、NVIDIA Container Toolkit
- 显存满足所选模型和分辨率要求的 NVIDIA GPU
- 可访问 Hugging Face，或准备可信的内部镜像/模型缓存

### 只启动图片服务

```bash
git clone https://github.com/jewdore/Atelier-TryOn.git
cd Atelier-TryOn
cp .env.example .env
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/api/health
```

Worker 完成模型加载和预热并报告 `READY` 后，打开 `http://SERVER_IP:3000`。

### 启动图片 + 视频服务

视频 overlay 默认将一张物理 GPU 分配给 CatV2TON，其余 GPU 保留给 CatVTON 图片 Worker。若机器 GPU 编号不同，请修改 Compose 中的设备分配。

```bash
docker compose -f docker-compose.yml -f docker-compose.video.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.video.yml ps
```

首次启动会把数 GB 模型下载到 `models/`。模型目录是运行时缓存，已被 Git 忽略。视频限制、API、部署细节和已知问题见 [VIDEO.md](VIDEO.md)。

## 目录结构

```text
backend/                 FastAPI 路由、schema、存储和调度器
worker/                  图片/视频模型适配器和常驻 Worker
frontend/                Next.js / React / TypeScript 前端
vendor/                  固定版本的上游模型源码快照
garments/                本地衣橱图片和元数据
scripts/                 模型下载、健康检查、smoke test、benchmark
tests/                   调度、API、上传和恢复测试
docker-compose.yml       图片 Worker 部署
docker-compose.video.yml 图片 + 独立视频 Worker overlay
```

## API 概览

### 图片换装

```http
POST /api/tryon
GET  /api/tryon/{job_id}
GET  /api/tryon/{job_id}/result
```

```json
{
  "person_image": "base64...",
  "garment_id": "black_graphic_tee",
  "category": "upper_body",
  "session_id": "browser-session-id",
  "sequence": 1
}
```

### 视频换装

```http
POST /api/videos
POST /api/tryon/video
GET  /api/videos/{video_id}
GET  /api/tryon/{job_id}
GET  /api/tryon/{job_id}/result
```

视频上传使用流式二进制请求，不使用 base64：

```bash
curl -X POST http://127.0.0.1:8000/api/videos \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @person.mp4
```

上传接口返回 `video_id` 后，再创建视频任务；状态和结果继续复用统一 Job API。V1 只支持短视频、单人、上装换装，输出 MP4 且不保留音轨。

## 性能与验证

```bash
python -m pytest -q
cd frontend && npm ci && npm run build
```

图片 benchmark：

```bash
python scripts/benchmark.py --concurrency 1 2 4 8 16 --rounds 3
```

视频 benchmark：

```bash
python scripts/benchmark.py --video person.mp4 \
  --require-workers 1 --concurrency 1 2 --rounds 2 --timeout 1800
```

报告包含平均值、P50、P95、P99、吞吐、队列延迟、GPU 编号、GPU 利用率和显存采样。当前参考数据见 `VALIDATION.md` 和 `VIDEO-VALIDATION.md`。

## 安全与隐私

- V1 没有账号和鉴权。
- 不要把 API 直接暴露到公网；公网部署前必须增加 TLS、鉴权、限流、上传治理、磁盘配额和内容审核。
- 不要提交 `.env`、模型缓存、生成图片/视频、私有报告或个人媒体。
- 只使用已经获得授权的人物照片和服装素材。
- 上传媒体与结果属于敏感运行数据，应单独保护。

## 模型和素材许可

应用代码、上游代码快照、模型权重、基础模型、人体解析模型和衣橱图片可能适用不同许可。CatVTON 和 CatV2TON 上游项目材料中标注了非商业/同源许可限制；商业使用前必须逐项核实，不能把本仓库视为第三方模型和素材的商业授权。

请查看：`vendor/CatVTON/LICENSE`、`vendor/CatVTON/README.md`、`vendor/CatV2TON/README.md`、`garments/ASSETS.md`。

## 支持项目

如果 Atelier TryOn 对你的研究或原型有帮助，最有价值的支持方式是：

1. Star 仓库，并分享可复现的 benchmark。
2. 提交聚焦 Issue，包含硬件、驱动、模型版本、输入限制和不含私有媒体的日志。
3. 提交小型 Pull Request：测试、部署修复、模型适配器、UI 或文档改进。
4. 提供已经授权的服装/视频样本或质量报告。
5. Buy Me a Coffee 页面启用后，再通过赞助支持持续开发。

目前不会在仓库里放未经确认的收款用户名，避免把捐助导向错误账户。具体启用方案见 [SUPPORT.md](SUPPORT.md)。

## 路线图

- 增加视频 GPU Worker 和公平调度
- 保留视频音轨
- 提升时序一致性和遮挡处理
- 支持更多衣服类别
- 账号与多用户隔离
- 使用已授权真人运动视频进行质量评估
- 可选 ASR/Jev 接入

## 贡献

大型架构修改前请先开 Issue。模型集成应保持适配器边界，不能让视频任务阻塞图片队列；调度器或 API 改动需要补充测试。

## 许可证说明

本项目没有对第三方源码快照、模型权重和素材作统一授权声明。重新分发或商业部署前请逐项阅读上游许可。如果未来要为原创应用代码采用宽松许可证，请先把它与受限的 vendored 内容分离。
