import shutil
import subprocess
import time
from uuid import uuid4

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from backend.app.config import Settings, settings
from backend.app.main import app
from backend.app.scheduler.worker import JobStore, queue_key, worker_key
from backend.app.storage.storage import job_dir
from backend.app.storage.video import normalize_video, probe, video_dir


def task(kind='video', session=None, sequence=0):
    return {'job_id': 'tryon_' + uuid4().hex, 'kind': kind, 'session_id': session or uuid4().hex,
            'sequence': sequence, 'created_at': time.time(), 'request_id': uuid4().hex}


@pytest.fixture
async def stores():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield JobStore(redis, Settings()), JobStore(redis, Settings(worker_kind='video', model_name='catv2ton'))
    await redis.aclose()


async def test_video_pool_isolation_and_ninth_queue(stores):
    image, video = stores
    await image.register(0, 'image')
    await video.register(7, 'video')
    image_job, video_job, extra = task('image'), task(), task()
    for job in [video_job, extra, image_job]:
        await image.enqueue(job)
    assert await image.dispatch(0) == image_job['job_id']
    assert await image.dispatch(7) == video_job['job_id']
    assert await image.dispatch(7) is None
    assert await image.redis.lrange(queue_key('video'), 0, -1) == [extra['job_id']]


async def test_video_timeout_does_not_pop_image_queue(stores):
    image, video = stores
    await video.register(7, 'video')
    expired, picture = task(), task('image')
    expired['created_at'] -= settings.video_queue_timeout + 1
    await image.enqueue(expired)
    await image.enqueue(picture)
    assert await image.dispatch(7) is None
    assert (await image.get(expired['job_id']))['error'] == 'queue_timeout'
    assert await image.redis.lrange(queue_key(), 0, -1) == [picture['job_id']]


async def test_cross_modality_latest_wins(stores):
    image, _ = stores
    session = uuid4().hex
    old, new = task('image', session, 1), task('video', session, 2)
    await image.enqueue(old)
    await image.enqueue(new)
    assert await image.redis.llen(queue_key()) == 0
    assert (await image.get(old['job_id']))['error'] == 'superseded'
    assert await image.enqueue(task('video', session, 1)) == 'stale_sequence'


async def test_video_recovery_and_progress_fencing(stores):
    image, video = stores
    await video.register(7, 'old')
    job = task()
    job['created_at'] -= 200
    await image.enqueue(job)
    await image.dispatch(7)
    old = await image.get(job['job_id'])
    await image.progress(old, 'inference', 40)
    assert (await image.get(job['job_id']))['progress'] == '40'
    await image.redis.delete(worker_key(7))
    await image.recover(job['job_id'])
    assert await image.redis.lindex(queue_key('video'), 0) == job['job_id']
    await video.register(7, 'new')
    await image.dispatch(7)
    await image.progress(old, 'encoding', 90)
    assert (await image.get(job['job_id']))['progress'] != '90'
    assert not await image.finish(old, result_file='stale.mp4')


@pytest.fixture
def clip(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg unavailable')
    path = tmp_path / 'test.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=192x256:rate=12',
        '-t', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True, capture_output=True)
    return path


def test_video_normalization_and_validation(clip, tmp_path, monkeypatch):
    destination = tmp_path / 'normalized.mp4'
    metadata = normalize_video(clip, destination)
    assert metadata == {'duration_seconds': 1.0, 'width': 384, 'height': 512, 'fps': 12, 'frames': 12}
    assert probe(destination)['streams'][0]['codec_name'] == 'h264'
    with pytest.raises(ValueError):
        video_dir('../../escape')
    monkeypatch.setattr(settings, 'video_max_seconds', 0)
    with pytest.raises(ValueError, match='Video must'):
        normalize_video(clip, destination)


async def test_video_api_upload_submit_result_limits(clip, stores, tmp_path, monkeypatch):
    image, video = stores
    monkeypatch.setattr(settings, 'data_dir', tmp_path / 'data')
    monkeypatch.setattr(settings, 'garment_dir', tmp_path / 'garments')
    clothes = settings.garment_dir / 'tops'
    clothes.mkdir(parents=True)
    Image.new('RGB', (100, 100), 'blue').save(clothes / 'test.png')
    app.state.redis = image.redis
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/videos', content=clip.read_bytes())
        assert response.status_code == 201, response.text
        uploaded = response.json()
        preview = await client.get(uploaded['preview_url'], headers={'Range': 'bytes=0-31'})
        assert preview.status_code == 206
        session = uuid4().hex
        payload = {'video_id': uploaded['video_id'], 'garment_id': 'test', 'category': 'upper_body', 'session_id': session, 'sequence': 1}
        response = await client.post('/api/tryon/video', json=payload)
        assert response.status_code == 202, response.text
        old_id = response.json()['job_id']
        payload['sequence'] = 2
        response = await client.post('/api/tryon/video', json=payload)
        job_id = response.json()['job_id']
        assert (await client.get('/api/tryon/' + old_id)).json()['error'] == 'superseded'
        await video.register(7, 'video')
        assert await image.dispatch(7) == job_id
        assignment = await image.get(job_id)
        filename = assignment['token'] + '.mp4'
        shutil.copyfile(job_dir(job_id) / 'source.mp4', job_dir(job_id) / filename)
        await image.finish(assignment, result_file=filename)
        state = (await client.get('/api/tryon/' + job_id)).json()
        assert state['kind'] == 'video' and state['progress'] == 100
        result = await client.get(state['result_url'])
        assert result.headers['content-type'] == 'video/mp4'
        await image.redis.delete('tryon:video:' + uploaded['video_id'])
        assert (await client.get(uploaded['preview_url'])).status_code == 404
        assert job_dir(job_id).joinpath('source.mp4').exists()
        assert (await client.post('/api/tryon/video', json=payload)).status_code == 404
        monkeypatch.setattr(settings, 'video_max_bytes', 10)
        assert (await client.post('/api/videos', content=b'x' * 11)).status_code == 413
        assert (await client.post('/api/videos', content=b'bad')).status_code == 422
        assert len(list(settings.data_dir.glob('video_*'))) == 1
