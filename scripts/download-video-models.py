import json
import os
from pathlib import Path

from filelock import FileLock
from huggingface_hub import snapshot_download


def main() -> None:
    root = Path('/models')
    root.mkdir(parents=True, exist_ok=True)
    models = [
        ('video-base', 'alibaba-pai/EasyAnimateV4-XL-2-InP',
         '0bdb0bfc02bfe5f5497fd30b55f79e2ddebb630b', ['transformer/**', 'vae/**', 'scheduler/**', 'README.md', 'LICENSE*']),
        ('catv2ton', 'zhengchong/CatV2TON',
         'bbf2a004905cc0a4a5834c11d25590909143a990', ['512-64K/**', 'README.md', 'LICENSE*']),
    ]
    with FileLock('/models/video-download.lock', timeout=7200):
        manifest_path = root / 'video-manifest.json'
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        for name, repository, revision, patterns in models:
            previous = manifest.get(name, {})
            if previous.get('revision') == revision and previous.get('files') and all(
                (root / name / filename).is_file() and (root / name / filename).stat().st_size == length
                for filename, length in previous['files'].items()
            ):
                print(f'{name}: local snapshot verified', flush=True)
                continue
            print(f'Downloading {repository}@{revision}', flush=True)
            destination = snapshot_download(repository, revision=revision, local_dir=root / name,
                allow_patterns=patterns, max_workers=3, token=os.environ.get('HF_TOKEN') or None)
            files = {str(path.relative_to(destination)): path.stat().st_size
                     for path in Path(destination).rglob('*') if path.is_file() and '.cache' not in path.parts}
            manifest[name] = {'repository': repository, 'revision': revision, 'files': files}
        temporary = manifest_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(manifest, indent=2) + '\n')
        temporary.replace(manifest_path)


if __name__ == '__main__':
    main()
