import sys
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1])
    pipeline = root / 'model/pipeline.py'
    source = pipeline.read_text()
    old = 'AutoencoderKL.from_pretrained("stabilityai/sd-vae-ft-mse")'
    new = 'AutoencoderKL.from_pretrained(os.environ.get("VAE_MODEL_PATH", "/models/vae"))'
    if old not in source:
        raise RuntimeError('Unexpected upstream VAE loader; review pinned revision')
    source = source.replace(old, new)
    old = 'UNet2DConditionModel.from_pretrained(base_ckpt, subfolder="unet")'
    if old not in source:
        raise RuntimeError('Unexpected upstream UNet loader')
    source = source.replace(old, 'UNet2DConditionModel.from_pretrained(base_ckpt, subfolder="unet", variant="fp16", use_safetensors=True)')
    pipeline.write_text(source)
    schp = root / 'model/SCHP/__init__.py'
    source = schp.read_text()
    old = "torch.load(ckpt_path, map_location='cpu')"
    if old not in source:
        raise RuntimeError('Unexpected SCHP checkpoint loader')
    schp.write_text(source.replace(old, "torch.load(ckpt_path, map_location='cpu', weights_only=True)"))


if __name__ == '__main__':
    main()
