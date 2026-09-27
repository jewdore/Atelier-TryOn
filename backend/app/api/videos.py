import asyncio
import json
import os
import shutil
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from backend.app.api.garments import find_garment
from backend.app.config import settings
from backend.app.schemas.tryon import JobResponse, VideoTryOnRequest, VideoUploadResponse
from backend.app.scheduler.worker import JobStore
from backend.app.storage.storage import job_dir
from backend.app.storage.video import normalize_video, video_dir

router = APIRouter()
upload_slots = asyncio.Semaphore(2)


@router.post('/api/videos', response_model=VideoUploadResponse, status_code=201)
async def upload_video(request: Request) -> VideoUploadResponse:
    if upload_slots.locked():
        raise HTTPException(429, 'Video upload capacity reached; retry shortly')
    async with upload_slots:
        video_id = 'video_' + uuid4().hex
        directory = video_dir(video_id)
        directory.mkdir(parents=True)
        source = directory / 'upload.bin'
        ready = False
        try:
            size = 0
            async with asyncio.timeout(120):
                with source.open('wb') as output:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > settings.video_max_bytes:
                            raise HTTPException(413, 'Video exceeds 100MB')
                        await run_in_threadpool(output.write, chunk)
            if not size:
                raise HTTPException(422, 'Video is empty')
            metadata = await run_in_threadpool(normalize_video, source, directory / 'source.mp4')
            source.unlink(missing_ok=True)
            await request.app.state.redis.set('tryon:video:' + video_id, json.dumps(metadata), ex=settings.result_ttl)
            ready = True
            return VideoUploadResponse(video_id=video_id, preview_url=f'/api/videos/{video_id}',
                expires_in=settings.result_ttl, **metadata)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(408, 'Video upload timed out') from exc
        finally:
            if not ready:
                await run_in_threadpool(shutil.rmtree, directory, True)


@router.get('/api/videos/{video_id}')
async def preview_video(video_id: str, request: Request) -> FileResponse:
    try:
        path = video_dir(video_id) / 'source.mp4'
    except ValueError as exc:
        raise HTTPException(404, 'Video not found') from exc
    if not await request.app.state.redis.exists('tryon:video:' + video_id) or not path.is_file():
        raise HTTPException(404, 'Video expired; upload again')
    return FileResponse(path, media_type='video/mp4')


@router.post('/api/tryon/video', response_model=JobResponse, status_code=202, response_model_exclude_none=True)
async def submit_video(payload: VideoTryOnRequest, request: Request) -> JobResponse:
    metadata = await request.app.state.redis.get('tryon:video:' + payload.video_id)
    if not metadata:
        raise HTTPException(404, 'Video expired; upload again')
    garment, path = await run_in_threadpool(find_garment, payload.garment_id)
    if garment.category != payload.category:
        raise HTTPException(422, 'Category does not match garment')
    if garment.category != 'upper_body':
        raise HTTPException(422, 'Video V1 supports upper-body garments only')
    job_id = 'tryon_' + uuid4().hex
    directory = job_dir(job_id)
    directory.mkdir(parents=True)
    try:
        await run_in_threadpool(os.link, video_dir(payload.video_id) / 'source.mp4', directory / 'source.mp4')
        job = {'job_id': job_id, 'kind': 'video', 'video_id': payload.video_id,
            'video_metadata': metadata, 'garment_id': garment.id, 'garment_path': path.as_posix(),
            'category': payload.category, 'created_at': time.time(), 'request_id': request.state.request_id,
            'session_id': payload.session_id or uuid4().hex, 'sequence': payload.sequence,
            'phase': 'queued', 'progress': 0}
        status = await JobStore(request.app.state.redis).enqueue(job)
        if status != 'queued':
            raise HTTPException(409 if status == 'stale_sequence' else 429, status)
    except FileNotFoundError as exc:
        await run_in_threadpool(shutil.rmtree, directory, True)
        raise HTTPException(404, 'Video expired; upload again') from exc
    except Exception:
        await run_in_threadpool(shutil.rmtree, directory, True)
        raise
    return JobResponse(job_id=job_id, status='queued', kind='video', phase='queued', progress=0)
