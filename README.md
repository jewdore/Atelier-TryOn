# Atelier TryOn

**Image and video virtual try-on with independent GPU workers.**

[中文文档](README.zh-CN.md) · [Video guide](VIDEO.md) · [Validation](VALIDATION.md) · [Support](SUPPORT.md)

Atelier TryOn is a self-hosted virtual try-on platform for image and short-video clothing replacement. Upload a person image or video, choose an item from a local wardrobe, and submit an asynchronous try-on job.

> This is an engineering and research prototype, not a hosted public service.

## Highlights

- Image try-on powered by [CatVTON](https://github.com/Zheng-Chong/CatVTON).
- Temporal video try-on powered by [CatV2TON](https://github.com/Zheng-Chong/CatV2TON), not frame-by-frame image compositing.
- One independent inference worker per physical GPU; no tensor parallelism.
- FastAPI, Redis queues, a scheduler, and long-lived model workers.
- Latest-request-wins behavior for quickly switching garments.
- Worker heartbeats, leases, crash recovery, fenced result commits, timeouts, retries, and TTL cleanup.
- Local wardrobe discovery without an application database.
- Next.js / React / TypeScript frontend with image and video modes.

## Architecture

```text
Browser
   │
   ├── image upload + garment selection
   └── video upload + garment selection
               │
               ▼
        FastAPI API gateway
               │
               ▼
          Redis queues
          ┌────┴────┐
          ▼         ▼
   image queue   video queue
          │         │
    GPUs 0–6    GPU 7 (example)
   CatVTON × 7  CatV2TON × 1
```

Video workers are isolated from image workers so a long video job does not block the low-latency image queue.

## Quick start

### Requirements

- Ubuntu 22.04 or a compatible Linux host
- NVIDIA driver, Docker Engine, Docker Compose v2, and NVIDIA Container Toolkit
- NVIDIA GPU memory suitable for the selected model and resolution
- Hugging Face access, or a trusted internal mirror/cache

### Image-only deployment

```bash
git clone https://github.com/jewdore/Atelier-TryOn.git
cd Atelier-TryOn
cp .env.example .env
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/api/health
```

Open `http://SERVER_IP:3000` after the workers report `READY`.

### Image + video deployment

The video overlay reserves one physical GPU for CatV2TON and leaves the other GPUs for CatVTON image workers. Edit the GPU assignment in Compose if your host uses a different layout.

```bash
docker compose -f docker-compose.yml -f docker-compose.video.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.video.yml ps
```

The first model initialization downloads several gigabytes into `models/`. These runtime caches are intentionally ignored by Git. Read [VIDEO.md](VIDEO.md) for video limits, API examples, and known limitations.

## Project layout

```text
backend/                 FastAPI routes, schemas, storage, scheduler
worker/                  Image/video model adapters and long-lived workers
frontend/                Next.js / React / TypeScript UI
vendor/                  Pinned upstream model source snapshots
garments/                Local wardrobe images and metadata
scripts/                 Model download, health, smoke, and benchmark tools
tests/                   Scheduler, API, upload, and recovery tests
docker-compose.yml       Image-worker deployment
docker-compose.video.yml Image + dedicated video-worker overlay
```

## API overview

### Image try-on

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

### Video try-on

```http
POST /api/videos
POST /api/tryon/video
GET  /api/videos/{video_id}
GET  /api/tryon/{job_id}
GET  /api/tryon/{job_id}/result
```

Video upload uses a streamed binary request instead of base64:

```bash
curl -X POST http://127.0.0.1:8000/api/videos \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @person.mp4
```

The video task references the returned `video_id`, then uses the same job status and result endpoints. Video V1 is bounded to short, single-person, upper-body try-on and produces an MP4 without an audio track.

## Testing and benchmarks

```bash
python -m pytest -q
cd frontend && npm ci && npm run build
```

Image benchmark:

```bash
python scripts/benchmark.py --concurrency 1 2 4 8 16 --rounds 3
```

Video benchmark:

```bash
python scripts/benchmark.py --video person.mp4 \
  --require-workers 1 --concurrency 1 2 --rounds 2 --timeout 1800
```

Reports include latency percentiles, throughput, queue time, GPU IDs, utilization, and memory samples. See [VALIDATION.md](VALIDATION.md) and [VIDEO-VALIDATION.md](VIDEO-VALIDATION.md) for reference measurements.

## Security and privacy

- V1 has no user accounts or authentication.
- Do not expose the API directly to the public internet without TLS, authentication, rate limiting, upload governance, disk quotas, and content moderation.
- Do not commit `.env`, model caches, generated media, private reports, or personal media.
- Use only person images and garment assets for which you have permission.
- Treat uploaded media and generated results as sensitive runtime data.

## Model and asset licensing

Application code, upstream source snapshots, model weights, base models, parser models, and wardrobe images may have different licenses. CatVTON and CatV2TON project materials identify non-commercial/share-alike restrictions. Review every upstream license before commercial use; this repository does not grant commercial rights to third-party models or assets.

See `vendor/CatVTON/LICENSE`, `vendor/CatVTON/README.md`, `vendor/CatV2TON/README.md`, and `garments/ASSETS.md`.

## Support the project

If this project helps you, [support Atelier TryOn on Afdian](https://afdian.com/a/jerry). Voluntary contributions help with development, GPU testing, and documentation; they do not purchase model licenses, inference access, or guaranteed support.

You can also help with a reproducible benchmark, a focused sanitized issue, a small pull request, or authorized garment/video quality data. See [SUPPORT.md](SUPPORT.md).

## Roadmap

- More video GPU workers and fair scheduling
- Audio-preserving video output
- Better temporal consistency and occlusion handling
- More garment categories
- Authentication and multi-user isolation
- Quality evaluation on authorized real-motion clips
- Optional ASR/Jev integration

## Contributing

Please open an issue before large architectural changes. Keep model integrations behind stable adapters, preserve image/video queue separation, and add tests for scheduler or API behavior.

## License note

There is no blanket license for third-party source snapshots, model weights, or assets. Read the upstream notices before redistribution or commercial deployment.
