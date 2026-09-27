import asyncio
import os
import signal
import time
from uuid import uuid4

from PIL import Image
from redis.exceptions import RedisError

from backend.app.config import settings
from backend.app.logging import configure, event
from backend.app.scheduler.worker import JobStore, redis_client, worker_key
from backend.app.storage.storage import job_dir, save_image
from worker.model import TryOnModel, create_model
from worker.video_model import VideoTryOnModel, CatV2TONModel, Progress


def execute(model: TryOnModel | VideoTryOnModel, job: dict[str, str],
            progress: Progress | None = None) -> tuple[str, dict[str, float]]:
    started = time.perf_counter()
    if job.get('kind') == 'video':
        filename = job['token'] + '.mp4'
        model.predict(job_dir(job['job_id']) / 'source.mp4', settings.garment_dir / job['garment_path'],
            job['category'], job_dir(job['job_id']) / filename, progress or (lambda phase, percent: None))
        return filename, {**model.timings, 'queue_time_ms': float(job['queue_time_ms']),
            'worker_time_ms': (time.perf_counter() - started) * 1000,
            'total_latency_ms': (time.time() - float(job['created_at'])) * 1000}
    with Image.open(job_dir(job['job_id']) / 'person.png') as person, Image.open(settings.garment_dir / job['garment_path']) as garment:
        image = model.tryon(person, garment, job['category'])
    post_started = time.perf_counter()
    filename = job['token'] + '.png'
    save_image(image, job_dir(job['job_id']) / filename)
    timings = {**model.timings, 'queue_time_ms': float(job['queue_time_ms']),
        'postprocess_time_ms': (time.perf_counter() - post_started) * 1000,
        'worker_time_ms': (time.perf_counter() - started) * 1000,
        'total_latency_ms': (time.time() - float(job['created_at'])) * 1000}
    return filename, timings


async def main() -> None:
    configure()
    gpu, boot = settings.gpu_id, uuid4().hex
    event('Loading model', model=settings.model_name, gpu_id=gpu)
    model = CatV2TONModel() if settings.worker_kind == 'video' else create_model()
    await asyncio.to_thread(model.load)
    event('Model loaded', gpu_id=gpu)
    await asyncio.to_thread(model.warmup)
    event('Warmup complete', gpu_id=gpu)
    redis = redis_client()
    store = JobStore(redis)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def shutdown(signum: int, frame: object) -> None:
        event('shutdown_requested', gpu_id=gpu, signal=signum)
        loop.call_soon_threadsafe(stop.set)

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, shutdown)
    while not stop.is_set():
        try:
            if await store.register(gpu, boot):
                break
        except RedisError as exc:
            event('registration_retry', gpu_id=gpu, error=str(exc))
        await asyncio.sleep(2)
    event('READY', gpu_id=gpu, boot_id=boot, model=settings.model_name)

    async def heartbeat() -> None:
        last_success = time.monotonic()
        while True:
            try:
                if not await store.heartbeat(gpu, boot):
                    event('lease_lost_exit', gpu_id=gpu)
                    os._exit(1)
                last_success = time.monotonic()
            except RedisError as exc:
                event('heartbeat_retry', gpu_id=gpu, error=str(exc))
                if time.monotonic() - last_success > settings.lease_seconds - settings.heartbeat_seconds:
                    os._exit(1)
            await asyncio.sleep(settings.heartbeat_seconds)

    heartbeats = asyncio.create_task(heartbeat())
    try:
        while not stop.is_set():
            try:
                state = await redis.hgetall(worker_key(gpu))
                if state.get('boot_id') != boot or state.get('status') == 'unhealthy':
                    raise RuntimeError('Worker fenced by scheduler')
                if state.get('status') != 'busy':
                    await asyncio.sleep(0.05)
                    continue
                job = await store.get(state['job_id'])
                if job.get('token') != state['token'] or job.get('status') != 'running':
                    raise RuntimeError('Assignment revoked')
                event('inference_started', gpu_id=gpu, job_id=job['job_id'], request_id=job['request_id'])
                try:
                    def progress(phase: str, percent: int) -> None:
                        future = asyncio.run_coroutine_threadsafe(store.progress(job, phase, percent), loop)
                        try:
                            future.result(timeout=7)
                        except Exception:
                            future.cancel()

                    filename, timings = await asyncio.wait_for(asyncio.to_thread(execute, model, job, progress), store.timeouts(job)[1])
                    while True:
                        try:
                            committed = await store.finish(job, result_file=filename, timings=timings)
                            break
                        except RedisError:
                            await asyncio.sleep(1)
                    if not committed:
                        (job_dir(job['job_id']) / filename).unlink(missing_ok=True)
                    event('inference_complete', gpu_id=gpu, job_id=job['job_id'], request_id=job['request_id'], committed=committed, **timings)
                except TimeoutError:
                    event('inference_timeout_exit', gpu_id=gpu, job_id=job['job_id'])
                    os._exit(1)
                except Exception as exc:
                    event('inference_failed', gpu_id=gpu, job_id=job['job_id'], error=repr(exc))
                    await store.finish(job, error='inference_failed')
                    raise
            except RedisError as exc:
                event('worker_redis_retry', gpu_id=gpu, error=str(exc))
                await asyncio.sleep(1)
    finally:
        heartbeats.cancel()
        await asyncio.gather(heartbeats, return_exceptions=True)
        try:
            await redis.eval("if redis.call('HGET', KEYS[1], 'boot_id') == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end", 1, worker_key(gpu), boot)
        except RedisError:
            pass
        await redis.aclose()
        event('worker_stopped', gpu_id=gpu)


if __name__ == '__main__':
    asyncio.run(main())
