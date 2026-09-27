# Validation summary

This document records a reproducible engineering validation for the project. It intentionally omits private hostnames, IP addresses, SSH paths, container names, and generated user media.

## Reference environment

- Ubuntu 22.04
- 8 NVIDIA RTX 6000D GPUs with approximately 83 GiB per GPU
- NVIDIA driver 590.48.01
- Docker 29.1.3 and Docker Compose 2.40.3
- PyTorch 2.7.1 + CUDA 12.8
- torchvision 0.22.1, diffusers 0.31.0, transformers 4.46.3

## Image validation

- CUDA GEMM and torchvision CUDA NMS passed.
- CatVTON model loading, AutoMasker import, warmup, and image generation passed.
- Eight independent image workers each used one physical GPU; no tensor parallelism.
- Scheduler assignment, ninth-job queueing, latest-request-wins, worker crash recovery, Redis reconnect, timeout handling, TTL cleanup, and fenced result commits passed.
- Browser checks passed for image upload, repeated garment selection, stale-result suppression, and mobile layout without horizontal overflow.

Reference image configuration: 576 × 768, 20 inference steps. On the reference 8-GPU host, a representative concurrency-8 run completed 24/24 jobs with approximately 2.70 seconds average end-to-end latency. Treat this as a smoke benchmark, not an SLA.

## Video validation

Video validation is documented separately in [VIDEO-VALIDATION.md](VIDEO-VALIDATION.md). The video path uses CatV2TON temporal inference and an isolated video queue; it does not silently fall back to frame-by-frame CatVTON.

## Reproduce

```bash
python -m pytest -q
cd frontend && npm ci && npm run build
cd ..
python scripts/benchmark.py --concurrency 1 2 4 8 --rounds 3
```

Run benchmarks on the GPU host to collect server-side `nvidia-smi` samples. Do not commit generated reports or personal media to a public repository.

## Limitations

- No authentication or public-internet security gateway.
- No long-duration soak test or adversarial upload-flood test.
- Model and wardrobe quality varies with pose, occlusion, body shape, lighting, and garment category.
- Third-party model, parser, base-model, and asset licenses must be reviewed before commercial use.
