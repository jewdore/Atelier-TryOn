# Video validation summary

This document records a reproducible engineering validation and intentionally omits private hostnames, IP addresses, SSH paths, container names, and generated user media.

## Verified

- CatV2TON official source and pinned weights load successfully on CUDA.
- Model warmup, temporal inference, H.264 encoding, MP4 playback, HTTP Range delivery, and result download passed.
- Video workers are isolated from image workers and use a dedicated Redis queue.
- Upload validation covers streamed writes, format checks, duration, resolution, frame limits, timeout, cleanup, and expired assets.
- Scheduler tests cover video-pool isolation, queue timeout, latest-request-wins across modalities, crash recovery, progress fencing, and stale result suppression.
- Browser checks passed for upload, garment selection, video playback, repeated switching, and mobile layout without horizontal overflow.

## Reference measurements

Configuration: 384 × 512, 12 FPS, 20 inference steps, one video GPU.

| Test input | Concurrency | Successful | Average end-to-end | P95 | Average queue |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 second / 12 frames | 1 | 2/2 | 7.68 s | 7.70 s | 0.053 s |
| 1 second / 12 frames | 2 | 4/4 | 13.27 s | 15.26 s | 5.70 s |
| 8 seconds / 96 frames | 1 | 1/1 | 81.70 s | single sample | 0.008 s |
| Image request while video runs | 1 | 1/1 | 2.90 s | single sample | 0.348 s |

The 8-second run reached 100% sampled GPU utilization and approximately 22.4 GiB peak GPU memory. Model initialization took about 59 seconds and warmup about 3.3 seconds. A single video GPU serializes concurrent video jobs; concurrency 2 therefore measures queueing, not two-way video parallelism.

The test video was synthesized from a still image and looped. Compute, API, and GPU measurements are real, but these samples do not represent quality on real human motion, turning, occlusion, or difficult clothing patterns. Authorized real-motion quality evaluation remains a follow-up task.

## Reproduce

```bash
python scripts/video-smoke.py
python scripts/benchmark.py --video person.mp4 \
  --require-workers 1 --concurrency 1 2 --rounds 2 --timeout 1800
```

## Limitations

- V1 supports short single-person upper-body try-on only.
- Output is H.264 MP4 at 384 × 512 and 12 FPS with no audio track.
- Progress is a phase estimate, not an ETA.
- The current project is a prototype and has no authentication or public-internet security gateway.
