# 视频换装 V1

## 使用

打开页面的“视频换装”，上传人物视频，点击右侧上装，等待完成后播放或下载 MP4。原有“图片换装”保留。

- 输入：单人 MP4 / MOV / WebM，最大 100MiB、最长 8 秒、最高 4096 × 2160 像素；规范化后至少 4 帧。
- 输出：384 × 512、12 FPS、H.264 MP4，保持时长至一帧误差，保持画面比例并补边。
- **输出无音轨**；不是实时直播。V1 仅开放上装，建议正面、动作缓慢、无遮挡。转身、大幅动作、遮挡及复杂衣服图案的质量需要真实素材验收。
- 使用 CatV2TON 时序模型，不是逐帧 CatVTON 拼接。24 帧分段、8 帧重叠、AdaCN、20 步、bf16；蒙版保护未换装区域。
- 切换衣服无需重新上传视频；连续点击时，同一会话未运行旧任务被替换，运行中的旧任务允许结束，但前端不会展示过时结果。
- 上传与结果默认 1 小时过期，清理器每 30 秒检查。任务用硬链接持有原视频，即使上传到期，也不会破坏排队或运行中的任务。
- 无账号、无鉴权，仅限可信内网。生产对公网前必须在入口增加鉴权、速率限制、TLS、磁盘配额和内容合规机制；不要把此版本直接暴露公网。

## GPU 分配与启动

视频模式：GPU 0–6 各一个 CatVTON 图片 worker；GPU 7 一个 CatV2TON 视频 worker。仍是单卡独立推理，不使用 TP。视频队列与图片队列隔离，耗时视频不会占据图片 worker。

首次在 Ubuntu 部署：

```bash
cp .env.example .env
docker compose -f docker-compose.yml build model-init
echo 'COMPOSE_FILE=docker-compose.yml:docker-compose.video.yml' >> .env
docker compose up -d --build
```

之后只需：

```bash
docker compose up -d
```

`worker/video.Dockerfile` 以 `virtual-tryon-worker:local` 为基底，所以首次必须先构建 `model-init`。镜像独立，视频依赖不会升级图片 worker 的 diffusers。模型 init 成功、视频模型加载和 8 帧 dummy inference 完成后，GPU 7 才注册 READY。首启下载约 6.2GiB 视频权重，复用已有 CatVTON 人体解析权重。

手动下载：

```bash
docker compose run --rm video-model-init
docker compose logs -f worker-gpu7
curl http://127.0.0.1:8000/api/health
```

模型缓存目录 `models/video-base`、`models/catv2ton`；运行时离线只读。`models/video-manifest.json` 记录快照版本和文件大小，第二次无需重复下载。网络受限时可在 `.env` 配置 `HF_ENDPOINT=https://hf-mirror.com`。

回到纯图片 8 卡：删除 `.env` 的 `COMPOSE_FILE` 行，然后执行 `docker compose -f docker-compose.yml up -d worker-gpu7`。不要同时启动同一 GPU 的两个 worker。

## API

### 上传视频

`POST /api/videos`，body 是原始视频二进制，**不是 base64 或 multipart**：

```bash
curl -X POST http://127.0.0.1:8000/api/videos \
  -H 'Content-Type: application/octet-stream' --data-binary @person.mp4
```

返回 201：`video_id`、`preview_url`、`duration_seconds`、`width`、`height`、`fps`、`frames`、`expires_in`。

上传流分块写磁盘，不将整个视频缓存在 Python 内存；解码进程有协议白名单、线程限制、时长/像素/帧数约束和超时。每个 API 进程最多两个同时上传/规范化任务。损坏视频返回 422，超限返回 413，容量已满返回 429。

### 创建视频任务

`POST /api/tryon/video`：

```json
{
  "video_id": "video_0123456789abcdef0123456789abcdef",
  "garment_id": "black_graphic_tee",
  "category": "upper_body",
  "session_id": "video-session-001",
  "sequence": 1
}
```

返回 202：`job_id`、`status: queued`、`kind: video`。

复用 `GET /api/tryon/{job_id}` 查询，包含 `phase`、`progress`、`gpu_id`、`timings` 和 `result_url`。进度为阶段估计，不是精确百分比或 ETA。默认排队超时 1800 秒，推理超时 1800 秒。

`GET /api/tryon/{job_id}/result` 返回 `video/mp4`，支持 HTTP Range，可浏览器播放/拖动；图片任务仍返回 `image/png`。`GET /api/videos/{video_id}` 获取规范化预览。

Redis 新增 `tryon:queue:video`、`tryon:video:{video_id}`。worker 注册 `kind=image|video`；调度器按类型取队列，保留 token/boot_id 栅栏、心跳、超时、崩溃重试。`/api/health` 增加 `image_workers`、`video_workers`、`video_queue_depth`；`/api/metrics` 增加视频队列深度。

## 验证和 Benchmark

```bash
python -m pytest -q
cd frontend && npm run build && cd ..
python scripts/benchmark.py --video person.mp4 --require-workers 1 \
  --concurrency 1 2 --rounds 2 --timeout 1800 --output reports/benchmark-video.json
```

GPU 7 只有一个视频 worker，因此并发 2 的第二个任务正常排队，并不意味着两路并行。图片 benchmark 在混合部署中应使用 `--require-workers 7`。报告含队列时延、预处理/推理/编码时间、吞吐和 GPU 采样。请在 GPU 主机执行 benchmark 才能采集 `nvidia-smi`。

`scripts/video-smoke.py` 在 GPU 容器运行最小模型验证：从示例照片构造 12 帧平移视频，再执行真实时序推理。**该素材只验证工程通路，不能代替真人运动视频质量验收。** 已部署实测见 `VIDEO-VALIDATION.md`。

## 源码及权重版本

- 官方仓库：`https://github.com/Zheng-Chong/CatV2TON`
- vendored commit：`d8abdab93c9e3ffc89f6f9e13dbbee6b88e85cfc`
- 基础模型：`alibaba-pai/EasyAnimateV4-XL-2-InP@0bdb0bfc02bfe5f5497fd30b55f79e2ddebb630b`
- 换装权重：`zhengchong/CatV2TON@bbf2a004905cc0a4a5834c11d25590909143a990`，`512-64K`。
- 官方 README 标记 CC BY-NC-SA 4.0；非商业研究使用，不把当前部署当作已有商业授权。基础模型和解析模型的条款也需分别检查。保留上游原始源码和许可说明。

## 后续扩展接口

`worker/video_model.py` 的 `VideoTryOnModel.load/warmup/predict` 与图片模型分离。以后接入 ASR/Jev，只需将语义映射成 `garment_id + video_id + session_id + sequence`，调用任务 API；当前不实现语音、LLM、WebRTC 或直播。扩视频并发时将更多物理 GPU 明确分配为视频 worker，不能让视频任务在图片 worker 内临时加载第二个模型。
