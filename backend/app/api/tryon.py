import json
import shutil
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from backend.app.api.garments import find_garment
from backend.app.schemas.tryon import JobResponse, TryOnRequest
from backend.app.scheduler.worker import JobStore
from backend.app.storage.storage import decode_image, job_dir, save_image

router = APIRouter()


@router.post('/api/tryon', response_model=JobResponse, status_code=202, response_model_exclude_none=True)
async def submit(payload: TryOnRequest, request: Request) -> JobResponse:
    garment, path = await run_in_threadpool(find_garment, payload.garment_id)
    if garment.category != payload.category:
        raise HTTPException(422, 'Category does not match garment')
    created_at = time.time()
    try:
        person = await run_in_threadpool(decode_image, payload.person_image)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    job_id = 'tryon_' + uuid4().hex
    directory = job_dir(job_id)
    await run_in_threadpool(save_image, person, directory / 'person.png')
    job = {'job_id': job_id, 'garment_id': garment.id, 'garment_path': path.as_posix(),
        'category': payload.category, 'created_at': created_at, 'request_id': request.state.request_id,
        'session_id': payload.session_id or uuid4().hex, 'sequence': payload.sequence}
    status = await JobStore(request.app.state.redis).enqueue(job)
    if status != 'queued':
        await run_in_threadpool(shutil.rmtree, directory)
        raise HTTPException(409 if status == 'stale_sequence' else 429, status)
    return JobResponse(job_id=job_id, status='queued')


async def read_job(job_id: str, request: Request) -> dict[str, str]:
    try:
        job_dir(job_id)
    except ValueError:
        raise HTTPException(404, 'Job not found')
    job = await JobStore(request.app.state.redis).get(job_id)
    if not job:
        raise HTTPException(404, 'Job not found or expired')
    return job


@router.get('/api/tryon/{job_id}', response_model=JobResponse, response_model_exclude_none=True)
async def status(job_id: str, request: Request) -> JobResponse:
    job = await read_job(job_id, request)
    timings = json.loads(job.get('timings', '{}'))
    return JobResponse(job_id=job_id, status=job['status'], error=job.get('error') or None,
        gpu_id=int(job['gpu_id']) if 'gpu_id' in job else None,
        result_url=f'/api/tryon/{job_id}/result' if job['status'] == 'completed' else None,
        latency_ms=timings.get('total_latency_ms'), timings=timings or None,
        kind=job.get('kind', 'image'), phase=job.get('phase'),
        progress=int(job['progress']) if 'progress' in job else None)


@router.get('/api/tryon/{job_id}/result')
async def result(job_id: str, request: Request) -> FileResponse:
    job = await read_job(job_id, request)
    if job['status'] != 'completed':
        raise HTTPException(409, 'Result is not ready')
    path = job_dir(job_id) / job['result_file']
    if not path.is_file():
        raise HTTPException(410, 'Result expired')
    video = job.get('kind') == 'video'
    return FileResponse(path, media_type='video/mp4' if video else 'image/png',
        headers={'Cache-Control': 'no-store'}, filename=f'{job_id}.mp4' if video else None,
        content_disposition_type='inline')
