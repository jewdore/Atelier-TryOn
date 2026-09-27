import json
import time
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import WatchError

from backend.app.config import Settings, settings

QUEUE = 'tryon:queue'
ACTIVE = 'tryon:active'
METRICS = 'tryon:metrics'


def queue_key(kind: str = 'image') -> str:
    return QUEUE + ':video' if kind == 'video' else QUEUE


def job_key(job_id: str) -> str:
    return f'tryon:job:{job_id}'


def worker_key(gpu: int) -> str:
    return f'worker:{gpu}:status'


class JobStore:
    def __init__(self, redis: Redis, config: Settings = settings):
        self.redis = redis
        self.config = config

    async def get(self, job_id: str) -> dict[str, str]:
        return await self.redis.hgetall(job_key(job_id))

    async def enqueue(self, job: dict[str, Any]) -> str:
        session = 'tryon:session:' + job['session_id']
        queue = queue_key(job.get('kind', 'image'))
        queue_timeout, inference_timeout = self.timeouts(job)
        while True:
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(session, queue)
                    previous = await pipe.hgetall(session)
                    if previous and int(previous['sequence']) >= int(job['sequence']):
                        return 'stale_sequence'
                    old_key = job_key(previous['job_id']) if previous else 'tryon:absent'
                    await pipe.watch(old_key)
                    old = await pipe.hgetall(old_key)
                    replacing = old.get('status') == 'queued'
                    if await pipe.llen(queue) >= self.config.max_queue and not (replacing and queue_key(old.get('kind', 'image')) == queue):
                        return 'queue_full'
                    pipe.multi()
                    if replacing:
                        pipe.lrem(queue_key(old.get('kind', 'image')), 0, previous['job_id'])
                        pipe.hset(old_key, mapping={'status': 'failed', 'error': 'superseded'})
                        pipe.expire(old_key, self.config.result_ttl)
                        pipe.srem(ACTIVE, previous['job_id'])
                        pipe.hincrby(METRICS, 'superseded', 1)
                    pipe.hset(session, mapping={'sequence': job['sequence'], 'job_id': job['job_id']})
                    pipe.expire(session, self.config.result_ttl + queue_timeout + inference_timeout)
                    pipe.hset(job_key(job['job_id']), mapping={**job, 'status': 'queued', 'attempts': 0})
                    pipe.sadd(ACTIVE, job['job_id'])
                    pipe.rpush(queue, job['job_id'])
                    pipe.hincrby(METRICS, 'requests', 1)
                    await pipe.execute()
                    return 'queued'
                except WatchError:
                    continue

    async def register(self, gpu: int, boot: str) -> bool:
        key = worker_key(gpu)
        while True:
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    if await pipe.exists(key):
                        return False
                    pipe.multi()
                    pipe.hset(key, mapping={'worker_id': f'worker-{gpu}', 'gpu_id': gpu,
                        'model': self.config.model_name, 'status': 'idle', 'boot_id': boot,
                        'kind': self.config.worker_kind,
                        'heartbeat': time.time(), 'job_id': '', 'token': ''})
                    pipe.expire(key, self.config.lease_seconds)
                    await pipe.execute()
                    return True
                except WatchError:
                    continue

    async def heartbeat(self, gpu: int, boot: str) -> bool:
        key = worker_key(gpu)
        while True:
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    if await pipe.hget(key, 'boot_id') != boot:
                        return False
                    pipe.multi()
                    pipe.hset(key, 'heartbeat', time.time())
                    pipe.expire(key, self.config.lease_seconds)
                    await pipe.execute()
                    return True
                except WatchError:
                    continue

    async def dispatch(self, gpu: int) -> str | None:
        key = worker_key(gpu)
        while True:
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    worker = await pipe.hgetall(key)
                    if worker.get('status') != 'idle':
                        return None
                    queue = queue_key(worker.get('kind', 'image'))
                    await pipe.watch(queue)
                    job_id = await pipe.lindex(queue, 0)
                    if not job_id:
                        return None
                    target = job_key(job_id)
                    await pipe.watch(target)
                    job = await pipe.hgetall(target)
                    if job.get('status') != 'queued':
                        pipe.multi()
                        pipe.lpop(queue)
                        await pipe.execute()
                        continue
                    now = time.time()
                    if now - float(job['created_at']) > self.timeouts(job)[0]:
                        pipe.multi()
                        pipe.lpop(queue)
                        pipe.hset(target, mapping={'status': 'failed', 'error': 'queue_timeout'})
                        pipe.expire(target, self.config.result_ttl)
                        pipe.srem(ACTIVE, job_id)
                        pipe.hincrby(METRICS, 'failed', 1)
                        await pipe.execute()
                        continue
                    token = uuid4().hex
                    pipe.multi()
                    pipe.lpop(queue)
                    pipe.hset(target, mapping={'status': 'running', 'gpu_id': gpu,
                        'boot_id': worker['boot_id'], 'token': token, 'started_at': now,
                        'queue_time_ms': (now - float(job['created_at'])) * 1000})
                    pipe.hincrby(target, 'attempts', 1)
                    pipe.hset(key, mapping={'status': 'busy', 'job_id': job_id, 'token': token})
                    await pipe.execute()
                    return job_id
                except WatchError:
                    continue

    async def finish(self, job: dict[str, str], *, error: str = '', result_file: str = '',
                     timings: dict[str, float] | None = None) -> bool:
        target = job_key(job['job_id'])
        key = worker_key(int(job['gpu_id']))
        while True:
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(target, key)
                    current = await pipe.hgetall(target)
                    worker = await pipe.hgetall(key)
                    if current.get('status') != 'running' or current.get('token') != job['token']:
                        return False
                    if worker.get('boot_id') != job['boot_id'] or worker.get('token') != job['token']:
                        return False
                    pipe.multi()
                    pipe.hset(target, mapping={'status': 'failed' if error else 'completed',
                        'phase': 'failed' if error else 'completed', 'progress': 100 if not error else 0,
                        'error': error, 'result_file': result_file, 'timings': json.dumps(timings or {}),
                        'finished_at': time.time()})
                    pipe.expire(target, self.config.result_ttl)
                    pipe.srem(ACTIVE, job['job_id'])
                    pipe.hset(key, mapping={'status': 'idle', 'job_id': '', 'token': ''})
                    pipe.hincrby(METRICS, 'failed' if error else 'completed', 1)
                    if timings:
                        for name, value in timings.items():
                            pipe.hincrbyfloat(METRICS, name, value / 1000)
                        pipe.hincrby(METRICS, 'timed', 1)
                    await pipe.execute()
                    return True
                except WatchError:
                    continue

    async def recover(self, job_id: str) -> None:
        target = job_key(job_id)
        while True:
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(target)
                    job = await pipe.hgetall(target)
                    state = job.get('status')
                    queue_timeout, inference_timeout = self.timeouts(job)
                    queue = queue_key(job.get('kind', 'image'))
                    if state not in {'queued', 'running'}:
                        await self.redis.srem(ACTIVE, job_id)
                        return
                    age = time.time() - float(job['created_at'])
                    error = ''
                    retry = False
                    key = worker_key(int(job.get('gpu_id', -1)))
                    if state == 'queued':
                        if age <= queue_timeout:
                            return
                        error = 'queue_timeout'
                    else:
                        await pipe.watch(key)
                        worker = await pipe.hgetall(key)
                        lost = worker.get('boot_id') != job['boot_id'] or worker.get('token') != job['token']
                        expired = time.time() - float(job['started_at']) > inference_timeout + 10
                        if not lost and not expired:
                            return
                        error = 'worker_lost' if lost else 'inference_timeout'
                        retry = lost and int(job['attempts']) < self.config.max_attempts and age < queue_timeout
                    session = 'tryon:session:' + job['session_id']
                    await pipe.watch(session)
                    latest = await pipe.hget(session, 'job_id')
                    if latest and latest != job_id:
                        error, retry = 'superseded', False
                    pipe.multi()
                    if retry:
                        pipe.hset(target, mapping={'status': 'queued', 'token': '', 'phase': 'queued', 'progress': 0})
                        pipe.rpush(queue, job_id)
                        pipe.hincrby(METRICS, 'retries', 1)
                    else:
                        pipe.lrem(queue, 0, job_id)
                        pipe.hset(target, mapping={'status': 'failed', 'error': error, 'token': ''})
                        pipe.expire(target, self.config.result_ttl)
                        pipe.srem(ACTIVE, job_id)
                        pipe.hincrby(METRICS, 'failed', 1)
                        if state == 'running' and not lost:
                            pipe.hset(key, 'status', 'unhealthy')
                    await pipe.execute()
                    return
                except WatchError:
                    continue

    def timeouts(self, job: dict) -> tuple[int, int]:
        if job.get('kind') == 'video':
            return self.config.video_queue_timeout, self.config.video_inference_timeout
        return self.config.queue_timeout, self.config.inference_timeout

    async def progress(self, job: dict[str, str], phase: str, percent: int) -> None:
        await self.redis.eval(
            "if redis.call('HGET',KEYS[1],'token') == ARGV[1] and redis.call('HGET',KEYS[1],'status') == 'running' then return redis.call('HSET',KEYS[1],'phase',ARGV[2],'progress',ARGV[3]) else return 0 end",
            1, job_key(job['job_id']), job['token'], phase, max(0, min(percent, 99)))


def redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True,
                          socket_connect_timeout=5, socket_timeout=5, health_check_interval=15)
