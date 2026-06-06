import subprocess
import json
from dataclasses import dataclass
from ff_paths import FFPROBE


@dataclass
class VideoInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    size_bytes: int
    has_audio: bool


def probe_video(path: str) -> VideoInfo:
    cmd = [
        FFPROBE, "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    data = json.loads(result.stdout)

    duration = float(data["format"]["duration"])
    size = int(data["format"]["size"])

    video_stream = next(s for s in data["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])

    fps_str = video_stream.get("r_frame_rate", "30/1")
    num, den = fps_str.split("/")
    fps = float(num) / float(den) if float(den) != 0 else 30.0

    return VideoInfo(
        path=path,
        duration=duration,
        width=int(video_stream["width"]),
        height=int(video_stream["height"]),
        fps=fps,
        size_bytes=size,
        has_audio=has_audio,
    )
