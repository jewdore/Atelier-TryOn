from typing import Literal

from pydantic import BaseModel, Field

Category = Literal['upper_body', 'lower_body', 'dresses']


class TryOnRequest(BaseModel):
    person_image: str = Field(min_length=1, max_length=28_000_100)
    garment_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')
    category: Category
    session_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{8,100}$')
    sequence: int = Field(default=0, ge=0, le=2**53 - 1)


class JobResponse(BaseModel):
    job_id: str
    status: Literal['queued', 'running', 'completed', 'failed']
    result_url: str | None = None
    latency_ms: float | None = None
    error: str | None = None
    gpu_id: int | None = None
    timings: dict[str, float] | None = None
    kind: Literal['image', 'video'] = 'image'
    phase: str | None = None
    progress: int | None = None


class VideoTryOnRequest(BaseModel):
    video_id: str = Field(pattern=r'^video_[a-f0-9]{32}$')
    garment_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')
    category: Category
    session_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{8,100}$')
    sequence: int = Field(default=0, ge=0, le=2**53 - 1)


class VideoUploadResponse(BaseModel):
    video_id: str
    preview_url: str
    duration_seconds: float
    width: int
    height: int
    fps: int
    frames: int
    expires_in: int


class Garment(BaseModel):
    id: str
    name: str
    category: Category
    image_url: str
