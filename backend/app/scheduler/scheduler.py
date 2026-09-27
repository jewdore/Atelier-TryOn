import asyncio
import shutil
import signal
import time

from redis.exceptions import RedisError

from backend.app.config import settings
from backend.app.logging import configure, event
from backend.app.scheduler.worker import ACTIVE, JobStore, job_key, redis_client


async def cleanup(store: JobStore) -> None:
    if not settings.data_dir.exists():
        return
    for directory in settings.data_dir.glob('tryon_*'):
        if directory.is_symlink() or not directory.is_dir():
            continue
        if time.time() - directory.stat().st_mtime > 60 and not await store.redis.exists(job_key(directory.name)):
            await asyncio.to_thread(shutil.rmtree, directory)
    for directory in settings.data_dir.glob('video_*'):
        if directory.is_symlink() or not directory.is_dir():
            continue
        if time.time() - directory.stat().st_mtime > 300 and not await store.redis.exists('tryon:video:' + directory.name):
            await asyncio.to_thread(shutil.rmtree, directory)


async def main() -> None:
    configure()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            pass
    redis = redis_client()
    store = JobStore(redis)
    last_cleanup = 0.0
    try:
        while not stop.is_set():
            try:
                for job_id in await redis.smembers(ACTIVE):
                    await store.recover(job_id)
                async for key in redis.scan_iter('worker:*:status'):
                    await store.dispatch(int(key.split(':')[1]))
                await redis.set('tryon:scheduler:heartbeat', time.time(), ex=15)
                if time.monotonic() - last_cleanup > 30:
                    await cleanup(store)
                    last_cleanup = time.monotonic()
                await asyncio.sleep(0.05)
            except (RedisError, OSError) as exc:
                event('scheduler_retry', error=str(exc))
                await asyncio.sleep(2)
    finally:
        await redis.aclose()


if __name__ == '__main__':
    asyncio.run(main())
