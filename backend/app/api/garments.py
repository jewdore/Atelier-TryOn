import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.app.config import settings
from backend.app.schemas.tryon import Garment

router = APIRouter()


def catalog() -> list[Garment]:
    names_file = settings.garment_dir / 'names.json'
    names = json.loads(names_file.read_text(encoding='utf-8')) if names_file.exists() else {}
    garments = []
    seen: set[str] = set()
    for folder, category in [('tops', 'upper_body'), ('jackets', 'upper_body'), ('dresses', 'dresses'), ('pants', 'lower_body')]:
        for path in sorted((settings.garment_dir / folder).glob('*')):
            if path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'} or path.is_symlink():
                continue
            if path.stem in seen:
                raise RuntimeError(f'Duplicate garment id: {path.stem}')
            seen.add(path.stem)
            garments.append(Garment(id=path.stem, name=names.get(path.stem, path.stem.replace('_', ' ')),
                category=category, image_url=f'/garments/{folder}/{path.name}'))
    return garments


def find_garment(garment_id: str) -> tuple[Garment, Path]:
    for garment in catalog():
        if garment.id == garment_id:
            return garment, Path(garment.image_url.removeprefix('/garments/'))
    raise HTTPException(404, 'Garment not found')


@router.get('/api/garments', response_model=list[Garment])
async def list_garments() -> list[Garment]:
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(catalog)
