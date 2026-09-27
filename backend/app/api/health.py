from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from redis.exceptions import RedisError

from backend.app.scheduler.worker import METRICS, QUEUE, queue_key

router = APIRouter()


@router.get('/api/health')
async def health(request: Request) -> JSONResponse:
    redis = request.app.state.redis
    try:
        await redis.ping()
        workers = [await redis.hgetall(key) async for key in redis.scan_iter('worker:*:status')]
        ready = [worker for worker in workers if worker.get('status') in {'idle', 'busy'}]
        scheduler = bool(await redis.exists('tryon:scheduler:heartbeat'))
        return JSONResponse({'status': 'ok' if ready and scheduler else 'starting', 'redis': True,
            'scheduler': scheduler, 'ready_workers': len(ready), 'workers': workers,
            'image_workers': sum(worker.get('kind', 'image') == 'image' for worker in ready),
            'video_workers': sum(worker.get('kind') == 'video' for worker in ready),
            'video_queue_depth': await redis.llen(queue_key('video')),
            'queue_depth': await redis.llen(QUEUE)}, status_code=200 if ready and scheduler else 503)
    except RedisError:
        return JSONResponse({'status': 'unavailable', 'redis': False}, status_code=503)


@router.get('/api/metrics', response_class=PlainTextResponse)
async def metrics(request: Request) -> PlainTextResponse:
    redis = request.app.state.redis
    values = await redis.hgetall(METRICS)
    lines = []
    for field, name in [('requests', 'tryon_requests_total'), ('failed', 'tryon_requests_failed_total'),
                        ('completed', 'tryon_requests_completed_total'), ('superseded', 'tryon_requests_superseded_total'),
                        ('retries', 'tryon_retries_total')]:
        lines += [f'# TYPE {name} counter', f'{name} {values.get(field, 0)}']
    for field, name in [('inference_time_ms', 'tryon_inference_seconds'), ('queue_time_ms', 'tryon_queue_seconds')]:
        lines += [f'# TYPE {name} summary', f'{name}_sum {values.get(field, 0)}',
                  f'{name}_count {values.get("timed", 0)}']
    lines += ['# TYPE tryon_queue_depth gauge', f'tryon_queue_depth {await redis.llen(QUEUE)}',
              '# TYPE tryon_video_queue_depth gauge', f'tryon_video_queue_depth {await redis.llen(queue_key("video"))}',
              '# TYPE tryon_worker_busy gauge']
    async for key in redis.scan_iter('worker:*:status'):
        worker = await redis.hgetall(key)
        if worker:
            lines.append(f'tryon_worker_busy{{gpu_id="{int(worker["gpu_id"])}"}} {int(worker["status"] == "busy")}')
    return PlainTextResponse('\n'.join(lines) + '\n', media_type='text/plain; version=0.0.4')
