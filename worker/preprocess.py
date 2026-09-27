from PIL import Image, ImageOps


def prepare(image: Image.Image, size: tuple[int, int], garment: bool = False) -> Image.Image:
    rgb = ImageOps.exif_transpose(image).convert('RGB')
    if garment:
        return ImageOps.pad(rgb, size, method=Image.Resampling.LANCZOS, color='white')
    return ImageOps.fit(rgb, size, method=Image.Resampling.LANCZOS)
