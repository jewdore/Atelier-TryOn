import asyncio
import base64
import io
import time
from uuid import uuid4

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from backend.app.config import Settings, settings
from backend.app.main import app
from backend.app.scheduler.worker import JobStore, QUEUE, job_key, worker_key
from backend.app.storage.storage import decode_image
from worker.model import MockModel
from worker.worker import execute


def new_job(sequence: int = 0, session: str | None = None) -> dict:
    return {'job_id': 'tryon_' + uuid4().hex, 'session_id': session or uuid4().hex,
            'sequence': sequence, 'created_at': time.time(), 'category': 'upper_body',
            'garment_path': 'tops/test.png', 'garment_id': 'test', 'request_id': uuid4().hex}


@pytest.fixture
async def store():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield JobStore(redis, Settings())
    await redis.aclose()


async def test_eight_workers_ninth_queued(store):
    for gpu in range(8):
        assert await store.register(gpu, f'boot-{gpu}')
    jobs = [new_job() for _ in range(9)]
    for job in jobs:
        assert await store.enqueue(job) == 'queued'
    assignments = await asyncio.gather(*(store.dispatch(gpu) for gpu in range(8)))
    assert len(set(assignments)) == 8
    assert await store.redis.llen(QUEUE) == 1
    assert await store.dispatch(0) is None
    first = await store.get(assignments[0])
    assert await store.finish(first, result_file='test.png')
    assert await store.dispatch(0) == jobs[-1]['job_id']


async def test_latest_request_wins_and_out_of_order(store):
    session = uuid4().hex
    first, second, stale = new_job(1, session), new_job(3, session), new_job(2, session)
    assert await store.enqueue(first) == 'queued'
    assert await store.enqueue(second) == 'queued'
    assert (await store.get(first['job_id']))['error'] == 'superseded'
    assert await store.enqueue(stale) == 'stale_sequence'
    assert await store.redis.lrange(QUEUE, 0, -1) == [second['job_id']]


async def test_crash_recovery_fences_old_completion(store):
    await store.register(0, 'old')
    job = new_job()
    await store.enqueue(job)
    await store.dispatch(0)
    old = await store.get(job['job_id'])
    await store.redis.delete(worker_key(0))
    await store.recover(job['job_id'])
    assert (await store.get(job['job_id']))['status'] == 'queued'
    await store.register(0, 'new')
    await store.dispatch(0)
    assert not await store.finish(old, result_file='obsolete.png')
    current = await store.get(job['job_id'])
    assert await store.finish(current, result_file='new.png')
    assert (await store.get(job['job_id']))['result_file'] == 'new.png'


async def test_queue_timeout_without_workers(store):
    job = new_job()
    job['created_at'] -= 1000
    await store.enqueue(job)
    await store.recover(job['job_id'])
    assert (await store.get(job['job_id']))['error'] == 'queue_timeout'
    assert await store.redis.llen(QUEUE) == 0


async def test_busy_worker_timeout_never_reused(store):
    await store.register(0, 'old')
    job = new_job()
    await store.enqueue(job)
    await store.dispatch(0)
    await store.redis.hset(job_key(job['job_id']), 'started_at', time.time() - 1000)
    old = await store.get(job['job_id'])
    await store.recover(job['job_id'])
    assert (await store.get(job['job_id']))['error'] == 'inference_timeout'
    assert await store.redis.hget(worker_key(0), 'status') == 'unhealthy'
    assert not await store.finish(old)


async def test_duplicate_workers_cannot_register(store):
    assert await store.register(0, 'owner')
    assert not await store.register(0, 'intruder')
    assert not await store.heartbeat(0, 'intruder')
    assert await store.heartbeat(0, 'owner')


async def test_running_old_request_completes_but_new_one_is_queued(store):
    session = uuid4().hex
    old = new_job(1, session)
    await store.register(0, 'boot')
    await store.enqueue(old)
    await store.dispatch(0)
    running = await store.get(old['job_id'])
    new = new_job(2, session)
    await store.enqueue(new)
    assert (await store.get(old['job_id']))['status'] == 'running'
    assert await store.finish(running, result_file='old.png')
    assert await store.dispatch(0) == new['job_id']


async def test_superseded_crashed_job_not_retried(store):
    session = uuid4().hex
    job = new_job(1, session)
    await store.register(0, 'boot')
    await store.enqueue(job)
    await store.dispatch(0)
    newer = new_job(2, session)
    await store.enqueue(newer)
    await store.redis.delete(worker_key(0))
    await store.recover(job['job_id'])
    assert (await store.get(job['job_id']))['error'] == 'superseded'
    assert await store.redis.lrange(QUEUE, 0, -1) == [newer['job_id']]


async def test_queue_capacity_and_terminal_ttl(store):
    store.config.max_queue = 1
    first = new_job()
    assert await store.enqueue(first) == 'queued'
    assert await store.enqueue(new_job()) == 'queue_full'
    assert await store.redis.ttl(job_key(first['job_id'])) == -1
    await store.register(0, 'boot')
    await store.dispatch(0)
    await store.finish(await store.get(first['job_id']), error='test_error')
    assert 0 < await store.redis.ttl(job_key(first['job_id'])) <= store.config.result_ttl


async def test_multiple_schedulers_do_not_duplicate_assignment(store):
    for gpu in range(8):
        await store.register(gpu, str(gpu))
    for _ in range(16):
        await store.enqueue(new_job())
    assignments = await asyncio.gather(*(store.dispatch(gpu) for _ in range(3) for gpu in range(8)))
    assigned = [value for value in assignments if value]
    assert len(assigned) == len(set(assigned)) == 8
    assert await store.redis.llen(QUEUE) == 8


def test_image_validation_and_exif():
    buffer = io.BytesIO()
    image = Image.new('RGB', (20, 40), 'red')
    exif = image.getexif()
    exif[274] = 6
    image.save(buffer, format='JPEG', exif=exif)
    result = decode_image(base64.b64encode(buffer.getvalue()).decode())
    assert result.size == (40, 20)
    assert result.mode == 'RGB'
    with pytest.raises(ValueError):
        decode_image('not-base64')
    with pytest.raises(ValueError):
        decode_image(base64.b64encode(b'not an image').decode())


async def test_api_to_model_to_result(store, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path / 'data')
    monkeypatch.setattr(settings, 'garment_dir', tmp_path / 'garments')
    clothes = settings.garment_dir / 'tops'
    clothes.mkdir(parents=True)
    Image.new('RGB', (100, 100), 'blue').save(clothes / 'test.png')
    app.state.redis = store.redis
    image = io.BytesIO()
    Image.new('RGB', (100, 150), 'white').save(image, format='PNG')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        clothes_response = await client.get('/api/garments')
        assert clothes_response.status_code == 200
        submitted = await client.post('/api/tryon', json={
            'person_image': base64.b64encode(image.getvalue()).decode(),
            'garment_id': 'test', 'category': 'upper_body'})
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()['job_id']
        await store.register(0, 'test-boot')
        await store.dispatch(0)
        job = await store.get(job_id)
        model = MockModel()
        model.load()
        model.warmup()
        filename, timings = execute(model, job)
        assert await store.finish(job, result_file=filename, timings=timings)
        status = await client.get(f'/api/tryon/{job_id}')
        assert status.json()['status'] == 'completed'
        output = await client.get(status.json()['result_url'])
        assert output.headers['content-type'] == 'image/png'
        assert Image.open(io.BytesIO(output.content)).size == (384, 512)
        metrics = await client.get('/api/metrics')
        assert 'tryon_requests_completed_total 1' in metrics.text
