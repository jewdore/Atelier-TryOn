import hashlib
import sys
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from backend.app.config import Settings, settings
from worker.preprocess import prepare


class TryOnModel(ABC):
    timings: dict[str, float]

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def warmup(self) -> None: ...

    @abstractmethod
    def predict(self, person_image: Image.Image, garment_image: Image.Image, category: str) -> Image.Image: ...

    def tryon(self, person_image: Image.Image, garment_image: Image.Image, category: str) -> Image.Image:
        return self.predict(person_image, garment_image, category)


class CatVTONModel(TryOnModel):
    def __init__(self, config: Settings = settings):
        self.config = config
        self.pipeline: Any = None
        self.masker: Any = None
        self.cache: OrderedDict[str, Image.Image] = OrderedDict()
        self.timings = {}

    def load(self) -> None:
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable; use a compatible CUDA PyTorch build, not CPU torch')
        torch.cuda.set_device(0)
        torch.ones((32, 32), device='cuda').matmul(torch.ones((32, 32), device='cuda'))
        torch.cuda.synchronize()
        sys.path.insert(0, self.config.catvton_source)
        from model.pipeline import CatVTONPipeline
        from model.cloth_masker import AutoMasker

        self.pipeline = CatVTONPipeline(
            base_ckpt=self.config.base_model_path,
            attn_ckpt=str(self.config.model_path), attn_ckpt_version='mix',
            weight_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
            device='cuda', skip_safety_check=True, use_tf32=True,
        )
        self.masker = AutoMasker(
            densepose_ckpt=str(self.config.model_path / 'DensePose'),
            schp_ckpt=str(self.config.model_path / 'SCHP'), device='cuda',
        )

    def warmup(self) -> None:
        path = Path(self.config.warmup_person)
        if not path.is_file():
            candidates = sorted((Path(self.config.catvton_source) / 'resource/demo/example/person').rglob('*.jpg'))
            if not candidates:
                raise RuntimeError('Set WARMUP_PERSON to a real person image')
            path = candidates[0]
        with Image.open(path) as person:
            self.predict(person, Image.new('RGB', (512, 768), 'white'), 'upper_body')
        self.cache.clear()

    def predict(self, person_image: Image.Image, garment_image: Image.Image, category: str) -> Image.Image:
        import torch

        started = time.perf_counter()
        size = (self.config.width, self.config.height)
        person = prepare(person_image, size)
        garment = prepare(garment_image, size, garment=True)
        mask_type = {'upper_body': 'upper', 'lower_body': 'lower', 'dresses': 'overall'}[category]
        cache_key = hashlib.sha256(person.tobytes() + category.encode()).hexdigest()
        with torch.inference_mode():
            mask = self.cache.get(cache_key)
            if mask is None:
                mask = self.masker(person, mask_type)['mask'].filter(ImageFilter.GaussianBlur(9))
                if self.config.mask_cache_size:
                    self.cache[cache_key] = mask
                    while len(self.cache) > self.config.mask_cache_size:
                        self.cache.popitem(last=False)
            else:
                self.cache.move_to_end(cache_key)
            torch.cuda.synchronize()
            inference_started = time.perf_counter()
            result = self.pipeline(
                image=person, condition_image=garment, mask=mask,
                width=size[0], height=size[1], num_inference_steps=self.config.inference_steps,
                guidance_scale=2.5, generator=torch.Generator('cuda').manual_seed(self.config.seed),
            )[0]
            torch.cuda.synchronize()
        self.timings = {'preprocess_time_ms': (inference_started - started) * 1000,
                        'inference_time_ms': (time.perf_counter() - inference_started) * 1000}
        return result


class MockModel(TryOnModel):
    def load(self) -> None:
        self.timings = {}

    def warmup(self) -> None:
        self.predict(Image.new('RGB', (384, 512)), Image.new('RGB', (384, 512)), 'upper_body')

    def predict(self, person_image: Image.Image, garment_image: Image.Image, category: str) -> Image.Image:
        image = prepare(person_image, (384, 512))
        image.paste(prepare(garment_image, (128, 180), True), (240, 310))
        ImageDraw.Draw(image).text((12, 12), 'MOCK - NOT VIRTUAL TRY-ON', fill='red', stroke_width=1)
        time.sleep(0.05)
        self.timings = {'preprocess_time_ms': 0.0, 'inference_time_ms': 50.0}
        return image


def create_model(config: Settings = settings) -> TryOnModel:
    if config.model_name == 'catvton':
        return CatVTONModel(config)
    if config.model_name == 'mock':
        return MockModel()
    raise ValueError(f'Unsupported MODEL_NAME: {config.model_name}')
