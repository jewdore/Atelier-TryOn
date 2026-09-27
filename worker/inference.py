import argparse
import json
import time
from pathlib import Path

from PIL import Image

from backend.app.storage.storage import save_image
from worker.model import create_model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--person', required=True)
    parser.add_argument('--garment', required=True)
    parser.add_argument('--category', choices=['upper_body', 'lower_body', 'dresses'], default='upper_body')
    parser.add_argument('--output', default='result.png')
    arguments = parser.parse_args()
    model = create_model()
    model.load()
    model.warmup()
    started = time.perf_counter()
    with Image.open(arguments.person) as person, Image.open(arguments.garment) as garment:
        save_image(model.tryon(person, garment, arguments.category), Path(arguments.output))
    print(json.dumps({'output': arguments.output, 'total_latency_ms': (time.perf_counter() - started) * 1000, **model.timings}))


if __name__ == '__main__':
    main()
