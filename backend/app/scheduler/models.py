from typing import Literal

from pydantic import BaseModel


class WorkerInfo(BaseModel):
    worker_id: str
    gpu_id: int
    model: str
    status: Literal['idle', 'busy', 'unhealthy']
    boot_id: str
    heartbeat: float
    job_id: str = ''
    token: str = ''
