import json
import math
import re
import subprocess
from pathlib import Path

from backend.app.config import settings


def video_dir(video_id: str) -> Path:
    if not re.fullmatch(r'video_[a-f0-9]{32}', video_id):
        raise ValueError('Invalid video id')
    return settings.data_dir / video_id


def probe(path: Path) -> dict:
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file',
            '-show_streams', '-show_format', '-of', 'json', str(path)],
            capture_output=True, timeout=20, check=True)
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError) as exc:
        raise ValueError('Invalid or unsupported video') from exc


def normalize_video(source: Path, destination: Path) -> dict[str, int | float]:
    info = probe(source)
    streams = [stream for stream in info.get('streams', []) if stream.get('codec_type') == 'video']
    container = info.get('format', {})
    formats = set(container.get('format_name', '').split(','))
    if len(streams) != 1 or not formats.intersection({'mov', 'mp4', 'matroska', 'webm'}):
        raise ValueError('Upload an MP4, MOV or WebM with one video stream')
    stream = streams[0]
    duration = float(container.get('duration') or stream.get('duration') or 0)
    if not math.isfinite(duration) or not 0.25 <= duration <= settings.video_max_seconds:
        raise ValueError(f'Video must be 0.25–{settings.video_max_seconds} seconds; trim it before uploading')
    if not 0 < int(stream.get('width', 0)) * int(stream.get('height', 0)) <= 4096 * 2160:
        raise ValueError('Video resolution exceeds 4096 × 2160 pixels')
    width, height, fps = settings.video_width, settings.video_height, settings.video_fps
    filters = f'fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1'
    try:
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
            '-threads', '2', '-protocol_whitelist', 'file', '-i', str(source),
            '-map', '0:v:0', '-an', '-vf', filters, '-t', str(settings.video_max_seconds),
            '-frames:v', str(settings.video_max_seconds * fps), '-c:v', 'libx264',
            '-threads', '2', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '18',
            '-movflags', '+faststart', str(destination)], check=True, capture_output=True, timeout=120)
    except subprocess.SubprocessError as exc:
        raise ValueError('Video decoding failed or timed out') from exc
    normalized = probe(destination)
    output = next(stream for stream in normalized['streams'] if stream['codec_type'] == 'video')
    frames = int(output.get('nb_frames') or 0)
    if not 4 <= frames <= settings.video_max_seconds * fps:
        raise ValueError('Video has too few or too many decodable frames')
    return {'duration_seconds': frames / fps, 'width': width, 'height': height, 'fps': fps, 'frames': frames}
