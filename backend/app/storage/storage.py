import base64
import binascii
import io
import os
import warnings
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.app.config import settings


def decode_image(encoded: str) -> Image.Image:
    if encoded.startswith('data:'):
        encoded = encoded.split(',', 1)[-1]
    if len(encoded) > (settings.max_image_bytes + 2) // 3 * 4:
        raise ValueError('Image exceeds 20MB')
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('Invalid base64 image') from exc
    if len(content) > settings.max_image_bytes:
        raise ValueError('Image exceeds 20MB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise ValueError('Only JPEG, PNG and WebP are supported')
                if source.width * source.height > 40_000_000:
                    raise ValueError('Image exceeds 40 megapixels')
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                return image.copy()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('Invalid or unsafe image') from exc


def job_dir(job_id: str) -> Path:
    if not job_id.startswith('tryon_') or not job_id[6:].isalnum():
        raise ValueError('Invalid job id')
    return settings.data_dir / job_id


def save_image(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.' + uuid4().hex + '.tmp')
    try:
        image.save(temporary, format='PNG')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
