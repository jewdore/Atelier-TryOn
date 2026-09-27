import json
import os
from pathlib import Path

from filelock import FileLock
from huggingface_hub import HfApi, snapshot_download


def main() -> None:
    root = Path('/models')
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / 'manifest.json'
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    models = [
        ('catvton', 'zhengchong/CatVTON', ['mix-48k-1024/**', 'DensePose/**', 'SCHP/**', 'README.md', 'LICENSE*']),
        ('base', 'stable-diffusion-v1-5/stable-diffusion-inpainting', ['unet/config.json', 'unet/diffusion_pytorch_model.fp16.safetensors', 'scheduler/**', 'model_index.json', 'README.md', 'LICENSE*']),
        ('vae', 'stabilityai/sd-vae-ft-mse', ['config.json', '*.safetensors', 'README.md', 'LICENSE*']),
    ]
    manifest = {}
    for name, repository, patterns in models:
        cached = previous.get(name, {})
        files = cached.get('files', {})
        if files and not os.environ.get(name.upper() + '_REVISION') and all(
            (root / name / filename).is_file() and (root / name / filename).stat().st_size == length
            for filename, length in files.items()
        ):
            print(f'{name}: verified local snapshot, no network required', flush=True)
            manifest[name] = cached
            continue
        revision = os.environ.get(name.upper() + '_REVISION') or previous.get(name, {}).get('revision')
        if not revision:
            revision = HfApi().model_info(repository).sha
        destination = root / name
        print(f'Downloading {repository}@{revision} -> {destination}', flush=True)
        snapshot_download(repository, revision=revision, local_dir=destination, allow_patterns=patterns,
                          max_workers=4, token=os.environ.get('HF_TOKEN') or None)
        files = {str(path.relative_to(destination)): path.stat().st_size
                 for path in destination.rglob('*') if path.is_file() and '.cache' not in path.parts}
        manifest[name] = {'repository': repository, 'revision': revision, 'files': files}
    temporary = manifest_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, indent=2) + '\n')
    temporary.replace(manifest_path)
    print('All model snapshots ready. Runtime workers are offline.', flush=True)


if __name__ == '__main__':
    Path('/models').mkdir(parents=True, exist_ok=True)
    with FileLock('/models/download.lock', timeout=7200):
        main()
