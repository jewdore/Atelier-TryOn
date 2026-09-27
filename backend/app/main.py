import re
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from redis.exceptions import RedisError

from backend.app.api import garments, health, tryon, videos
from backend.app.config import settings
from backend.app.logging import configure, event
from backend.app.scheduler.worker import redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app.state.redis = redis_client()
    yield
    await app.state.redis.aclose()


app = FastAPI(title='Virtual Try-On', version='1.0.0', lifespan=lifespan)
app.include_router(health.router)
app.include_router(garments.router)
app.include_router(videos.router)
app.include_router(tryon.router)
app.mount('/garments', StaticFiles(directory=str(settings.garment_dir), check_dir=False), name='garments')


@app.middleware('http')
async def context(request: Request, call_next):
    incoming = request.headers.get('x-request-id', '')
    request.state.request_id = incoming if re.fullmatch(r'[A-Za-z0-9_-]{1,100}', incoming) else uuid4().hex
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except RedisError:
        response = JSONResponse({'detail': 'Queue temporarily unavailable'}, status_code=503)
    response.headers['x-request-id'] = request.state.request_id
    response.headers['cache-control'] = 'no-store' if request.url.path.startswith('/api/') else 'public, max-age=60'
    event('http', request_id=request.state.request_id, path=request.url.path, status=response.status_code,
          latency_ms=(time.perf_counter() - started) * 1000)
    return response


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        if scope.get('path') == '/api/videos' and scope.get('method') == 'POST':
            return await self.app(scope, receive, send)
        messages = []
        size = 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > 28_100_000:
                response = JSONResponse({'detail': 'Request exceeds image upload limit'}, status_code=413)
                return await response(scope, receive, send)
            messages.append(message)
            if not message.get('more_body', False):
                break
        async def replay():
            if messages:
                return messages.pop(0)
            return await receive()
        await self.app(scope, replay, send)


app.add_middleware(BodyLimit)
