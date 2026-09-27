from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    redis_url: str = 'redis://localhost:6379/0'
    data_dir: Path = Path('data')
    garment_dir: Path = Path('garments')
    model_name: str = 'catvton'
    model_path: Path = Path('/models/catvton')
    base_model_path: str = '/models/base'
    catvton_source: str = '/opt/CatVTON'
    gpu_id: int = 0
    width: int = Field(576, multiple_of=8, ge=256, le=1024)
    height: int = Field(768, multiple_of=8, ge=256, le=1536)
    inference_steps: int = Field(20, ge=1, le=100)
    seed: int = 42
    result_ttl: int = Field(3600, ge=60)
    queue_timeout: int = Field(180, ge=5)
    inference_timeout: int = Field(180, ge=5)
    heartbeat_seconds: int = Field(3, ge=1)
    lease_seconds: int = Field(30, ge=10)
    max_queue: int = Field(128, ge=1)
    max_attempts: int = Field(2, ge=1)
    max_image_bytes: int = 20 * 1024 * 1024
    mask_cache_size: int = Field(8, ge=0, le=64)
    warmup_person: str = '/opt/CatVTON/resource/demo/example/person/men/model_5.png'
    worker_kind: Literal['image', 'video'] = 'image'
    catv2ton_source: str = '/opt/CatV2TON'
    video_base_path: str = '/models/video-base'
    video_model_path: str = '/models/catv2ton/512-64K'
    video_width: int = Field(384, ge=256, le=768, multiple_of=16)
    video_height: int = Field(512, ge=256, le=1024, multiple_of=16)
    video_fps: int = Field(12, ge=4, le=24)
    video_max_seconds: int = Field(8, ge=1, le=30)
    video_max_bytes: int = 100 * 1024 * 1024
    video_steps: int = Field(20, ge=1, le=50)
    video_queue_timeout: int = Field(1800, ge=60)
    video_inference_timeout: int = Field(1800, ge=60)


settings = Settings()
