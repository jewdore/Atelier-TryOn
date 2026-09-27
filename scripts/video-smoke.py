import json
import time
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageOps

from backend.app.config import settings
from worker.video_model import CatV2TONModel


def main() -> None:
    root = Path('/data/video-smoke')
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'source.mp4'
    with Image.open(settings.warmup_person) as image:
        image = ImageOps.pad(image.convert('RGB'), (settings.video_width, settings.video_height))
        with av.open(str(source), 'w') as container:
            stream = container.add_stream('libx264', rate=settings.video_fps)
            stream.width, stream.height, stream.pix_fmt = image.width, image.height, 'yuv420p'
            for index in range(12):
                frame = ImageOps.expand(image, border=8, fill='white').crop((index, 8, index + image.width, 8 + image.height))
                for packet in stream.encode(av.VideoFrame.from_ndarray(np.array(frame), format='rgb24')):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
    model = CatV2TONModel()
    started = time.time()
    model.load()
    print('MODEL LOADED', time.time() - started, flush=True)
    model.warmup()
    print('WARMUP DONE', time.time() - started, flush=True)
    garment = next(Path('/garments/tops').glob('*.*'))
    model.predict(source, garment, 'upper_body', root / 'result.mp4',
        lambda phase, progress: print(phase, progress, flush=True))
    import torch
    report = {'timings': model.timings, 'peak_gpu_mib': torch.cuda.max_memory_allocated() / 1024**2,
              'source': 'synthetic 12-frame camera-pan from warmup photo, not a real-motion quality benchmark'}
    (root / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
