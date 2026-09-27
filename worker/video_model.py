import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps

from backend.app.config import settings

Progress = Callable[[str, int], None]


class VideoTryOnModel(ABC):
    timings: dict[str, float]

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def warmup(self) -> None: ...

    @abstractmethod
    def predict(self, person_video: Path, garment_image: Path, category: str,
                output: Path, progress: Progress) -> None: ...


class CatV2TONModel(VideoTryOnModel):
    def load(self) -> None:
        sys.path.insert(0, settings.catv2ton_source)
        import torch
        from modules.cloth_masker import AutoMasker
        from modules.pipeline import V2TONPipeline

        if not torch.cuda.is_available():
            raise RuntimeError('CatV2TON requires CUDA')
        self.dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        self.pipeline = V2TONPipeline(settings.video_base_path, settings.video_model_path,
            load_pose=True, torch_dtype=self.dtype, device='cuda')
        self.masker = AutoMasker(str(settings.model_path / 'DensePose'), str(settings.model_path / 'SCHP'), 'cuda')
        self.timings = {}

    def warmup(self) -> None:
        import numpy as np
        import torch

        with Image.open(settings.warmup_person) as source:
            person = ImageOps.pad(source.convert('RGB'), (settings.video_width, settings.video_height))
        frames = torch.from_numpy(np.array(person)).permute(2, 0, 1).unsqueeze(0).repeat(8, 1, 1, 1).float() / 255
        self._predict_frames(frames, person, 'upper_body', lambda phase, percent: None, steps=1)
        torch.cuda.synchronize()
        torch.cuda.empty_cache()

    def _predict_frames(self, frames, garment: Image.Image, category: str, progress: Progress, steps: int):
        import cv2
        import numpy as np
        import torch
        from modules.cloth_masker import smooth_video_mask
        from data.utils import densepose_to_rgb

        if category != 'upper_body':
            raise ValueError('Video V1 supports upper-body garments only')
        started = time.perf_counter()
        masks, poses = [], []
        with torch.inference_mode():
            for index, frame in enumerate(frames):
                person = Image.fromarray((frame.permute(1, 2, 0).numpy() * 255).astype(np.uint8))
                processed = self.masker(person, mask_type='upper')
                masks.append(torch.from_numpy(np.array(processed['mask'])))
                poses.append(torch.from_numpy(np.array(densepose_to_rgb(processed['densepose'], cv2.COLORMAP_VIRIDIS))))
                progress('preprocess', 5 + round(30 * (index + 1) / len(frames)))
            mask = torch.stack(masks).unsqueeze(0).repeat(3, 1, 1, 1)
            mask = smooth_video_mask(mask).unsqueeze(0).float() / 255
            pose = torch.stack(poses).permute(3, 0, 1, 2).unsqueeze(0).float() / 127.5 - 1
            source = frames.permute(1, 0, 2, 3).unsqueeze(0) * 2 - 1
            count = source.shape[2]
            padding = (-count) % 4
            if padding:
                source = torch.cat([source, source[:, :, -1:].repeat(1, 1, padding, 1, 1)], dim=2)
                mask = torch.cat([mask, mask[:, :, -1:].repeat(1, 1, padding, 1, 1)], dim=2)
                pose = torch.cat([pose, pose[:, :, -1:].repeat(1, 1, padding, 1, 1)], dim=2)
            clothing = ImageOps.pad(garment.convert('RGB'), (settings.video_width, settings.video_height), color='white')
            condition = torch.from_numpy(np.array(clothing)).permute(2, 0, 1).unsqueeze(0).unsqueeze(2).float() / 127.5 - 1
            inference_start = time.perf_counter()
            self.timings = {'preprocess_time_ms': (inference_start - started) * 1000}
            progress('inference', 40)
            torch.manual_seed(settings.seed)
            output = self.pipeline.video_try_on(source_video=source, mask_video=mask,
                condition_image=condition, pose_video=pose, num_inference_steps=steps,
                guidance_scale=3.0, slice_frames=24, pre_frames=8, use_adacn=True,
                generator=torch.Generator(device='cuda').manual_seed(settings.seed))
            torch.cuda.synchronize()
            self.timings['inference_time_ms'] = (time.perf_counter() - inference_start) * 1000
            progress('encoding', 90)
            output = output.float().cpu().permute(0, 4, 1, 2, 3)
            kernel = settings.video_width // 50 | 1
            soft_mask = torch.nn.functional.avg_pool2d(mask[0].permute(1, 0, 2, 3), kernel,
                stride=1, padding=kernel // 2).permute(1, 0, 2, 3).unsqueeze(0)
            output = source * (1 - soft_mask) + output * soft_mask
            return ((output[0, :, :count].permute(1, 2, 3, 0) + 1) * 127.5).clamp(0, 255).byte().numpy()

    def predict(self, person_video: Path, garment_image: Path, category: str,
                output: Path, progress: Progress) -> None:
        import av
        import numpy as np
        import torch

        with av.open(str(person_video)) as video:
            arrays = []
            for frame in video.decode(video=0):
                if len(arrays) >= settings.video_max_seconds * settings.video_fps:
                    raise ValueError('Video frame limit exceeded')
                if (frame.width, frame.height) != (settings.video_width, settings.video_height):
                    raise ValueError('Video dimensions do not match worker configuration')
                arrays.append(frame.to_ndarray(format='rgb24'))
        frames = torch.from_numpy(np.stack(arrays)).permute(0, 3, 1, 2).float() / 255
        with Image.open(garment_image) as garment:
            results = self._predict_frames(frames, garment, category, progress, settings.video_steps)
        started = time.perf_counter()
        temporary = output.with_suffix('.part.mp4')
        try:
            with av.open(str(temporary), 'w', options={'movflags': '+faststart'}) as container:
                stream = container.add_stream('libx264', rate=settings.video_fps)
                stream.width, stream.height = settings.video_width, settings.video_height
                stream.pix_fmt = 'yuv420p'
                stream.options = {'crf': '18', 'preset': 'fast'}
                for array in results:
                    for packet in stream.encode(av.VideoFrame.from_ndarray(array, format='rgb24')):
                        container.mux(packet)
                for packet in stream.encode():
                    container.mux(packet)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        self.timings['postprocess_time_ms'] = (time.perf_counter() - started) * 1000
